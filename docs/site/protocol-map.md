# HLP Integration Map

This page is the compact map for embedding HLP in an existing AI system. HLP is
the project-defined protocol and SDK. L1 and L0 are integration routes to agent
harness and capability ecosystems the host platform already uses.

## Responsibility Map

| Boundary | Owned here | Routed elsewhere |
| --- | --- | --- |
| HLP | Human-owned tasks, checkpoints, reviews, artifacts, ledger entries, audit events | Agent execution loops, tool invocation, provider transport |
| L1 agent route | Task-to-run correlation, block/resume, handoff adapters, harness event projection | Existing harnesses, A2A, ACP, AGNTCY-style meshes, custom harnesses |
| L0 capability route | Stable capability references and provenance | MCP, Agent Skills, local tools, function-calling registries |

The allowed dependency direction remains downward:

```text
HLP -> agent protocol route -> capability protocol route
```

Lower routes expose capabilities and events. They do not import HLP business
objects.

## Operation Map

| Concern | HLP operation | Adapter expectation |
| --- | --- | --- |
| Start human-owned work | `task.create`, `task.assign` | Delegate to an agent run and return a correlated run handle. |
| Observe harness start | `task.start` | Mark the HLP task in progress only for the correlated run. |
| Pause for human decision | `checkpoint.raise` | Block the corresponding agent run. |
| Resume after decision | `checkpoint.resolve` | Resume the run with the resolution payload. |
| Transfer responsibility | `ownership.transfer` | Handoff execution while preserving task correlation. |
| Project harness events | `checkpoint.raise`, `artifact.commit` | Convert approval, input, choice, and artifact events into HLP objects. |
| Produce output | `artifact.commit` | Preserve provenance from agent and capability use. |
| Review output | `review.submit`, `review.comment` | Feed human verdicts back to the agent route when changes are requested. |
| Audit | `audit.query`, `audit.replay` | Keep enough correlated run/capability evidence to replay the task. |

## Identity Map

| Object | Owner | Stable identity | Rule |
| --- | --- | --- | --- |
| Task | HLP | `task_id` | Primary identity for the human loop. |
| Checkpoint | HLP | `checkpoint_id` | Human decision point attached to a task. |
| Review | HLP | `review_id` | Immutable human verdict and feedback. |
| Artifact | HLP | `artifact_id` plus version | Immutable deliverable with provenance. |
| Agent run | L1 route | Runtime-specific `run_id` | Must carry HLP `Task.id` as correlation. |
| Capability | L0 route | `(capability_id, version)` | Must be referenced without exposing transport. |

## Integration Contracts

| Contract | Rule | Evidence |
| --- | --- | --- |
| `CapabilityRef` | HLP references capabilities only by `(capability_id, version)`. | Task constraints contain no transport endpoints or local command strings. |
| TaskID correlation | HLP `Task.id` survives every agent run and event. | Run/event metadata carries the same task id. |
| Checkpoint-to-Block | `checkpoint.raise` blocks the corresponding run; `checkpoint.resolve` resumes it. | Audit replay shows the checkpoint and run transition as one logical pause. |
| Harness event projection | Harness approval/input/artifact events become HLP objects. | Human inbox and audit show checkpoints and reviews without harness internals. |
| Ownership-to-Handoff | `ownership.transfer` preserves task correlation through handoff. | The receiving run keeps the original HLP task id. |

## End-to-End Flow

```text
Human principal
  -> HLP task.create
  -> HLP task.assign
  -> Harness delegate(correlation_id = TaskID)
  -> Harness run.started
  -> HLP task.start
  -> L0 capability invoked by the harness
  -> Harness emits needs_approval
  -> HLP checkpoint.raise
  -> Harness block
  -> HLP checkpoint.resolve
  -> Harness resume
  -> Harness emits artifact
  -> HLP artifact.commit
  -> HLP review.submit
  -> HLP audit.replay
```

The flow is compatible only if the same task identity can be followed from
human assignment through agent execution, capability use, checkpoint handling,
artifact review, and audit replay.

## Implementation Boundaries

| If you are building... | Implement | Then prove |
| --- | --- | --- |
| A Human Loop Platform | HLP | Tasks, checkpoints, reviews, artifacts, ledger entries, and audit events are first-class records. |
| An agent harness adapter | L1 route | Runs are delegateable, blockable, resumable, handoff-capable, correlated, and able to project human-facing events. |
| A capability adapter | L0 route | Capabilities have stable ids, manifests, provenance, and hidden transport. |

Use [HLP Conformance](./conformance) for compatibility requirements and
[Integration Contracts](./specs/contracts) for deeper contract examples.
