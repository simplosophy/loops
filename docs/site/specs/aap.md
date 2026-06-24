---
title: L1 Agent Protocol Routes
outline: [2, 3]
---

# L1 Agent Protocol Routes

HLP does not define a new agent-to-agent protocol. This page is an integration
guide for connecting HLP to existing L1 agent ecosystems.

Use this route when a Human Loop Platform needs an existing agent harness to
accept work, pause for checkpoints, resume after human decisions, project
human-facing events, and preserve task identity across delegation or handoff.

## What HLP Needs From L1

An agent harness can sit under HLP if an adapter can provide these semantics:

| HLP need | L1 expectation |
| --- | --- |
| Assign work | Start an asynchronous agent run and return a handle immediately. |
| Preserve identity | Carry `Task.id` as the run correlation id in every run event. |
| Raise checkpoints | Let HLP block a run at a human decision point. |
| Resolve checkpoints | Resume the blocked run with the human resolution payload. |
| Transfer ownership | Handoff execution while preserving the original task correlation. |
| Inspect progress | Emit correlated run events for audit and debugging. |
| Project human interaction | Turn approvals, choices, input requests, and artifacts into HLP objects. |

These are adapter obligations, not a new protocol surface. If A2A, ACP,
AGNTCY-style meshes, or a custom harness already expose equivalent behavior,
HLP should route through that implementation.

## Existing Protocol Routes

| Route | Use when | HLP adapter focus |
| --- | --- | --- |
| A2A-style runtime | Agents expose cards, tasks, and asynchronous status updates. | Store HLP `Task.id` in task metadata or an extension field and map status updates to run events. |
| ACP-style broker | Agents communicate through a broker or session-oriented channel. | Keep HLP task correlation outside session-local ids and prevent autonomous resume while blocked. |
| AGNTCY-style mesh | Agents are discovered and routed through a mesh or registry. | Treat mesh discovery as the L1 route and keep HLP ownership separate from mesh placement. |
| Custom runtime | The platform already owns agent scheduling. | Implement only the narrow adapter methods HLP needs: delegate, block, resume, handoff, and events. |

## Required Adapter Shape

The HLP reference implementation names the boundary `AgentAdapter`. It is an
HLP-to-agent-harness adapter, not a new L1 protocol, and historical AAP
compatibility aliases are not part of the public API:

```text
delegate(task_id, assignee, payload) -> run_id
block(task_id, checkpoint_id) -> void
resume(task_id, checkpoint_id, resolution) -> void
handoff(task_id, from_assignee, to_assignee, context) -> run_id
observe(run_id) -> human-facing harness events
```

The important invariant is correlation:

```yaml
Task:
  id: "task_01J0K7..."

AgentRun:
  run_id: "run_01J0K8..."
  correlation_id: "task_01J0K7..."
```

HLP compatibility fails if the agent harness loses that identity during
subdelegation, retries, handoff, or recovery.

## What HLP Does Not Standardize

HLP does not choose:

- Agent card schema.
- Broker topology.
- Agent authentication.
- Placement or scheduling policy.
- Multi-agent planning strategy.
- Internal run state beyond the checkpoint contract.
- Prompt, memory, tool trace, or planner internals unless needed for human
  decision evidence.

Those decisions belong to the existing L1 ecosystem or the host platform.

## Implementation Checklist

- Pick the existing agent protocol or runtime you already use.
- Add a HLP adapter at the platform boundary.
- Persist the mapping from `Task.id` to agent `run_id`.
- Ensure every run event carries the HLP task correlation id.
- Treat `checkpoint.raise` as authoritative: the run must remain blocked until
  HLP resolves the checkpoint.
- Project approval/input/artifact events into HLP through a harness adapter.
- Preserve correlation through handoff and child delegation.

For the exact HLP-side obligations, see [Integration Contracts](./contracts).
