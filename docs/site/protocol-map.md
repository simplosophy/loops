# Protocol Map

This page is the compact implementation map for the Loops Protocol Stack. Use it
when you need to decide which layer owns a behavior, which object carries state,
and which contract joins two layers.

## Layer Responsibility Map

| Layer | Protocol | Owns | Does not own |
| --- | --- | --- | --- |
| L2 | HLP | Human-owned work, checkpoints, reviews, artifacts, ledger entries, audit events | Tool transport, model execution loops, raw capability calls |
| L1 | AAP | Agent discovery, delegation, run lifecycle, block/resume, handoff, correlated events | Human review policy, artifact review verdicts, capability implementation |
| L0 | CAP | Capability manifests, schemas, invocation, structured results, capability errors | Agent planning, task ownership, human approvals |

The allowed dependency direction is always downward:

```text
HLP (L2) -> AAP (L1) -> CAP (L0)
```

Lower layers expose capabilities and events. They do not import the business
semantics of higher layers.

## Protocol Surface Map

| Concern | HLP | AAP | CAP |
| --- | --- | --- | --- |
| Discovery | Optional host-specific task templates | `agent.discover` | `capability.list`, `capability.describe` |
| Start work | `task.create`, `task.assign` | `agent.delegate` | Not applicable |
| Pause work | `checkpoint.raise` | `agent.block` | Invocation timeout or error only |
| Resume work | `checkpoint.resolve` | `agent.resume` | Not applicable |
| Transfer work | `ownership.transfer` | `agent.handoff` | Not applicable |
| Produce output | `artifact.commit` | `run.completed` event | `capability.invoke` result |
| Review output | `review.open`, `review.submit` | Emits correlated run events | Not applicable |
| Audit | `audit.query`, `audit.replay` | Correlated run event stream | Structured invocation result and error records |

## Object Ownership Map

| Object | Owner | Stable identity | Mutability rule |
| --- | --- | --- | --- |
| Task | HLP | `task_id` | State changes are explicit transitions; task spec is immutable. |
| Checkpoint | HLP | `checkpoint_id` | Resolution is append-only and auditable. |
| Ownership | HLP | Task-scoped ownership chain | Transfers append records; history remains visible. |
| Review | HLP | `review_id` | Submitted reviews are immutable. |
| Artifact | HLP | `artifact_id` plus version | Versions are immutable; new content creates a new version. |
| Run | AAP | `run_id` | State follows AAP transitions; `correlation_id` is stable. |
| Capability | CAP | `(capability_id, version)` | Manifests are versioned; invocation results are records. |

## Layer Contract Map

These four contracts are required for full-stack interoperability.

| Contract | Rule | Evidence |
| --- | --- | --- |
| `CapabilityRef` | Upper layers reference capabilities only by `(capability_id, version)`. | HLP task constraints and AAP invocation plans contain no transport endpoints. |
| `TaskID` correlation | `HLP Task.id` **MUST** equal `AAP Run.correlation_id`. | Every AAP run event for the task carries the same correlation id. |
| Checkpoint-to-Block | `checkpoint.raise` **MUST** block the AAP run; `checkpoint.resolve` **MUST** resume it. | Audit replay shows the checkpoint and run state transition as one logical pause. |
| Ownership-to-Handoff | `ownership.transfer` **MUST** preserve correlation through AAP handoff. | The new run uses the original `TaskID` as `correlation_id`. |

## End-to-End Flow

```text
Human principal
  -> HLP task.create
  -> HLP task.assign
  -> AAP agent.delegate(correlation_id = TaskID)
  -> AAP run.started
  -> CAP capability.invoke(CapabilityRef)
  -> AAP run.progress
  -> HLP checkpoint.raise
  -> AAP agent.block
  -> HLP checkpoint.resolve
  -> AAP agent.resume
  -> HLP artifact.commit
  -> HLP review.submit
  -> HLP audit.replay
```

The flow is conforming only if the same task identity can be followed from
human assignment through agent execution, capability use, checkpoint handling,
artifact review, and audit replay.

## Implementation Boundaries

| If you are building... | Implement first | Then prove |
| --- | --- | --- |
| A capability source | CAP | Capabilities have stable ids, schemas, structured results, and typed errors. |
| An agent runtime | AAP | Runs are discoverable, delegateable, blockable, resumable, handoff-capable, and correlated. |
| A collaboration platform | HLP | Tasks, checkpoints, reviews, artifacts, ledger entries, and audit events are first-class records. |
| A complete Loops stack | CAP -> AAP -> HLP | The four layer contracts hold in a replayable end-to-end trace. |

## Conformance Shortcut

A system may claim a single layer without implementing the whole stack. A system
must not claim full Loops stack compatibility unless it satisfies CAP, AAP, HLP,
and every layer contract listed on this page.

Use [Conformance](./conformance) for normative requirements and
[Inter-layer Contracts](./specs/contracts) for deeper contract examples.
