# Implementation Guide

Use this guide to choose the right entry point. HLP is the only complete
protocol specification in this project. L1 and L0 pages are routing references
for integrating with existing agent harness and capability ecosystems.

| Document | Type | Meaning |
| --- | --- | --- |
| [HLP](./specs/hlp) | Full protocol specification | The primary spec: schemas, state machine, operations, errors, and conformance. |
| [Agent Protocol Routes](./specs/aap) | L1 routing reference | How HLP can delegate into A2A, ACP, AGNTCY-style meshes, or custom runtimes. |
| [Capability Protocol Routes](./specs/cap) | L0 routing reference | How HLP references capabilities exposed through MCP, Agent Skills, local tools, or registries. |
| [Integration Map](./protocol-map) | Implementation map | One-page ownership, operation, identity, and adapter boundary map. |
| [Contracts](./specs/contracts) | Cross-layer reference | The narrow contracts HLP expects harness adapters to preserve. |

## Path 0: Embed the HLP SDK

Start from the public Python surface when you are building an application or
host process:

```python
from loops import FakeAgentAdapter, HLPHost

host = HLPHost.in_memory(adapter=FakeAgentAdapter())
client = host.client
```

Use `HLPHost` to wire store, event bus, and harness adapters. Use `HLPClient`
for task, checkpoint, artifact, review, ledger, audit, and human inbox
operations. Public imports should come from `loops` or `loops.hlp`; internal
package names are implementation details.

## Path 1: Build a Human Loop Platform

Read [HLP](./specs/hlp) first.

You are building this path if your system needs to represent accountable work:
assignments, human decision gates, artifact review, project ledger state, and
audit replay.

Implementation checklist:

- Implement all seven HLP objects: Task, Checkpoint, Ownership, Review,
  Artifact, Ledger, and Audit.
- Implement the 21 required HLP operations.
- Enforce the Task state machine and operation preconditions.
- Persist immutable specs, artifact versions, reviews, ledger entries, and audit
  events.
- Bridge downward to your chosen agent harness for delegation, blocking,
  resuming, and handoff.

Expected work: large. HLP is a complete protocol surface.

## Path 2: Wrap an Existing Agent Harness

Read [Agent Protocol Routes](./specs/aap), then [Integration Contracts](./specs/contracts).

You are building this path if you already have an agent harness, A2A runtime,
ACP broker, agent mesh, or multi-agent orchestrator and want HLP to provide the
human interaction control plane around it.

Implementation checklist:

- Expose `discover`, `delegate`, `block`, `resume`, and `handoff`.
- Return a run handle immediately from `delegate`.
- Attach `correlation_id` to every run and event.
- Set `Run.correlation_id = HLP TaskID`.
- Treat `block` as authoritative: an agent run must not resume itself while
  blocked by a HLP checkpoint.
- Preserve correlation during handoff.
- Project human-facing harness events such as approvals, choices, input
  requests, and artifacts into HLP objects.

Expected work: small to medium. You are not implementing a new Loops harness or
L1 protocol; you are preserving HLP correlation, pause/resume, and event
projection semantics in an existing runtime.

## Path 3: Connect a Capability Source

Read [Capability Protocol Routes](./specs/cap).

You are building this path if you provide tools, MCP servers, Skills, packaged
automation, retrieval functions, or other agent-callable capabilities.

Implementation checklist:

- Provide `capability.list`, `capability.describe`, and `capability.invoke`.
- Give every capability a globally unique `(capability_id, version)`.
- Publish an input schema for every capability.
- Return a structured `InvokeResult`.
- Hide transport details from HLP and agent-level planning.

Expected work: minimal for MCP servers and Skills runtimes; moderate for plain
function-calling registries that lack discovery.

## Path 4: Assemble a HLP-Centered Stack

Read in this order:

1. [HLP](./specs/hlp)
2. [Integration Contracts](./specs/contracts)
3. [Agent Protocol Routes](./specs/aap)
4. [Capability Protocol Routes](./specs/cap)
5. [Integration Map](./protocol-map)
6. [HLP Conformance](./conformance)

Build from the human-loop boundary outward:

- Implement HLP objects and operations.
- Embed through `HLPHost` or an equivalent host process.
- Connect your agent harness through narrow command and event adapters.
- Connect capability sources through the agent harness or host platform.
- Verify that HLP task identity survives every runtime and capability boundary.

## Path 5: Evaluate an Existing Product

Use the [Conformance](./conformance) page as an audit checklist.

Ask four questions:

1. Does the product represent human-agent work through HLP tasks, checkpoints,
   reviews, artifacts, ledger entries, and audit events?
2. Can every delegated agent run preserve the HLP TaskID as correlation?
3. Can checkpoints block and resume the corresponding agent run without letting
   the agent bypass the human decision?
4. Can harness approval/input/artifact events be projected into HLP objects?
5. Can task constraints reference capabilities without exposing transport
   details to HLP?

If any answer is no, the product may still be useful, but it should not claim
HLP compatibility.

## Recommended First Flow

For a reference implementation, start with a single task:

```text
Human creates Task
  -> HLP task.assign
  -> Harness delegate with Run.correlation_id = TaskID
  -> Agent reaches a decision point
  -> Harness projects needs_approval to HLP checkpoint.raise
  -> Harness block
  -> Human resolves the checkpoint
  -> Harness resume
  -> Harness projects Artifact
  -> Human submits Review
  -> Task reaches completed
  -> Audit replay reconstructs the flow
```

If this flow works without losing correlation or mutating immutable records, the
implementation has the core Loops shape.
