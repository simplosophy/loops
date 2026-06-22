# Overview

Loops is a three-layer protocol stack for AI coordination. It separates three
different concerns that are often bundled into one agent application:

| Layer | Protocol | Concern | Typical implementation |
| --- | --- | --- | --- |
| L2 | HLP | Human-loop work | Task and review platforms |
| L1 | AAP | Agent-agent delegation | A2A runtimes, ACP brokers, agent meshes |
| L0 | CAP | Capability invocation | MCP servers, Skills runtimes |

The central claim is simple: a platform should be able to change a capability
provider without changing human review semantics, add a new agent runtime without
rewriting task governance, and add a new UI channel without changing execution
rules.

## Problem

Most agent products are vertical stacks. Provider calls, tools, channels,
human approvals, artifact delivery, and audit logic live in one code path. That
works while the product is small. It becomes brittle when each concern evolves at
a different speed.

Models change weekly. Communication channels change quarterly. Governance,
identity, audit, and review processes change slowly and must remain reliable. A
single runtime abstraction cannot carry all three rhythms without coupling them.

## Model

Loops treats coordination as a protocol stack:

<img src="./assets/stack.svg" alt="Loops Protocol Stack: HLP above AAP above CAP, joined by explicit inter-layer contracts." style="display:block;width:100%;max-width:880px;height:auto;margin:8px auto 16px;border:1px solid var(--vp-c-divider);border-radius:8px;">

The ASCII view below traces the operations that flow down through the stack:

```text
Human principal
  │
  │ HLP: task.assign, checkpoint.raise, review.submit, audit.replay
  ▼
Agent worker
  │
  │ AAP: discover, delegate, block, resume, handoff
  ▼
Capability source
  │
  │ CAP: list, describe, invoke
  ▼
Tool or Skill implementation
```

The layers are deliberately narrow:

- **HLP** defines the lifecycle of human-owned work: tasks, checkpoints,
  ownership, reviews, artifacts, ledgers, and audit events.
- **AAP** defines the minimum agent-to-agent surface needed by HLP: discovery,
  delegation, blocking, resuming, handoff, and correlated run events.
- **CAP** defines the minimum capability surface needed by agents: manifests,
  versioned capability references, invocation results, and capability errors.

## Design Principles

### One layer, one responsibility

Each layer owns one coordination axis. HLP owns accountable work. AAP owns agent
delegation. CAP owns capability invocation. A layer may expose events and
contracts upward, but it does not import the semantics of the layer above it.

### Dependencies flow downward

The allowed dependency direction is:

```text
HLP (L2) -> AAP (L1) -> CAP (L0)
```

CAP never knows that AAP or HLP exists. AAP never knows human review semantics
except through explicit correlation and block/resume contracts. HLP never calls
a tool directly.

### Cross-layer communication uses contract objects

Layers do not read or mutate each other's internal state. They coordinate through
explicit objects:

| Contract | Purpose |
| --- | --- |
| `CapabilityRef` | Lets upper layers reference a capability by `(capability_id, version)` without seeing transport details. |
| `TaskID = Run.correlation_id` | Carries HLP task identity through every AAP run and event. |
| `Checkpoint -> block/resume` | Maps a human decision point to an agent run pause and restart. |
| `Ownership -> handoff` | Maps task ownership transfer to AAP handoff while preserving correlation. |

### Forward-only state

HLP is designed for replayability and audit. Task specs, artifact versions,
reviews, ledger entries, and audit events are immutable. Corrections are modeled
as new entries or new versions, not as destructive edits.

## What Loops Defines

Loops defines:

- A complete HLP 0.1.0-draft protocol for accountable human-loop work.
- AAP and CAP conformance profiles for existing agent and capability protocols.
- The inter-layer contracts required for full-stack interoperability.
- Conformance requirements that let implementations make precise claims.

Loops does not define:

- A mandatory transport such as HTTP, gRPC, WebSocket, or stdio.
- A required persistence backend.
- A universal identity, RBAC, or billing model.
- A UI specification for chat, web, IM, or CLI experiences.
- A replacement for MCP, Skills, A2A, ACP, or agent runtime internals.

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

Together, these objects make human-loop work inspectable, replayable,
and implementable across runtimes.

## Specification Status

All protocol documents are currently **0.1.0-draft**. Draft status means the
semantic model is concrete enough to implement, but transport bindings and some
open policy choices remain intentionally outside the core specification.

Start with the [Implementation Guide](./reading-routes), then use
[Conformance](./conformance) to decide what your implementation can claim.
