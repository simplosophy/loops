"""PR Review Desk — real host application embedding HLP.

This is intentionally a *host*, not another protocol demo:

- The desk owns PR domain language, inbox cards, and presentation.
- HLP owns task lifecycle, checkpoints, artifacts, reviews, ledger, audit.
- The harness adapter owns external code-review execution and human-facing
  event projection.

Default mode is offline and deterministic via an injected Codex harness
runner. Pass ``--live`` only when a local Codex CLI is available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from loops.hlp import (
    Artifact,
    Checkpoint,
    CodexHarnessAdapter,
    HarnessCapabilities,
    HLPHost,
    ProcessResult,
    Review,
    Task,
)
from loops.hlp.adapters import ProcessRunner


Decision = Literal["approve", "reject", "request_change"]


@dataclass(frozen=True)
class PullRequest:
    """Host-domain object. HLP never needs to know about GitHub/GitLab."""

    repository: str
    number: int
    title: str
    author: str
    base_ref: str = "main"
    head_ref: str = "feature/branch"
    diff_uri: str = ""

    @property
    def ref(self) -> str:
        return f"{self.repository}#{self.number}"

    def goal(self) -> str:
        return (
            f"Review pull request {self.ref}: {self.title}. "
            f"Author={self.author}; base={self.base_ref}; head={self.head_ref}."
        )


@dataclass
class ReviewSession:
    """Host session mapping a PR onto one HLP task + harness run."""

    pr: PullRequest
    task_id: str
    run_id: str | None = None
    agent_id: str = "agent_code_reviewer"
    status: str = "opened"


@dataclass(frozen=True)
class DeskCard:
    """Channel-ready presentation of a HumanInboxItem."""

    card_id: str
    kind: str
    action: str
    task_id: str
    subject_id: str
    title: str
    pr_ref: str
    principal: str


@dataclass
class DeskReport:
    """Final host-facing summary for operators / compliance."""

    pr_ref: str
    task_id: str
    run_id: str | None
    task_state: str
    checkpoint_id: str | None
    checkpoint_decision: str | None
    artifact_id: str | None
    artifact_uri: str | None
    review_id: str | None
    review_verdict: str | None
    ledger_status: Any
    audit_actions: list[str]
    inbox_remaining: list[str]
    steered: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PRReviewDesk:
    """Host application: PR review approval desk embedding HLPHost.

    Host code may grow web/IM channels on top of :meth:`list_inbox` without
    changing HLP. HLP remains the responsibility control plane.
    """

    def __init__(
        self,
        host: HLPHost,
        *,
        principal: str,
        reviewer: str | None = None,
        agent_id: str = "agent_code_reviewer",
        ledger_scope: str = "pr-review-desk",
    ) -> None:
        if not principal:
            raise ValueError("principal is required")
        self.host = host
        self.client = host.client
        self.principal = principal
        self.reviewer = reviewer or principal
        self.agent_id = agent_id
        self.ledger_scope = ledger_scope
        self._sessions: dict[str, ReviewSession] = {}
        self._pr_by_task: dict[str, PullRequest] = {}

    async def open_review(self, pr: PullRequest) -> ReviewSession:
        """Open a bounded HLP task for a PR and record host metadata."""
        task = await self.client.create_task(
            principal=self.principal,
            goal=pr.goal(),
            type="pr-review",
            acceptance_criteria=(
                "Security-sensitive findings are called out",
                "Human approved any external side effects",
                "Deliverable review report was accepted or rejected",
            ),
            inputs=(),
        )
        session = ReviewSession(pr=pr, task_id=task.id, agent_id=self.agent_id)
        self._sessions[task.id] = session
        self._pr_by_task[task.id] = pr
        await self.client.write_ledger(
            self.ledger_scope,
            f"pr:{pr.ref}:opened",
            {
                "task_id": task.id,
                "repository": pr.repository,
                "number": pr.number,
                "title": pr.title,
                "author": pr.author,
            },
            by=self.principal,
        )
        return session

    async def dispatch(self, session: ReviewSession) -> ReviewSession:
        """Delegate the PR to the external review harness and start the run."""
        pr = session.pr
        handle = await self.client.delegate(
            session.task_id,
            session.agent_id,
            capability="code-review",
            input={
                "goal": pr.goal(),
                "repository": pr.repository,
                "pull_request": pr.number,
                "base_ref": pr.base_ref,
                "head_ref": pr.head_ref,
                "diff_uri": pr.diff_uri or f"git://{pr.repository}/pull/{pr.number}.diff",
            },
        )
        await self.client.start(session.task_id)
        session.run_id = handle.run_id
        session.status = "in_progress"
        self._sessions[session.task_id] = session
        return session

    async def sync_harness(self, session: ReviewSession) -> list[Any]:
        """Project pending harness human-facing events into HLP objects."""
        if not session.run_id:
            raise RuntimeError("session has no harness run; call dispatch() first")
        return await self.client.project_harness_events(session.run_id)

    async def steer(
        self,
        session: ReviewSession,
        *,
        text: str,
        intent: str = "constrain",
    ) -> Task:
        """Inject continuous control without restarting the harness run."""
        return await self.client.amend(
            session.task_id,
            by=self.principal,
            text=text,
            intent=intent,  # type: ignore[arg-type]
        )

    async def list_inbox(self) -> list[DeskCard]:
        """Map HLP human inbox into host channel cards."""
        items = await self.client.human_inbox(self.principal)
        cards: list[DeskCard] = []
        for item in items:
            pr = self._pr_by_task.get(item.task_id)
            cards.append(DeskCard(
                card_id=f"{item.kind}:{item.subject_id}",
                kind=item.kind,
                action=item.action,
                task_id=item.task_id,
                subject_id=item.subject_id,
                title=item.title,
                pr_ref=pr.ref if pr is not None else item.task_id,
                principal=item.principal,
            ))
        return cards

    async def decide_checkpoint(
        self,
        card: DeskCard,
        *,
        decision: Decision,
        comment: str | None = None,
    ) -> Checkpoint:
        if card.action != "resolve_checkpoint":
            raise ValueError(f"card action is {card.action}, not resolve_checkpoint")
        action = {
            "approve": "approve",
            "reject": "reject",
            "request_change": "request_change",
        }[decision]
        return await self.client.resolve_checkpoint(
            card.subject_id,
            by=self.principal,
            action=action,  # type: ignore[arg-type]
            comment=comment,
        )

    async def decide_review(
        self,
        card: DeskCard,
        *,
        decision: Decision,
        comments: tuple[str, ...] = (),
    ) -> Review:
        if card.action != "submit_review":
            raise ValueError(f"card action is {card.action}, not submit_review")
        verdict = {
            "approve": "approved",
            "reject": "rejected",
            "request_change": "changes_requested",
        }[decision]
        review = await self.client.submit_review(
            task_id=card.task_id,
            artifact_id=card.subject_id,
            reviewer=self.reviewer,
            verdict=verdict,  # type: ignore[arg-type]
            kind="deliverable",
            requested_changes=comments if decision == "request_change" else (),
        )
        session = self._sessions.get(card.task_id)
        if session is not None:
            session.status = f"review_{verdict}"
        await self.client.write_ledger(
            self.ledger_scope,
            f"pr:{self._pr_ref(card.task_id)}:decision",
            {
                "task_id": card.task_id,
                "artifact_id": card.subject_id,
                "review_id": review.id,
                "verdict": review.verdict,
                "reviewer": self.reviewer,
            },
            by=self.reviewer,
        )
        return review

    async def report(self, session: ReviewSession) -> DeskReport:
        task = await self.client.get_task(session.task_id)
        audit = await self.client.replay_audit(session.task_id)
        ledger_status = await self.client.read_ledger(
            self.ledger_scope,
            f"pr:{session.pr.ref}:decision",
        )
        inbox = await self.list_inbox()
        checkpoint = self._latest_checkpoint(session.task_id)
        artifact = self._latest_artifact(task)
        reviews = (
            self.client.store.reviews_of_artifact(artifact.id)
            if artifact is not None
            else []
        )
        review = reviews[-1] if reviews else None
        return DeskReport(
            pr_ref=session.pr.ref,
            task_id=session.task_id,
            run_id=session.run_id,
            task_state=task.state,
            checkpoint_id=checkpoint.id if checkpoint else None,
            checkpoint_decision=(
                checkpoint.resolution.action
                if checkpoint is not None and checkpoint.resolution is not None
                else None
            ),
            artifact_id=artifact.id if artifact else None,
            artifact_uri=(
                artifact.payload.uri
                if artifact is not None and artifact.payload is not None
                else None
            ),
            review_id=review.id if review else None,
            review_verdict=review.verdict if review else None,
            ledger_status=ledger_status,
            audit_actions=[event.action for event in audit],
            inbox_remaining=[card.card_id for card in inbox if card.task_id == session.task_id],
            steered=bool(task.steering_log),
        )

    def _pr_ref(self, task_id: str) -> str:
        pr = self._pr_by_task.get(task_id)
        return pr.ref if pr is not None else task_id

    def _latest_checkpoint(self, task_id: str) -> Checkpoint | None:
        matches = [
            ckpt
            for ckpt in self.client.store.checkpoints.values()
            if ckpt.task_id == task_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.raised_at)

    def _latest_artifact(self, task: Task) -> Artifact | None:
        if not task.artifacts:
            return None
        artifact_id = task.artifacts[-1]
        return self.client.store.get_artifact(artifact_id)


def offline_review_harness_runner(
    command: tuple[str, ...],
    request: dict[str, Any],
    timeout: float,
) -> ProcessResult:
    """Deterministic code-review harness used by offline desk demos/tests."""
    correlation = str(request.get("correlation_id") or "")
    run_id = str(request.get("run_id") or f"pr_run_{correlation[-8:] or 'demo'}")
    agent_id = str(request.get("agent_id") or "agent_code_reviewer")
    op = request.get("operation")

    if op == "delegate":
        # First turn: ask human before posting comments / applying side effects.
        return ProcessResult(
            exit_code=0,
            stdout="\n".join((
                json.dumps({
                    "type": "hlp.event",
                    "run_id": run_id,
                    "correlation_id": correlation,
                    "hlp": {
                        "kind": "needs_approval",
                        "agent_id": agent_id,
                        "prompt": (
                            "Allow the review agent to post findings as PR comments "
                            "and open follow-up issues for high severity findings?"
                        ),
                    },
                }),
                json.dumps({
                    "type": "turn.completed",
                    "run_id": run_id,
                    "correlation_id": correlation,
                    "status": "blocked",
                    "summary": "Waiting for human approval of external side effects",
                }),
            )),
            stderr="",
        )

    if op == "resume":
        resolution = request.get("resolution")
        action = ""
        if isinstance(resolution, dict):
            action = str(resolution.get("action") or "")
        elif hasattr(resolution, "action"):
            action = str(getattr(resolution, "action") or "")
        # Rejected checkpoints end the HLP task; harness must not emit deliverables.
        if action in {"reject", "rejected"}:
            return ProcessResult(
                exit_code=0,
                stdout=json.dumps({
                    "type": "turn.completed",
                    "run_id": run_id,
                    "correlation_id": correlation,
                    "status": "cancelled",
                    "summary": "Harness stopped after human rejected side effects",
                }),
                stderr="",
            )
        # After approval: produce the review report artifact.
        return ProcessResult(
            exit_code=0,
            stdout="\n".join((
                json.dumps({
                    "type": "hlp.event",
                    "run_id": run_id,
                    "correlation_id": correlation,
                    "hlp": {
                        "kind": "artifact",
                        "agent_id": agent_id,
                        "artifact_type": "review-report",
                        "artifact_uri": "mem://pr-review-report",
                        "artifact_checksum": "sha256:pr-review-report-v1",
                        "artifact_size": 2048,
                    },
                }),
                json.dumps({
                    "type": "turn.completed",
                    "run_id": run_id,
                    "correlation_id": correlation,
                    "status": "ok",
                    "summary": "Review report ready for human acceptance",
                }),
            )),
            stderr="",
        )

    if op == "steer":
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "type": "turn.completed",
                "run_id": run_id,
                "correlation_id": correlation,
                "status": "ok",
                "summary": "Steering applied without restart",
            }),
            stderr="",
        )

    return ProcessResult(
        exit_code=0,
        stdout=json.dumps({
            "type": "turn.completed",
            "run_id": run_id,
            "correlation_id": correlation,
            "status": "ok",
        }),
        stderr="",
    )


def build_desk(
    *,
    live: bool = False,
    runner: ProcessRunner | None = None,
    db_path: str | Path | None = None,
    principal: str = "user_alice",
    reviewer: str = "user_alice",
) -> PRReviewDesk:
    """Construct a desk with either offline injectable runner or live Codex."""
    if live and runner is not None:
        raise ValueError("live mode cannot take a custom runner")
    adapter = CodexHarnessAdapter(
        command=(
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--ephemeral",
        ),
        runner=None if live else (runner or offline_review_harness_runner),
        timeout=180.0,
        capabilities=HarnessCapabilities(
            name="codex-pr-review",
            conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
            description="Code-review harness projected into HLP for PR Review Desk.",
        ),
    )
    if db_path is None:
        host = HLPHost.in_memory(adapter=adapter)
    else:
        host = HLPHost.sqlite(db_path, adapter=adapter)
    return PRReviewDesk(host, principal=principal, reviewer=reviewer)


async def run_desk_demo(
    *,
    live: bool = False,
    runner: ProcessRunner | None = None,
    db_path: str | Path | None = None,
    principal: str = "user_alice",
    reviewer: str = "user_alice",
    approve_side_effects: bool = True,
    accept_report: bool = True,
    steer_text: str = "Focus on authentication, authorization, and secret handling.",
) -> dict[str, Any]:
    """Run one complete PR review through the host desk."""
    owns_db = False
    if db_path is None and not live:
        tmp = tempfile.NamedTemporaryFile(prefix="hlp-pr-desk-", suffix=".db", delete=False)
        tmp.close()
        db_path = tmp.name
        owns_db = True

    desk = build_desk(
        live=live,
        runner=runner,
        db_path=db_path,
        principal=principal,
        reviewer=reviewer,
    )
    pr = PullRequest(
        repository="acme/payments-api",
        number=1234,
        title="Add scoped API tokens for partner webhooks",
        author="dev_bob",
        base_ref="main",
        head_ref="feature/partner-tokens",
        diff_uri="git://acme/payments-api/pull/1234.diff",
    )

    session = await desk.open_review(pr)
    session = await desk.dispatch(session)

    # Continuous control: steer before the human approval lands.
    if steer_text:
        await desk.steer(session, text=steer_text, intent="constrain")

    projected = await desk.sync_harness(session)
    assert projected, "expected harness to raise a human checkpoint"
    inbox = await desk.list_inbox()
    checkpoint_cards = [card for card in inbox if card.action == "resolve_checkpoint"]
    if not checkpoint_cards:
        raise RuntimeError("desk inbox has no checkpoint cards after harness sync")
    checkpoint = await desk.decide_checkpoint(
        checkpoint_cards[0],
        decision="approve" if approve_side_effects else "reject",
        comment=(
            "Approved for read-only comment posting"
            if approve_side_effects
            else "Rejected external side effects"
        ),
    )

    artifact: Artifact | None = None
    review: Review | None = None
    if approve_side_effects:
        more = await desk.sync_harness(session)
        artifact = next((item for item in more if isinstance(item, Artifact)), None)
        if artifact is None and more:
            # project_harness_events returns Artifact objects directly
            artifact = more[0] if hasattr(more[0], "payload") else None
        inbox = await desk.list_inbox()
        review_cards = [card for card in inbox if card.action == "submit_review"]
        if review_cards:
            review = await desk.decide_review(
                review_cards[0],
                decision="approve" if accept_report else "request_change",
                comments=(
                    ()
                    if accept_report
                    else ("Expand auth boundary analysis for partner scopes",)
                ),
            )

    report = await desk.report(session)
    result = {
        "mode": "live" if live else "offline",
        "db_path": str(db_path) if db_path is not None else None,
        "principal": principal,
        "reviewer": reviewer,
        "session": {
            "task_id": session.task_id,
            "run_id": session.run_id,
            "status": session.status,
            "pr": asdict(pr),
        },
        "checkpoint": {
            "id": checkpoint.id,
            "state": checkpoint.state,
            "action": (
                checkpoint.resolution.action
                if checkpoint.resolution is not None
                else None
            ),
        },
        "artifact_id": artifact.id if artifact is not None else report.artifact_id,
        "review_id": review.id if review is not None else report.review_id,
        "report": report.to_dict(),
        "host_events": [event.action for event in desk.host.events],
    }

    if owns_db and db_path is not None:
        # Keep file for inspection only when caller asked; demo temp is cleaned
        # by OS eventually. Tests pass explicit paths.
        Path(db_path).unlink(missing_ok=True)
        result["db_path"] = None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the PR Review Desk host: embed HLP as the human-control plane "
            "for a code-review harness."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the local Codex CLI instead of the offline injectable runner.",
    )
    parser.add_argument(
        "--db",
        default="",
        help="Optional SQLite path for durable desk state (default: temp offline DB).",
    )
    parser.add_argument("--principal", default="user_alice")
    parser.add_argument("--reviewer", default="user_alice")
    parser.add_argument(
        "--reject-side-effects",
        action="store_true",
        help="Reject the harness side-effect checkpoint instead of approving.",
    )
    parser.add_argument(
        "--request-changes",
        action="store_true",
        help="Request changes on the deliverable instead of approving it.",
    )
    parser.add_argument(
        "--no-steer",
        action="store_true",
        help="Skip continuous-control steering amendment.",
    )
    args = parser.parse_args()

    result = asyncio.run(run_desk_demo(
        live=args.live,
        db_path=args.db or None,
        principal=args.principal,
        reviewer=args.reviewer,
        approve_side_effects=not args.reject_side_effects,
        accept_report=not args.request_changes,
        steer_text="" if args.no_steer else (
            "Focus on authentication, authorization, and secret handling."
        ),
    ))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
