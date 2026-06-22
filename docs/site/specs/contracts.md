# Inter-layer Contracts

This page is the quick reference for the contracts that join the Loops layers.
Most interoperability bugs happen here.

## Contract Summary

| Contract | Cross-layer object | Layers | Rule |
| --- | --- | --- | --- |
| `CapabilityRef` | Capability reference | L0 -> L1 -> L2 | Upper layers reference capabilities only by `(capability_id, version)`. |
| TaskID correlation | Task and Run identity | L2 -> L1 | `HLP Task.id` **MUST** equal `AAP Run.correlation_id`. |
| Checkpoint-to-Block | Checkpoint and Run state | L2 <-> L1 | `checkpoint.raise` **MUST** block the corresponding run; `checkpoint.resolve` **MUST** resume it. |
| Ownership-to-Handoff | Ownership transfer and Run handoff | L2 <-> L1 | `ownership.transfer` **MUST** preserve correlation through AAP handoff. |

## Contract 1: CapabilityRef

`CapabilityRef` is the only legal way for upper layers to refer to a capability.

```yaml
CapabilityRef:
  capability_id: string
  version: string
```

Required behavior:

- CAP creates and owns the capability identity.
- AAP calls capabilities by reference.
- HLP uses references in task constraints such as `must_use_capabilities`.
- AAP and HLP **MUST NOT** know whether the capability is reached through MCP
  stdio, MCP SSE, HTTP, a local function, or a Skills runtime.

Non-conforming behavior:

```yaml
must_use_capabilities:
  - transport: "stdio"
    command: "node server.js"
```

Conforming behavior:

```yaml
must_use_capabilities:
  - capability_id: "cap:code-review"
    version: "2.1.0"
```

## Contract 2: TaskID Correlation

TaskID correlation is the most important full-stack invariant.

When HLP assigns a task to an agent, the resulting AAP run **MUST** carry the
same identity:

```yaml
Task:
  id: "task_01J0K7..."

Run:
  run_id: "run_01J0K8..."
  correlation_id: "task_01J0K7..."
```

Required behavior:

- `task.assign` calls `agent.delegate`.
- `DelegateRequest.task_id` becomes `Run.correlation_id`.
- Every AAP event includes the same `correlation_id`.
- Child delegations and handoffs preserve the original correlation unless a new
  HLP task is explicitly created.

This invariant lets audit replay reconstruct the complete lifecycle of a human
task across agent runs, subdelegations, checkpoints, and artifact commits.

## Contract 3: Checkpoint-to-Block

HLP checkpoints are human decision points. AAP block/resume is how those
decision points affect the executing agent run.

```text
Agent reaches a decision point
  -> HLP checkpoint.raise
  -> Task state becomes blocked
  -> AAP agent.block(run_id, checkpoint_id)
  -> Human resolves the checkpoint
  -> HLP checkpoint.resolve
  -> AAP agent.resume(run_id, resolution)
```

Required behavior:

- `checkpoint.raise` **MUST** identify the affected task and corresponding run.
- `agent.block` **MUST** carry `checkpoint_id`.
- A blocked run **MUST NOT** resume itself.
- `checkpoint.resolve` **MUST** pass the human resolution to `agent.resume`.
- Resolution and resume **SHOULD** be auditable as one logical transition.

## Contract 4: Ownership-to-Handoff

HLP ownership expresses who is responsible for a task. AAP handoff expresses how
an agent run transfers execution to another agent.

Required behavior:

- `ownership.transfer` changes the HLP assignee and appends an ownership chain
  record.
- When the new assignee is another agent, the implementation **MUST** call AAP
  `agent.handoff`.
- The new run **MUST** keep the original `correlation_id`.
- The old run **SHOULD** remain visible as read-only history.

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

## Dependency Direction

The only allowed dependency direction is downward:

```text
HLP (L2) -> AAP (L1) -> CAP (L0)
```

The reverse direction is forbidden:

- CAP **MUST NOT** import or depend on AAP or HLP.
- AAP **MUST NOT** import or depend on HLP business semantics.
- HLP **MUST NOT** call concrete tools or skills directly.

## Event Responsibilities

| Layer | Emits | Consumed by |
| --- | --- | --- |
| CAP | Capability invocation results and capability errors | AAP runtime |
| AAP | Run events with `correlation_id` | HLP bridge and host platform |
| HLP | Task, checkpoint, review, artifact, ledger, and audit events | Channels, UIs, project systems |

HLP produces events, but it does not define how those events are rendered in
chat, web, mobile, or CLI channels. Delivery belongs to the host platform.
