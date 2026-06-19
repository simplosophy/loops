# Implementation Guide

Use this guide to choose the right entry point. The Loops documents have
different shapes because the layers have different roles.

| Document | Type | Meaning |
| --- | --- | --- |
| [HACP](./specs/hacp) | Full protocol specification | Loops defines this layer: schemas, state machine, operations, errors, and conformance. |
| [AAP](./specs/aap) | Conformance profile | Loops profiles the minimum L1 surface that existing agent protocols must expose. |
| [CAP](./specs/cap) | Conformance profile | Loops profiles the minimum L0 surface that MCP servers and Skills runtimes already approximate. |
| [Protocol Map](./protocol-map) | Implementation map | One-page ownership, operation, identity, and contract map for the full stack. |
| [Contracts](./specs/contracts) | Cross-layer reference | Loops defines how the layers join without leaking internal state. |

## Path 1: Build a Human-Agent Collaboration Platform

Read [HACP](./specs/hacp) first.

You are building this path if your system needs to represent accountable work:
assignments, human decision gates, artifact review, project ledger state, and
audit replay.

Implementation checklist:

- Implement all seven HACP objects: Task, Checkpoint, Ownership, Review,
  Artifact, Ledger, and Audit.
- Implement the 21 required HACP operations.
- Enforce the Task state machine and operation preconditions.
- Persist immutable specs, artifact versions, reviews, ledger entries, and audit
  events.
- Bridge downward to AAP for delegation, blocking, resuming, and handoff.

Expected work: large. HACP is a complete protocol surface.

## Path 2: Make an Agent Runtime Loops-Compatible

Read [AAP](./specs/aap), then [Inter-layer Contracts](./specs/contracts).

You are building this path if you already have an agent runtime, A2A runtime,
ACP broker, agent mesh, or multi-agent orchestrator and want it to sit under
HACP.

Implementation checklist:

- Expose `discover`, `delegate`, `block`, `resume`, and `handoff`.
- Return a run handle immediately from `delegate`.
- Attach `correlation_id` to every run and event.
- Set `Run.correlation_id = HACP TaskID`.
- Treat `block` as authoritative: an agent run must not resume itself while
  blocked by a HACP checkpoint.
- Preserve correlation during handoff.

Expected work: small to medium. Most of the work is correlation, state, and
event discipline.

## Path 3: Publish a Capability Source

Read [CAP](./specs/cap).

You are building this path if you provide tools, MCP servers, Skills, packaged
automation, retrieval functions, or other agent-callable capabilities.

Implementation checklist:

- Provide `capability.list`, `capability.describe`, and `capability.invoke`.
- Give every capability a globally unique `(capability_id, version)`.
- Publish an input schema for every capability.
- Return a structured `InvokeResult`.
- Use CAP error semantics for invalid input, missing capabilities, permission
  failures, execution failures, and timeouts.

Expected work: minimal for MCP servers and Skills runtimes; moderate for plain
function-calling registries that lack discovery.

## Path 4: Assemble a Complete Loops Stack

Read in dependency order:

1. [CAP](./specs/cap)
2. [AAP](./specs/aap)
3. [HACP](./specs/hacp)
4. [Protocol Map](./protocol-map)
5. [Inter-layer Contracts](./specs/contracts)
6. [Conformance](./conformance)

Build bottom-up:

- Start with one or more CAP providers.
- Add an AAP runtime that can discover and delegate to agents that use those
  providers.
- Add HACP on top to represent human-owned work, checkpoints, review, ledger,
  and audit.
- Verify that the cross-layer contracts hold in the full flow.

## Path 5: Evaluate an Existing Product

Use the [Conformance](./conformance) page as an audit checklist.

Ask four questions:

1. Does the product expose versioned capabilities through a CAP-compatible
   manifest and invocation result?
2. Does the product expose agent delegation through AAP-compatible runs and
   correlated events?
3. Does the product represent human-agent work through HACP tasks, checkpoints,
   reviews, artifacts, ledger entries, and audit events?
4. Can a single task identity survive every handoff from HACP through AAP to the
   executing runtime?

If any answer is no, the product may still be useful, but it should not claim
full Loops Protocol Stack conformance.

## Recommended First Flow

For a reference implementation, start with a single task:

```text
Human creates Task
  -> HACP task.assign
  -> AAP delegate with Run.correlation_id = TaskID
  -> Agent reaches a decision point
  -> HACP checkpoint.raise
  -> AAP block
  -> Human resolves the checkpoint
  -> AAP resume
  -> Agent commits Artifact
  -> Human submits Review
  -> Task reaches completed
  -> Audit replay reconstructs the flow
```

If this flow works without losing correlation or mutating immutable records, the
implementation has the core Loops shape.
