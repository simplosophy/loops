# HLP SDK-Only Harness Control Plane Refactor Plan

## Goal

Reframe HLP as the SDK-only human-interaction control plane for existing agent
harnesses:

> HLP unifies human interaction semantics, not harness execution mechanisms.

The project should make it clear that Codex, Kimi, Claude Code, LangGraph,
CrewAI, OpenAI Agents SDK, and custom harnesses keep their own execution model.
HLP wraps their human-facing responsibility loop into common Task, Checkpoint,
Artifact, Review, Ledger, and Audit semantics. The project should not keep a
self-implemented `loop0` harness.

## Architecture Boundary

HLP owns:

- Human-owned work state: Task and Ownership.
- Human decision state: Checkpoint and resolution.
- Human acceptance state: Artifact and Review.
- Human-visible continuity: Ledger and Audit.
- Adapter contracts that preserve task/run correlation and project harness
  events into HLP objects.

HLP does not own:

- Tool calling.
- Agent planning.
- Agent memory.
- Harness-specific run internals.
- UI/channel rendering.
- Agent-to-agent protocols.
- A built-in agent harness or execution runtime.

## Implementation Shape

1. Remove the self-implemented harness surface.
   - Delete `loops/loop0`.
   - Delete loop0 demos/configs/prompts and console scripts.
   - Keep HLP tests focused on adapter contracts and protocol state.

2. Add a `HarnessAdapter` protocol and `HarnessEvent` value object.
   - `AgentAdapter` remains the command boundary.
   - `HarnessAdapter` adds capability metadata and optional event observation.
   - Harness events project into HLP objects but do not change harness execution.

3. Add a unified human interaction query API.
   - `HLPClient.human_inbox(principal)` returns pending human actions.
   - Checkpoints appear as decision items.
   - Review-ready artifacts appear as review items.

4. Add a deterministic fake harness demo.
   - Fake harness delegates a task.
   - It emits a human approval event.
   - HLP raises a checkpoint.
   - Human resolves it.
   - Fake harness emits an artifact.
   - HLP commits the artifact and exposes it in the review inbox.
   - Human review completes the task.

5. Update docs and site positioning.
   - HLP is a harness human-interaction control plane.
   - Adapter conformance is capability-based.
   - UI remains host application responsibility.
   - Current docs state that Loops does not ship a built-in harness.

## Acceptance Criteria

- `from loops import HarnessAdapter, HarnessEvent, FakeHarnessAdapter` works.
- `loops.loop0`, `loops-loop0`, `loops-demo`, and old loop0 examples are gone.
- Harness events can be projected into HLP checkpoints and artifacts.
- `HLPClient.human_inbox(principal)` returns unified checkpoint/review items.
- A dependency-free harness wrap demo runs end to end.
- README, HLP spec, architecture docs, and site copy consistently state the new
  positioning.
- Existing SDK, adapter, loop2, and site verification tests still pass.
