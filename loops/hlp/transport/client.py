"""Reference wire client for the HLP HTTP transport binding.

Wire-level client: results are wire dicts (the wire is the contract, §6.4).
Typed reconstruction (from_wire) is a documented follow-up. Stdlib only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


class TransportError(RuntimeError):
    """Server returned a non-2xx status; carries the §6.2 error object."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        error = payload.get("error") if isinstance(payload, dict) else None
        error = error if isinstance(error, dict) else {}
        self.status = status
        self.code = str(error.get("code") or "INTERNAL")
        self.details = error.get("details") or {}
        self.retryable = bool(error.get("retryable"))
        super().__init__(f"[{self.code}] {error.get('message') or status} (HTTP {status})")


@dataclass(frozen=True)
class HttpHLPWireClient:
    """Stdlib reference client for the HLP HTTP transport."""

    base_url: str
    principal: str = ""
    timeout: float = 30.0

    # ── protocol surface ──

    def call(
        self,
        operation: str,
        params: dict[str, Any] | None = None,
        *,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
        principal: str | None = None,
    ) -> Any:
        """POST /v1/ops/<operation> and return the wire result."""
        body: dict[str, Any] = {"params": params or {}}
        if expected_task_revision is not None:
            body["expected_task_revision"] = expected_task_revision
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        headers = {"Content-Type": "application/json"}
        actor = principal if principal is not None else self.principal
        if actor:
            headers["X-HLP-Principal"] = actor
        request = urllib.request.Request(
            f"{self.base_url}/v1/ops/{operation}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._send(request)

    def version(self) -> dict[str, Any]:
        return self._get("/v1/version")

    def health(self) -> dict[str, Any]:
        return self._get("/v1/health")

    def events(self, *, after: int = 0, max_seconds: float = 5.0) -> Iterator[dict[str, Any]]:
        """Iterate audit events from the SSE stream (§3.9), oldest first."""
        url = f"{self.base_url}/v1/events?after={after}&max_seconds={max_seconds}"
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout + max_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if line.startswith("data: "):
                    yield json.loads(line.removeprefix("data: "))

    # ── lifecycle convenience helpers (thin, wire-level) ──

    def create_task(self, *, principal: str, goal: str, **params: Any) -> dict[str, Any]:
        return self.call(
            "task.create",
            {"principal": principal, "goal": goal, **params},
            principal=principal,
        )

    def assign(self, task_id: str, agent_id: str, **params: Any) -> dict[str, Any]:
        return self.call("task.assign", {"task_id": task_id, "agent_id": agent_id, **params})

    def start(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.call("task.start", {"task_id": task_id}, **kwargs)

    def amend(
        self, task_id: str, *, text: str, intent: str = "clarify", **kwargs: Any
    ) -> dict[str, Any]:
        return self.call(
            "task.amend", {"task_id": task_id, "text": text, "intent": intent}, **kwargs
        )

    def interrupt(self, task_id: str, *, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return self.call("task.interrupt", {"task_id": task_id, "prompt": prompt}, **kwargs)

    def resolve_checkpoint(
        self, checkpoint_id: str, *, action: str, **params: Any
    ) -> dict[str, Any]:
        return self.call(
            "checkpoint.resolve",
            {"ckpt_id": checkpoint_id, "action": action, **params},
        )

    def raise_checkpoint(
        self, *, task_id: str, kind: str, prompt: str, raised_by: str, **params: Any
    ) -> dict[str, Any]:
        return self.call(
            "checkpoint.raise",
            {
                "task_id": task_id,
                "kind": kind,
                "prompt": prompt,
                "raised_by": raised_by,
                **params,
            },
        )

    def commit_artifact(
        self, *, task_id: str, type: str, payload: dict[str, Any], produced_by: str, **params: Any
    ) -> dict[str, Any]:
        return self.call(
            "artifact.commit",
            {
                "task_id": task_id,
                "type": type,
                "payload": payload,
                "produced_by": produced_by,
                **params,
            },
        )

    def submit_review(
        self, *, task_id: str, artifact_id: str, verdict: str, **params: Any
    ) -> dict[str, Any]:
        return self.call(
            "review.submit",
            {"task_id": task_id, "artifact_id": artifact_id, "verdict": verdict, **params},
        )

    def write_ledger(
        self, scope: str, key: str, value: Any, *, by: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call(
            "ledger.write", {"scope": scope, "key": key, "value": value, "by": by}, **kwargs
        )

    def replay_audit(self, task_id: str) -> list[dict[str, Any]]:
        return self.call("audit.replay", {"task_id": task_id})

    def human_inbox(self, principal: str | None = None) -> list[dict[str, Any]]:
        return self.call(
            "human.inbox",
            {},
            principal=principal if principal is not None else self.principal,
        )

    # ── internals ──

    def _get(self, path: str) -> Any:
        return self._send(urllib.request.Request(f"{self.base_url}{path}", method="GET"))

    def _send(self, request: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:  # noqa: BLE001 - non-JSON error body
                payload = {"error": {"code": "INTERNAL", "message": str(exc)}}
            raise TransportError(exc.code, payload) from exc
