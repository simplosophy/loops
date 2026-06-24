# Overview

<section class="overview-hero">
  <p class="eyebrow">Human Loop Protocol</p>
  <h2>HLP defines accountability around autonomous harness work.</h2>
  <p>
    A human principal delegates a bounded task to an existing agent harness,
    the harness raises decision checkpoints, humans review artifacts, and the
    full lifecycle remains replayable.
  </p>
</section>

<section class="overview-summary" aria-label="HLP overview summary">
  <div>
    <strong>Protocol owner</strong>
    <span>HLP owns tasks, checkpoints, ownership, reviews, artifacts, ledgers, and audit events.</span>
  </div>
  <div>
    <strong>Integration model</strong>
    <span>Existing harnesses and L1/L0 ecosystems keep agent execution, delegation, and capability invocation.</span>
  </div>
  <div>
    <strong>Core invariant</strong>
    <span>Task identity, human decisions, and artifact provenance survive every harness boundary.</span>
  </div>
</section>

HLP sits above existing agent harness and capability ecosystems. Those lower
layers are integration routes, not new protocols owned by Loops:

| Layer | Role in this project | Concern | Typical implementation |
| --- | --- | --- | --- |
| L2 | HLP specification and SDK | Human-loop work | Task and review platforms |
| L1 | Agent protocol route | Agent delegation and run lifecycle | Existing harnesses, A2A runtimes, ACP brokers, agent meshes |
| L0 | Capability protocol route | Tool, skill, and capability invocation | MCP servers, Agent Skills runtimes, local tools |

The central claim is simple: a platform should be able to wrap a new agent
harness without rewriting human review semantics, change a capability provider
without changing task governance, and add a new UI channel without changing
execution rules.

## Problem

Most agent products are vertical stacks. Provider calls, tools, channels, human
approvals, artifact delivery, and audit logic live in one harness-specific code
path. That works while the product is small. It becomes brittle when each
concern evolves at a different speed.

Models change weekly. Communication channels change quarterly. Governance,
identity, audit, and review processes change slowly and must remain reliable. A
single harness abstraction cannot carry all three rhythms without coupling them.

## Model

HLP treats the human loop as the stable top-level protocol and routes downward
through adapter contracts:

<img src="./assets/stack.svg" alt="HLP integration stack: HLP above agent and capability protocol routes, joined by explicit contracts." style="display:block;width:100%;max-width:880px;height:auto;margin:8px auto 16px;border:1px solid var(--vp-c-divider);border-radius:8px;">

The ASCII view below traces the operations that flow down through the stack:

```text
Human principal
  │
  │ HLP: task.assign, checkpoint.raise, review.submit, audit.replay
  ▼
Existing agent harness
  │
  │ L1 route: delegate, block, resume, handoff, harness events
  ▼
Capability source
  │
  │ L0 capability route: list, describe, invoke
  ▼
Tool or Skill implementation
```

The boundaries are deliberately narrow:

- **HLP** defines the lifecycle of human-owned work: tasks, checkpoints,
  ownership, reviews, artifacts, ledgers, and audit events.
- **L1 agent routes** point to existing harnesses and agent protocols. HLP only
  needs delegation, blocking, resuming, handoff, and human-facing harness events.
- **L0 capability routes** point to existing capability protocols. HLP only
  needs stable capability references when a task constrains required tools or
  skills.

## Design Principles

### One layer, one responsibility

HLP owns accountable work. Existing agent harnesses own execution and
delegation. Existing capability systems own tool and skill invocation. HLP
observes those systems through explicit adapter contracts; it does not absorb
their protocols.

### Dependencies flow downward

The allowed dependency direction is:

```text
HLP (L2) -> agent protocol route (L1) -> capability protocol route (L0)
```

Capability implementations never need to know HLP exists. Agent harnesses only
see HLP through correlation, block/resume, and event projection contracts. HLP
never calls a tool directly.

### Cross-layer communication uses contract objects

Layers do not read or mutate each other's internal state. They coordinate
through explicit objects:

| Contract | Purpose |
| --- | --- |
| `CapabilityRef` | Lets upper layers reference a capability by `(capability_id, version)` without seeing transport details. |
| `TaskID = Run.correlation_id` | Carries HLP task identity through every agent run and event. |
| `Checkpoint -> block/resume` | Maps a human decision point to an agent run pause and restart. |
| `HarnessEvent -> HLP object` | Projects approval, input, choice, and artifact events into HLP semantics. |
| `Ownership -> handoff` | Maps task ownership transfer to agent handoff while preserving correlation. |

### Forward-only state

HLP is designed for replayability and audit. Task specs, artifact versions,
reviews, ledger entries, and audit events are immutable. Corrections are modeled
as new entries or new versions, not as destructive edits.

## What Loops Defines

This project defines:

- A complete HLP 0.1.0-draft protocol for accountable human-loop work.
- A Python SDK with protocol objects, `HLPClient`, `HLPHost`, stores, event bus,
  and adapters.
- Integration contracts for routing HLP task identity, checkpoints, ownership,
  harness events, and capability references into existing agent and capability
  protocols.
- Introductory L1/L0 route pages that explain where A2A, ACP, AGNTCY-style
  meshes, MCP, Agent Skills, and local capability systems fit.
- HLP conformance requirements that let implementations make precise claims.

This project does not define:

- A built-in agent harness or execution loop.
- A replacement for A2A, ACP, AGNTCY, MCP, Agent Skills, or harness internals.
- A mandatory transport such as HTTP, gRPC, WebSocket, or stdio.
- A required persistence backend.
- A universal identity, RBAC, or billing model.
- A UI specification for chat, web, IM, or CLI experiences.

## Why HLP Is New

MCP and Skills cover agent-to-capability calls. A2A and related protocols cover
agent-to-agent delegation. The missing protocol surface is the one that connects
autonomous agents back to the people responsible for the work.

HLP fills that gap with seven first-class objects:

| Object | Role |
| --- | --- |
| Task | A bounded unit of work owned by a human principal. |
| Checkpoint | A decision point raised by an agent and resolved by a human. |
| Ownership | The transferable assignee record for the task. |
| Review | Human feedback on an artifact. |
| Artifact | An immutable deliverable with provenance and versions. |
| Ledger | Append-only project or organization state. |
| Audit | Immutable protocol operation log. |

Together, these objects make human-loop work inspectable, replayable, and
implementable across harnesses.

## Specification Status

All protocol documents are currently **0.1.0-draft**. Draft status means the
semantic model is concrete enough to implement, but transport bindings and some
open policy choices remain intentionally outside the core specification.

Start with the [Implementation Guide](./reading-routes), then use
[Conformance](./conformance) to decide what your implementation can claim.
