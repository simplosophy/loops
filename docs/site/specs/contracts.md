# HLP Integration Contracts

This page defines the narrow contracts HLP expects when it routes work into an
existing agent runtime and capability ecosystem. These contracts do not define a
new L1 or L0 protocol; they define the adapter invariants HLP relies on.

## Contract Summary

| Contract | Cross-boundary object | Rule |
| --- | --- | --- |
| `CapabilityRef` | Capability reference | HLP references capabilities only by `(capability_id, version)`. |
| TaskID correlation | Task and agent run identity | HLP `Task.id` must survive every delegated run and event. |
| Checkpoint-to-Block | Checkpoint and run state | `checkpoint.raise` blocks the corresponding run; `checkpoint.resolve` resumes it. |
| Ownership-to-Handoff | Ownership transfer and run handoff | `ownership.transfer` preserves task correlation through handoff. |

## Contract 1: CapabilityRef

`CapabilityRef` is the only legal way for HLP to refer to a capability.

```yaml
CapabilityRef:
  capability_id: string
  version: string
```

Required behavior:

- Capability identities are created by the host capability ecosystem.
- HLP uses references in task constraints such as `must_use_capabilities`.
- HLP must not know whether the capability is reached through MCP stdio, MCP
  SSE, HTTP, a local function, or an Agent Skills runtime.

Non-compatible behavior:

```yaml
must_use_capabilities:
  - transport: "stdio"
    command: "node server.js"
```

Compatible behavior:

```yaml
must_use_capabilities:
  - capability_id: "cap:code-review"
    version: "2.1.0"
```

## Contract 2: TaskID Correlation

TaskID correlation is the most important integration invariant.

When HLP assigns a task to an agent, the resulting agent run must carry the same
identity:

```yaml
Task:
  id: "task_01J0K7..."

AgentRun:
  run_id: "run_01J0K8..."
  correlation_id: "task_01J0K7..."
```

Required behavior:

- `task.assign` delegates work through the L1 adapter.
- The adapter stores the mapping from HLP `Task.id` to runtime `run_id`.
- Every run event includes the same correlation id.
- Child delegations and handoffs preserve the original correlation unless a new
  HLP task is explicitly created.

This invariant lets audit replay reconstruct the complete lifecycle of a human
task across agent runs, subdelegations, checkpoints, and artifact commits.

## Contract 3: Checkpoint-to-Block

HLP checkpoints are human decision points. The L1 route is responsible for
making that decision point affect the executing agent run.

```text
Agent reaches a decision point
  -> HLP checkpoint.raise
  -> Task state becomes blocked
  -> L1 adapter blocks the run
  -> Human resolves the checkpoint
  -> HLP checkpoint.resolve
  -> L1 adapter resumes the run with the resolution
```

Required behavior:

- `checkpoint.raise` identifies the affected task and corresponding run.
- The adapter blocks the run with the checkpoint id.
- A blocked run must not resume itself.
- `checkpoint.resolve` passes the human resolution to the run.
- Resolution and resume should be auditable as one logical transition.

## Contract 4: Ownership-to-Handoff

HLP ownership expresses who is responsible for a task. The L1 route expresses
how execution moves to another agent or human-operated worker.

Required behavior:

- `ownership.transfer` changes the HLP assignee and appends an ownership chain
  record.
- When the new assignee requires a different agent run, the adapter performs
  the runtime-specific handoff.
- The receiving run keeps the original HLP task correlation id.
- The old run should remain visible as read-only history if the runtime
  supports it.

Example:

```yaml
OwnershipTransfer:
  from: "agent_reviewer"
  to: "agent_security"
  via: "handoff"

NewRun:
  agent_id: "agent_security"
  correlation_id: "task_01J0K7..."
```

## Event Responsibilities

| Boundary | Emits | Consumed by |
| --- | --- | --- |
| Capability route | Capability invocation results and capability errors | Agent runtime or host platform |
| Agent route | Run events with HLP task correlation | HLP adapter and host platform |
| HLP | Task, checkpoint, review, artifact, ledger, and audit events | Channels, UIs, project systems |

HLP produces events, but it does not define how those events are rendered in
chat, web, mobile, or CLI channels. Delivery belongs to the host platform.
