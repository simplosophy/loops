---
title: AAP — Agent-Agent Protocol Profile
outline: [2, 3]
---

# AAP — Agent-Agent Protocol Profile

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | Draft |
| Layer | L1, middle layer of the Loops Protocol Stack |
| Document type | Conformance profile |
| Primary concern | Agent discovery, delegation, blocking, and handoff |

AAP defines the minimum L1 surface required for agent-to-agent coordination in
the Loops Protocol Stack.

AAP is not a new agent transport protocol. A2A, ACP, AGNTCY, and custom agent
meshes may satisfy this profile if they expose the required semantics and
preserve the Loops inter-layer contracts.

Normative keywords follow RFC 2119.

## Scope

AAP governs:

- Agent discovery by capability.
- Asynchronous delegation to another agent.
- Run handles and run state.
- Blocking and resuming a run for HACP checkpoints.
- Handoff from one agent to another.
- Correlated event streams.

AAP does not govern:

- How an agent internally plans or executes.
- How humans review work; that is HACP.
- How tools and skills are invoked; that is CAP.
- Host platform lifecycle, identity, billing, or placement.

## Core Primitives

| Primitive | Meaning | Required for |
| --- | --- | --- |
| `discover` | Find agents by capability or tags | Routing work |
| `delegate` | Start an asynchronous run on another agent | HACP task assignment and subdelegation |
| `block` | Pause a run pending external decision | HACP checkpoint gating |
| `resume` | Continue a blocked run with resolution data | HACP checkpoint resolution |
| `handoff` | Transfer execution context to another agent | HACP ownership transfer |

## Agent

```yaml
Agent:
  agent_id: string
  capabilities: [CapabilityRef]
  manifest: AgentManifest
```

An agent is an execution unit that can accept delegated work. It declares
capabilities through CAP `CapabilityRef` values.

## AgentCard

```yaml
AgentCard:
  agent_id: string
  name: string
  description: string
  capabilities: [CapabilityRef]
  endpoint: string
  protocol: "a2a" | "acp" | "agntcy" | string
```

Rules:

- `AgentCard` **MUST** be discoverable through `agent.discover`.
- `endpoint` is transport-specific and **MUST NOT** be exposed upward to HACP.
- `capabilities` **MUST** use CAP `CapabilityRef` values.

## Run

```yaml
Run:
  run_id: string
  agent_id: string
  correlation_id: string
  state: "running" | "blocked" | "completed" | "failed"
  created_at: timestamp
```

`correlation_id` is the key L1-to-L2 contract. For HACP-originated work,
`Run.correlation_id` **MUST** equal `Task.id`.

## Discovery

```yaml
agent.discover(query: DiscoveryQuery) -> [AgentCard]

DiscoveryQuery:
  capability: CapabilityRef | null
  tags: [string] | null
```

Rules:

- A conforming L1 **MUST** support `agent.discover`.
- Results **MUST** include enough endpoint data for the L1 runtime to reach the
  target agent.
- HACP callers **MUST NOT** depend on endpoint details.

## Delegation

```yaml
agent.delegate(req: DelegateRequest) -> Run

DelegateRequest:
  to_agent: agent_id
  task_id: string
  capability: CapabilityRef
  input: object
  parent_run: run_id | null
```

Rules:

- `delegate` **MUST** return a `Run` handle without waiting for completion.
- `DelegateRequest.task_id` **MUST** become `Run.correlation_id`.
- If delegation fails after the run is created, the implementation **MUST** emit
  `run.failed`.
- If the target agent does not support the requested capability, the
  implementation **MUST** return `CAPABILITY_NOT_SUPPORTED`.

## Block and Resume

```yaml
agent.block(run_id, reason: string, checkpoint_id: string) -> void
agent.resume(run_id, resolution: object) -> void
```

Rules:

- `block` **MUST** include `checkpoint_id`.
- A blocked run **MUST NOT** resume itself.
- `resume` **MUST** carry the HACP checkpoint resolution payload.
- Invalid state transitions **MUST** return `INVALID_TRANSITION`.

## Handoff

```yaml
agent.handoff(run_id, to_agent: agent_id, context: object) -> Run
```

Rules:

- Handoff creates a new run for the receiving agent.
- The new run **MUST** preserve the original `correlation_id`.
- The old run **SHOULD** remain available as read-only history.
- Handoff is the AAP expression of HACP ownership transfer.

## Event Stream

Conforming L1 implementations **MUST** emit run events.

```yaml
AgentEvent:
  run_id: string
  correlation_id: string
  type: AgentEventType
  payload: object
  at: timestamp

AgentEventType:
  "run.started" | "run.progress" | "run.blocked" |
  "run.completed" | "run.failed"
```

Rules:

- Every event **MUST** include `correlation_id`.
- `run.blocked` **MUST** identify the HACP checkpoint when the block came from
  a checkpoint.
- AAP events **SHOULD** be replayable for debugging and audit correlation.

## Errors

| Code | Meaning |
| --- | --- |
| `AGENT_NOT_FOUND` | Target agent does not exist or is unavailable |
| `CAPABILITY_NOT_SUPPORTED` | Target agent does not declare the requested capability |
| `DELEGATION_REFUSED` | Target agent refused delegated work |
| `RUN_NOT_FOUND` | Run id is invalid |
| `INVALID_TRANSITION` | Run state transition is invalid |

## Reference Mappings

| AAP profile requirement | A2A-style mapping |
| --- | --- |
| `agent.discover` | Agent card discovery |
| `agent.delegate` | Asynchronous task send |
| `Run` | Task or run handle |
| `AgentEvent` | Task status updates |
| `correlation_id` | Task metadata or extension field |

ACP and AGNTCY-style runtimes may also conform if they expose the same semantics
and preserve correlation.

## Inter-layer Contracts

### AAP to HACP

| HACP operation | AAP action | Requirement |
| --- | --- | --- |
| `task.assign` | `agent.delegate` | TaskID **MUST** become `Run.correlation_id` |
| `checkpoint.raise` | `agent.block` | `checkpoint_id` **MUST** be provided |
| `checkpoint.resolve` | `agent.resume` | Resolution **MUST** be passed through |
| `ownership.delegate` | `agent.delegate` | Parent run **SHOULD** remain traceable |
| `ownership.transfer` | `agent.handoff` | Correlation **MUST** be preserved |

### AAP to CAP

AAP calls capabilities through CAP `CapabilityRef`. It **MUST NOT** depend on
the capability transport.

```yaml
CapabilityRef:
  capability_id: "cap:code-review"
  version: "2.1.0"
```

## Conformance

An implementation claiming AAP 0.1.0-draft compatibility **MUST**:

1. Support `agent.discover`, `agent.delegate`, `agent.block`, `agent.resume`,
   and `agent.handoff`.
2. Maintain the run states `running`, `blocked`, `completed`, and `failed`.
3. Include `correlation_id` on every run and run event.
4. Preserve HACP TaskID as `Run.correlation_id`.
5. Emit the required event stream.
6. Use the defined error semantics.

An implementation **MAY** choose the underlying transport, mesh topology,
authentication scheme, retry policy, and hosting model.

## Open Issues

| Issue | Draft stance |
| --- | --- |
| Agent mesh topology | Brokered and decentralized designs may both conform. |
| Delegate timeout and retry | Host-defined; no default retry in the profile. |
| Concurrent delegation limits | Host-defined. |
| Agent trust and authentication | Host platform responsibility. |
| Old run visibility after handoff | Read-only historical visibility is recommended. |
| Multi-agent coordination beyond pairs | Not standardized in this draft. |

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| 0.1.0-draft | 2026-06-19 | Initial L1 conformance profile for agent-to-agent coordination. |
