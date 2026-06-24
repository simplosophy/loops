---
title: HLP — Human Loop Protocol
outline: [2, 3]
---

# HLP — Human Loop Protocol

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | Draft, validated by the current reference implementation |
| Layer | HLP SDK layer above existing agent harness and capability routes |
| Document type | Full protocol specification |
| Primary concern | Human-owned work delegated to autonomous agent harnesses |

HLP defines how people and autonomous agent harnesses collaborate around a
bounded unit of work called a **Task**. It covers assignment, checkpoints,
ownership, artifact delivery, review, project state, and audit.

HLP is transport-agnostic and harness-agnostic. It specifies protocol semantics,
not whether those semantics are carried over HTTP, WebSocket, gRPC, stdio, an
event bus, or a host platform API.

Normative keywords follow RFC 2119: **MUST**, **MUST NOT**, **SHOULD**,
**SHOULD NOT**, and **MAY**.

## Scope

HLP governs:

- Human principals assigning work to agent harnesses.
- Agent harnesses raising decision checkpoints.
- Human reviewers accepting, rejecting, or requesting changes on artifacts.
- Ownership transfer across humans and agents.
- Immutable artifact versions and append-only project ledger state.
- Audit events for protocol replay and accountability.

HLP does not govern:

- How an agent harness internally executes a run.
- How agents delegate to other agents; use an existing L1 agent route.
- How agents invoke tools or skills; use an existing L0 capability route.
- How notifications are rendered in chat, web, mobile, or CLI channels.
- The host platform's identity, RBAC, billing, or tenant model.

## Roles

| Role | Definition |
| --- | --- |
| `principal` | The human ultimately responsible for the task. The principal **MUST** be human and **MUST NOT** change during task lifetime. |
| `assignee` | The current executor. The assignee **MAY** be a human or an agent and may change through protocol operations. |
| `reviewer` | A human who reviews an artifact. The reviewer **MUST** be human and **MAY** differ from the principal. |

## First-Class Objects

HLP defines seven first-class objects. A conforming implementation **MUST**
support all seven.

| Object | Purpose | Lifecycle |
| --- | --- | --- |
| Task | The primary unit of accountable work | Created to completed |
| Checkpoint | A decision point raised by an agent | Raised to resolved or expired |
| Ownership | Transferable responsibility for a task | Exists with the task |
| Review | Human verdict and feedback on an artifact | Immutable after submit |
| Artifact | A versioned deliverable with provenance | Independent, immutable versions |
| Ledger | Append-only project or organization state | Scope-scoped, append-only |
| Audit | Immutable operation log | Append-only forever |

## Immutability

HLP is forward-only:

- Task `spec` **MUST NOT** change after `task.create`.
- Artifact versions **MUST NOT** change after `artifact.commit`.
- Review records **MUST NOT** change after `review.submit`.
- Ledger entries **MUST NOT** be deleted.
- Audit events **MUST NEVER** be deleted or modified.

Corrections are represented as new tasks, new artifact versions, new reviews, or
new ledger entries.

## Identifiers

Object identifiers **MUST** use ULID-compatible entropy and sortable ordering
with type prefixes.

| Object | Prefix | Example |
| --- | --- | --- |
| Task | `task_` | `task_01J0K7M4N8Y7...` |
| Checkpoint | `ckpt_` | `ckpt_01J0K9C3G2T1...` |
| Review | `rev_` | `rev_01J0KAMJ6D8P...` |
| Artifact | `art_` | `art_01J0KBYF2Q3V...` |
| Ledger | `led_` | `led_01J0KC8A7M5R...` |
| AuditEvent | `aud_` | `aud_01J0KDK3N6A2...` |

Timestamps **MUST** use RFC 3339 UTC.

## Task

Task is the subject of the protocol.

```yaml
Task:
  id: task_
  type: string
  spec: TaskSpec
  ownership: Ownership
  state: TaskState
  parent_task: task_ | null
  created_at: timestamp
  deadline: timestamp | null
  checkpoints: [ckpt_]
  artifacts: [art_]
  audit_trail: aud_

TaskSpec:
  goal: string
  acceptance_criteria: [string]
  inputs: [InputRef]
  constraints: Constraints

InputRef:
  kind: "artifact" | "resource"
  id: string
  version: string
  uri: string

Constraints:
  max_duration: duration
  must_use_capabilities: [CapabilityRef]
```

Rules:

- `spec` **MUST** be immutable after creation.
- `ownership.principal` **MUST** be set at creation and **MUST NEVER** change.
- `state` transitions **MUST** follow the Task state machine.

## Task State Machine

Only the listed transitions are valid.

```text
created
  -> assigned
  -> in_progress
       -> blocked -> in_progress
       -> review_ready -> under_review -> in_progress
                                      -> accepted -> completed
                                      -> rejected

created | assigned | in_progress | blocked -> completed by task.cancel
```

| From | To | Trigger |
| --- | --- | --- |
| `created` | `assigned` | `task.assign` |
| `assigned` | `in_progress` | Agent starts work |
| `in_progress` | `blocked` | `checkpoint.raise` |
| `blocked` | `in_progress` | `checkpoint.resolve` with approve or provide |
| `blocked` | `completed` | `checkpoint.resolve` with reject |
| `in_progress` | `review_ready` | `artifact.commit` |
| `review_ready` | `under_review` | `review.submit` begins review |
| `under_review` | `in_progress` | `review.submit` with changes requested |
| `under_review` | `accepted` | `review.submit` with approved |
| `under_review` | `rejected` | `review.submit` with rejected |
| `accepted` | `completed` | Automatic completion |
| `created`, `assigned`, `in_progress`, `blocked` | `completed` | `task.cancel` |

State ownership:

| State | Assignee | Meaning |
| --- | --- | --- |
| `created` | principal | Created but not assigned |
| `assigned` | agent | Delegated but not started |
| `in_progress` | agent | Agent is executing |
| `blocked` | principal | Human decision required |
| `review_ready` | principal | Artifact delivered for review |
| `under_review` | principal | Review in progress |
| `accepted` | principal | Accepted, ready to complete |
| `completed` | principal | Terminal successful or canceled state |

## Checkpoint

Checkpoint is the upward control surface from agent to human.

```yaml
Checkpoint:
  id: ckpt_
  task_id: task_
  kind: "approval" | "choice" | "input" | "escalation"
  prompt: string
  options: [CheckpointOption]
  context: [Evidence]
  state: "pending" | "resolved" | "expired"
  raised_at: timestamp
  expires_at: timestamp | null
  resolution: CheckpointResolution | null

CheckpointOption:
  id: string
  label: string
  risk: "low" | "medium" | "high"

CheckpointResolution:
  by: user_
  action: "approve" | "reject" | "choose" | "provide" | "reassign"
  choice: string
  input: string
  reassign_to: agent_
  comment: string
  at: timestamp
```

Rules:

- `resolution.by` **MUST** be a principal or authorized reviewer.
- `checkpoint.raise` **MUST** move the task to `blocked`.
- `checkpoint.resolve` **MUST** resolve the checkpoint before resuming work.
- Expiration policy is implementation-defined in this draft, but expiration
  **MUST** emit an audit event.

## Ownership

Ownership records responsibility and assignment.

```yaml
Ownership:
  task_id: task_
  principal: user_
  assignee: user_ | agent_
  delegable: boolean
  chain: [OwnershipTransfer]

OwnershipTransfer:
  from: user_ | agent_
  to: user_ | agent_
  at: timestamp
  via: "assign" | "checkpoint" | "approve" | "reject" | "handoff"
```

Rules:

- Every assignee change **MUST** append to `chain`.
- Every transfer **MUST** correspond to a valid protocol event.
- If `delegable=false`, an agent **MUST NOT** call `ownership.delegate`.

## Review

Review captures human feedback on an artifact.

```yaml
Review:
  id: rev_
  task_id: task_
  artifact_id: art_
  reviewer: user_
  verdict: "approved" | "changes_requested" | "rejected"
  comments: [ReviewComment]
  requested_changes: [string]
  at: timestamp

ReviewComment:
  anchor: string
  severity: "blocker" | "major" | "minor" | "nit"
  body: string
```

Rules:

- Reviews **MUST** be immutable after submission.
- `reviewer` **MUST** be human.
- `requested_changes` **MUST** be present when verdict is
  `changes_requested`.

## Artifact

Artifact is a deliverable produced by a task.

```yaml
Artifact:
  id: art_
  type: string
  provenance: ArtifactProvenance
  version: string
  parent_version: string | null
  payload: ArtifactPayload
  references: [ArtifactRef]

ArtifactProvenance:
  produced_by: task_
  produced_at: timestamp

ArtifactPayload:
  kind: "diff" | "blob" | "ref" | "inline"
  uri: string
  checksum: string
  size: integer

ArtifactRef:
  task_id: task_
  as: "input" | "output"
```

Rules:

- `(id, version)` **MUST** be globally unique.
- Artifact references **MUST** lock both id and version.
- `checksum` **MUST** verify payload integrity.
- Updating an artifact **MUST** create a new version with `parent_version`.

## Ledger

Ledger is append-only project or organization state.

```yaml
Ledger:
  id: led_
  scope: string

LedgerEntry:
  key: string
  value: any
  written_at: timestamp
  by: task_
```

Rules:

- Ledger entries **MUST NEVER** be deleted.
- Rewriting a logical key **MUST** append a new entry.
- Every write **MUST** emit an audit event.
- Conflict handling is implementation-defined in this draft; implementations
  **SHOULD** document their policy.

## Audit

Audit is the immutable observation plane.

```yaml
AuditEvent:
  id: aud_
  seq: integer
  at: timestamp
  actor: user_ | agent_
  action: string
  subject:
    kind: string
    id: string
  task_id: task_ | null
  before: object | null
  after: object | null
```

Rules:

- Every state-changing protocol operation **MUST** produce an audit event.
- Audit events **MUST NEVER** be deleted or modified.
- `seq` **MUST** be monotonically increasing within its audit scope.

## Operations

HLP operation names follow `<object>.<verb>`. A conforming implementation
**MUST** support all 21 operations.

| Object | Operation | Caller | Semantics |
| --- | --- | --- | --- |
| Task | `task.create` | principal | Create task in `created` state |
| Task | `task.assign` | principal | Assign to agent and transfer ownership |
| Task | `task.start` | agent or adapter | Mark the correlated harness run as started |
| Task | `task.cancel` | principal | End an active task |
| Task | `task.get` | any authorized actor | Fetch one task |
| Task | `task.list` | any authorized actor | Query tasks |
| Checkpoint | `checkpoint.raise` | agent | Declare a human decision point |
| Checkpoint | `checkpoint.resolve` | human | Resolve a pending checkpoint |
| Checkpoint | `checkpoint.expire` | system | Mark checkpoint expired |
| Ownership | `ownership.transfer` | system | Transfer assignee |
| Ownership | `ownership.delegate` | agent | Delegate downward when allowed |
| Review | `review.submit` | reviewer | Submit verdict and feedback |
| Review | `review.comment` | reviewer | Append review comment |
| Artifact | `artifact.commit` | agent | Commit deliverable or version |
| Artifact | `artifact.get` | any authorized actor | Fetch by id and version |
| Artifact | `artifact.reference` | task | Reference artifact as input |
| Ledger | `ledger.read` | any authorized actor | Read key state |
| Ledger | `ledger.write` | task | Append key state |
| Ledger | `ledger.history` | any authorized actor | Read key history |
| Audit | `audit.query` | any authorized actor | Query audit events |
| Audit | `audit.replay` | any authorized actor | Replay task history |

## Operation Preconditions

Violations **MUST** return `PRECONDITION_FAILED`.

| Operation | Required precondition |
| --- | --- |
| `task.assign` | Task state is `created` |
| `task.start` | Task state is `assigned` |
| `task.cancel` | Task state is `created`, `assigned`, `in_progress`, or `blocked` |
| `checkpoint.raise` | Task state is `in_progress` |
| `checkpoint.resolve` | Checkpoint is pending and caller is authorized |
| `ownership.delegate` | `ownership.delegable == true` |
| `artifact.commit` | Task state is `in_progress` or review rework state |
| `review.submit` | Task state is `review_ready` or `under_review` |

## Audit Actions

State-changing operations **MUST** map to audit actions.

| Operation | Audit action |
| --- | --- |
| `task.create` | `task.created` |
| `task.assign` | `task.assigned` |
| `task.start` | `task.started` |
| `task.cancel` | `task.cancelled` |
| `checkpoint.raise` | `task.checkpoint.raised` |
| `checkpoint.resolve` | `task.checkpoint.resolved` |
| `checkpoint.expire` | `task.checkpoint.expired` |
| `ownership.transfer` | `ownership.transferred` |
| `ownership.delegate` | `ownership.delegated` |
| `review.submit` | `review.submitted` |
| `artifact.commit` | `artifact.committed` |
| `ledger.write` | `ledger.written` |

## Integration Contracts

HLP communicates downward through explicit adapter contracts:

| HLP event | L1 route action | Contract |
| --- | --- | --- |
| `task.assign` | `delegate` | TaskID **MUST** become `Run.correlation_id` |
| `task.start` | `observe run.started` | The correlated run start **MUST** move the HLP task into progress |
| `checkpoint.raise` | `agent.block` | The corresponding run **MUST** enter `blocked` |
| `checkpoint.resolve` | `agent.resume` | Resolution **MUST** be passed to the run |
| `ownership.delegate` | `delegate` | Parent run **SHOULD** remain traceable |
| `ownership.transfer` | `handoff` | Correlation **MUST** be preserved |

Existing harnesses can also project human-facing events upward:

| Harness event | HLP projection | Contract |
| --- | --- | --- |
| `needs_approval` | `Checkpoint(kind="approval")` | TaskID, RunID, and AgentID **MUST** be preserved |
| `needs_choice` | `Checkpoint(kind="choice")` | Options **MUST** be human-readable |
| `needs_input` | `Checkpoint(kind="input")` | Prompt and context **SHOULD** support a human decision |
| `artifact` | `Artifact` | Payload **MUST** have stable uri/checksum |

HLP **MUST NOT** directly invoke capabilities. It references them only through
`CapabilityRef`; invocation belongs to the agent harness or host platform.

## Errors

| Code | Meaning |
| --- | --- |
| `INVALID_SPEC` | Task spec is invalid |
| `PRECONDITION_FAILED` | Operation precondition failed |
| `UNAUTHORIZED` | Caller is not authorized |
| `NOT_FOUND` | Object does not exist |
| `CONFLICT` | Concurrent mutation conflict |
| `IMMUTABLE_VIOLATION` | Attempt to mutate immutable object |
| `DEADLINE_EXCEEDED` | Task deadline exceeded |
| `CHECKPOINT_EXPIRED` | Checkpoint can no longer be resolved |

State transition, ownership update, and audit append **SHOULD** be atomic from
the caller's perspective.

## Conformance

An implementation claiming HLP 0.1.0-draft compatibility **MUST**:

1. Support all seven first-class objects.
2. Implement all 21 operations.
3. Enforce the Task state machine.
4. Enforce the immutability rules.
5. Emit audit events for every state-changing protocol operation.
6. Validate operation preconditions.
7. Satisfy the integration contracts when routed into existing agent harness or
   capability systems.

## Open Issues

The following topics remain intentionally draft-scoped:

| Issue | Draft stance |
| --- | --- |
| Transport binding | Not specified; implementations may choose HTTP, gRPC, WebSocket, stdio, or host APIs. |
| Checkpoint expiration default | Implementation-defined; pure suspension plus configuration is recommended. |
| Delegation depth | Allowed through `delegable`, but limits are host policy. |
| Ledger conflict handling | Last-write-wins plus audit is acceptable in this draft. |
| Multi-reviewer verdicts | Not standardized; single reviewer is the baseline. |
| Cross-project artifact references | Require explicit authorization; mechanism is host-defined. |
| Version compatibility | Expected to follow semantic versioning after implementation feedback. |

## Reference Flow

```text
Human Alice                 HLP                         Agent Devin
  | task.create              |                             |
  | task.assign              | -> harness delegate(TaskID) |
  |                           | <- needs_approval           |
  | <- checkpoint notice      | -> harness block            |
  | checkpoint.resolve        | -> harness resume           |
  |                           | <- artifact(v1)             |
  | review.submit(changes)    | -> in_progress              |
  |                           | <- artifact.commit(v2)      |
  | review.submit(approved)   | -> accepted -> completed    |
  |                           | -> ledger.write             |
  | audit.replay              | reconstructs the flow       |
```

This flow exercises task assignment, checkpoint gating, artifact delivery,
human review, rework, completion, ledger persistence, and audit replay.
