---
title: HLP — Human Loop Protocol
outline: [2, 3]
---

# HLP — Human Loop Protocol

| Field | Value |
| --- | --- |
| Version | 0.2.0-draft |
| Status | Draft; 0.2.0 core semantics are covered by the reference implementation and offline conformance suite |
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

The following structures are **value objects** of Task (not first-class objects)
that carry continuous-control semantics:

| Value object | Host | Purpose |
| --- | --- | --- |
| `SteeringAmendment` | `Task.steering_log` | Append-only direction correction, never alters `spec` |
| `PermissionGrant` | `Task.spec.constraints.grants` | Append-only pre-authorized capability boundary |
| `ProposedAction` | `Checkpoint.proposed_actions` | A single proposed action in a batch approval |

## Immutability

HLP is forward-only:

- Task `spec` **MUST NOT** change after `task.create`. To change direction you
  **MUST** use `task.amend` to append to `steering_log` (never alter `spec`);
  `task.cancel` + new task is reserved for a full restart.
- `steering_log` **MUST** be append-only; amendments **MUST NEVER** be deleted
  or modified.
- `PermissionGrant` entries **MUST** be append-only; revocation appends a
  matching active `decision="deny"` entry. Authorization evaluation gives deny
  precedence over allow.
- Artifact versions **MUST NOT** change after `artifact.commit`.
- Review records **MUST NOT** change after `review.submit`.
- Ledger entries **MUST NOT** be deleted.
- Audit events **MUST NEVER** be deleted or modified.

Corrections are represented as appended amendments, new artifact versions, new
reviews, or new ledger entries. Continuous control (interrupt, steering,
pre-authorization, take-over) is admitted through append-only structures and
does not weaken forward-only semantics.

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
  revision: integer
  deadline: timestamp | null
  checkpoints: [ckpt_]
  artifacts: [art_]
  steering_log: [SteeringAmendment]
  audit_trail: aud_

TaskSpec:
  goal: string
  acceptance_criteria: [string]
  inputs: [InputRef]
  constraints: Constraints

SteeringAmendment:
  text: string
  intent: "redirect" | "clarify" | "constrain" | "abort_hint"
  by: user_
  at: timestamp

InputRef:
  kind: "artifact" | "resource"
  id: string
  version: string
  uri: string

Constraints:
  max_duration: duration
  external_refs: [ExternalRef]
  autonomy: AutonomyTier
  grants: [PermissionGrant]

AutonomyTier: "autonomous" | "plan_then_implement" | "confirm_each_action" | "read_only"

PermissionGrant:
  scope: string
  decision: "allow" | "deny"
  until: "session" | "task" | timestamp
  granted_by: user_
  granted_at: timestamp

Permission scope grammar:
  scope: "*" | namespace ":" target ["*"]
  namespace: [a-z][a-z0-9_-]*
  target: non-empty string without whitespace

`scope` **MUST** be trimmed and normalized before storage. `*` is valid only as
a global scope or suffix wildcard; `fs:/repo:*` **MAY** match
`fs:/repo/file.py`. Expired grants **MUST** be ignored. Active matching denies
**MUST** take precedence over active matching allows. No active allow means the
scope is not pre-authorized.

ExternalRef:
  kind: string
  namespace: string
  id: string
  version: string | null
  label: string | null
```

Rules:

- `spec` **MUST** be immutable after creation. Direction changes **MUST** go
  through `task.amend` appending to `steering_log`; `spec.goal` **MUST NOT** be
  rewritten.
- `steering_log` **MUST** be append-only. `task.amend` is callable in
  `in_progress` or `blocked` and **MUST NOT** be called in a terminal state.
- `autonomy` sets a baseline autonomy tier; `grants` refine it (allow-always /
  deny). A harness **MUST** consult active matching `grants` before executing a
  proposed action: an allowed scope **MAY** skip a checkpoint; a denied scope
  **MUST NOT** execute.
- `external_refs` **MAY** record opaque external evidence for human decisions
  and audit, but HLP **MUST NOT** interpret or invoke referenced systems.
- `ownership.principal` **MUST** be set at creation and **MUST NEVER** change.
- `state` transitions **MUST** follow the Task state machine.

## Task State Machine

Only the listed transitions are valid.

```text
created
  -> assigned
  -> in_progress
       -> blocked -> in_progress          (checkpoint.resolve)
       -> blocked                         (task.interrupt, human-initiated)
       -> review_ready -> under_review -> in_progress
                                      -> accepted -> completed
                                      -> rejected

created | assigned | in_progress | blocked -> completed by task.cancel
```

| From | To | Trigger |
| --- | --- | --- |
| `created` | `assigned` | `task.assign` |
| `assigned` | `in_progress` | Agent starts work |
| `in_progress` | `blocked` | `checkpoint.raise` (agent-initiated) or `task.interrupt` (human-initiated; system raises a `kind=interrupt` checkpoint) |
| `blocked` | `in_progress` | `checkpoint.resolve` with approve, provide, or amend |
| `blocked` | `completed` | `checkpoint.resolve` with reject |
| `in_progress` | `review_ready` | `artifact.commit` |
| `review_ready` | `under_review` | `review.submit` begins review |
| `under_review` | `in_progress` | `review.submit` with changes requested, or `review.submit` with `kind=plan` approved |
| `under_review` | `accepted` | `review.submit` with `kind=deliverable` approved |
| `under_review` | `rejected` | `review.submit` with `kind=deliverable` rejected |
| `accepted` | `completed` | Automatic completion |
| `created`, `assigned`, `in_progress`, `blocked` | `completed` | `task.cancel` |

Non-state-changing operations (do not transition `state` but **MUST** emit an
audit event):

| Operation | Allowed states | Semantics |
| --- | --- | --- |
| `task.amend` | `in_progress`, `blocked` | Append to `steering_log`; never alter state |
| `ownership.transfer` | non-terminal | Take-over: assignee may temporarily transfer to a human, then back to an agent |

State ownership:

| State | Assignee | Meaning |
| --- | --- | --- |
| `created` | principal | Created but not assigned |
| `assigned` | agent | Delegated but not started |
| `in_progress` | agent (MAY be human during take-over) | Agent is executing |
| `blocked` | principal | Human decision required (includes human-initiated interrupt) |
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
  kind: "approval" | "choice" | "input" | "escalation" | "interrupt"
  prompt: string
  options: [CheckpointOption]
  proposed_actions: [ProposedAction]
  context: [Evidence]
  state: "pending" | "resolved" | "expired"
  raised_at: timestamp
  raised_by: "agent" | "human" | "system"
  expires_at: timestamp | null
  resolution: CheckpointResolution | null

CheckpointOption:
  id: string
  label: string
  risk: "low" | "medium" | "high"

ProposedAction:
  id: string
  kind: string
  summary: string
  permission_scope: string | null
  detail: object | null
  risk: "low" | "medium" | "high"

CheckpointResolution:
  by: user_
  action: "approve" | "reject" | "choose" | "provide" | "reassign"
  choice: string
  input: string
  reassign_to: agent_
  approved_actions: [string]
  denied_actions: [string]
  state_patch: object | null
  edited_artifact_ref: { id: art_, version: string } | null
  comment: string
  at: timestamp
```

Rules:

- `resolution.by` **MUST** be a principal or authorized reviewer.
- `checkpoint.raise` **MUST** move the task to `blocked`.
- `checkpoint.resolve` **MUST** resolve the checkpoint before resuming work.
- A `kind=interrupt` checkpoint **MUST** be triggered by `task.interrupt`
  (`raised_by="human"`) and **MUST NOT** be raised directly by an agent.
- Expiration policy is implementation-defined in this draft, but expiration
  **MUST** emit an audit event. A `kind=interrupt` checkpoint **SHOULD** remain
  purely suspended on expiration, since a human-initiated interrupt means
  "await human" and has no sensible auto-reject.
- A single pending checkpoint per task is **SHOULD**; to ask about multiple
  things at once, use a single checkpoint's `proposed_actions` rather than
  raising concurrent checkpoints.
- `approved_actions` / `denied_actions` **MUST** reference the checkpoint's own
  `proposed_actions` ids; unlisted actions default to denied (**SHOULD**).
- `state_patch` / `edited_artifact_ref` carry human-modified intermediate
  state; the harness **MUST** resume from that state rather than the original
  interruption point.

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
  kind: "plan" | "deliverable"
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
- A `kind="plan"` review targets an intermediate artifact (e.g. a plan):
  `approved` returns the task to `in_progress` to continue; `changes_requested`
  likewise returns to `in_progress` for rework.
- A `kind="deliverable"` review targets a final deliverable: `approved` moves
  to `accepted`; `rejected` moves to the `rejected` terminal state.
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
  schema_version: string
  profile: string
  prev_hash: string
  hash: string
```

Rules:

- Every state-changing protocol operation **MUST** produce an audit event.
- Audit events **MUST NEVER** be deleted or modified.
- `seq` **MUST** be monotonically increasing within its audit scope.
- `HLP-industrial` implementations **SHOULD** make AuditEvent records a
  tamper-evident hash chain: `prev_hash` points to the previous event hash, and
  `hash` is computed from canonical JSON for the event excluding the `hash`
  field.

## Operations

HLP operation names follow `<object>.<verb>`. A conforming implementation
**MUST** support all 23 operations.

| Object | Operation | Caller | Semantics |
| --- | --- | --- | --- |
| Task | `task.create` | principal | Create task in `created` state |
| Task | `task.assign` | principal | Assign to agent and transfer ownership |
| Task | `task.start` | agent or adapter | Mark the correlated harness run as started |
| Task | `task.cancel` | principal | End an active task |
| Task | `task.interrupt` | principal | Human-initiated pause (`in_progress` to `blocked`; system raises a `kind=interrupt` checkpoint) |
| Task | `task.amend` | principal | Append a direction correction to `steering_log` (does not change state or `spec`) |
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

In the industrial profile, operations that mutate a Task aggregate **SHOULD**
accept:

```yaml
expected_task_revision: integer | null
idempotency_key: string | null
```

When `expected_task_revision` is present, implementations **MUST** compare it
with the current `Task.revision` before calling external adapters or writing
state. A mismatch **MUST** return `CONFLICT`. A successful Task aggregate
mutation **MUST** advance `revision` exactly once.

When `idempotency_key` is present, the same task-scoped key plus the same
canonical request fingerprint **MUST** return the original result without
rerunning preconditions, adapter calls, audit appends, or SDK event publication.
The same key with a different fingerprint **MUST** return `CONFLICT`. The
reference implementation covers task.amend, task.interrupt,
checkpoint.resolve, and artifact.commit for CAS/idempotency replay. Adapter
outbox context covers the external side-effect boundary for task.amend,
task.interrupt, checkpoint.raise, and checkpoint.resolve.

## Operation Preconditions

Violations **MUST** return `PRECONDITION_FAILED`.

| Operation | Required precondition |
| --- | --- |
| `task.assign` | Task state is `created` |
| `task.start` | Task state is `assigned` |
| `task.cancel` | Task state is `created`, `assigned`, `in_progress`, or `blocked` |
| `task.interrupt` | Task state is `in_progress`; caller is the principal |
| `task.amend` | Task state is `in_progress` or `blocked`; caller is the principal |
| `checkpoint.raise` | Task state is `in_progress` |
| `checkpoint.resolve` | Checkpoint is pending and caller is authorized |
| `ownership.delegate` | `ownership.delegable == true` |
| `artifact.commit` | Task state is `in_progress` or review rework state |
| `review.submit` | Task state is `review_ready` or `under_review`; a `kind=deliverable` approved transitions to `accepted` only when state is `under_review` |

## Audit Actions

State-changing operations **MUST** map to audit actions.

| Operation | Audit action |
| --- | --- |
| `task.create` | `task.created` |
| `task.assign` | `task.assigned` |
| `task.start` | `task.started` |
| `task.cancel` | `task.cancelled` |
| `task.interrupt` | `task.interrupted` + `task.checkpoint.raised` (system raises on behalf of the human) |
| `task.amend` | `task.amended` |
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
| `checkpoint.resolve` | `agent.resume` | Resolution **MUST** be passed to the run; if it carries `state_patch` / `edited_artifact_ref`, the harness **MUST** resume from that state |
| `task.interrupt` | `agent.block` | Human-initiated interrupt; the harness **MUST** stop the current turn and enter `blocked` |
| `task.amend` | `agent.steer` | The direction correction **MUST** be injected into the running agent's context; the run **MUST NOT** be restarted |
| `ownership.delegate` | `delegate` | Parent run **SHOULD** remain traceable |
| `ownership.transfer` | `handoff` | Correlation **MUST** be preserved |

Existing harnesses can also project human-facing events upward:

| Harness event | HLP projection | Contract |
| --- | --- | --- |
| `needs_approval` | `Checkpoint(kind="approval")` | TaskID, RunID, and AgentID **MUST** be preserved |
| `needs_choice` | `Checkpoint(kind="choice")` | Options **MUST** be human-readable |
| `needs_input` | `Checkpoint(kind="input")` | Prompt and context **SHOULD** support a human decision |
| `artifact` | `Artifact` | Payload **MUST** have stable uri/checksum |

HLP **MUST NOT** directly invoke capabilities. Capability identity, discovery,
schema interpretation, authorization, and invocation belong to the agent
harness, host platform, or L0 ecosystem. HLP may only store opaque external
references needed for human decision evidence or audit replay.

### Reliable Harness Event Delivery

Harness adapters that project human-facing event streams **SHOULD** support
non-destructive read plus explicit acknowledgement:

```yaml
HarnessEventDelivery:
  cursor: string
  event: HarnessEvent
```

| Method | Meaning |
| --- | --- |
| `peek_events(run_id, cursor?, limit?)` | Return unacknowledged `HarnessEventDelivery` values without consuming them |
| `ack_events(run_id, through)` | Acknowledge the per-run event prefix through `through` |

An `HLP-integrated` implementation that claims event-streaming support **MUST
NOT** acknowledge an event when projection fails due to correlation mismatch,
precondition failure, adapter failure, or commit failure. After successful
projection, the implementation **SHOULD** acknowledge the event immediately. In
batch projection, it **MAY** acknowledge the successful prefix and retain the
failed event plus later events. Legacy `observe(run_id)` may remain available as
a destructive embedded/test helper, but it is not sufficient evidence for
industrial reliable delivery.

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
| `VERSION_UNSUPPORTED` | No common spec, schema, or profile version |

When an implementation exposes errors over a transport, it **MUST** use a stable
wire object:

```yaml
ProtocolError:
  code: ErrorCode
  message: string
  details: object
  retryable: boolean
  operation_id: string | null
  correlation_id: task_ | string | null
  spec_version: "0.2.0-draft"
  schema_version: "0.2"
  profile: "HLP-industrial"
```

`CONFLICT` and `DEADLINE_EXCEEDED` default to retryable. Preconditions,
authorization, immutability, not-found, invalid-spec, and expired-checkpoint
errors default to non-retryable unless an implementation explicitly overrides
the field for a transport-specific reason.

State transition, ownership update, and audit append **SHOULD** be atomic from
the caller's perspective. When protocol operations call an external agent
harness adapter, implementations **SHOULD** persist an adapter outbox intent
before the side effect, pass a stable `operation_context` /
`AdapterOperationContext` with `operation_id`, `correlation_id`,
`idempotency_key`, request fingerprint, and Task revision, and mark the outbox
record `succeeded` after the local HLP mutation commits.

When harness events use reliable delivery, event acknowledgement **MUST** happen
only after successful HLP projection. Failed projection **MUST** leave the event
unacknowledged.

### JSON Schema And Version Negotiation

`HLP-industrial` implementations **SHOULD** expose an object/wire JSON Schema
registry. The reference implementation provides `HLP_JSON_SCHEMAS`,
`schema_for(name)`, `to_wire(value)`, and `validate_wire_object(name, value)`
for:

- `Task`
- `Checkpoint`
- `Ownership`
- `Review`
- `Artifact`
- `Ledger`
- `ProtocolError`
- `AuditEvent`
- `HarnessEvent`
- `HarnessEventDelivery`
- `PermissionGrant`
- `ProposedAction`
- `AdapterOperationContext`
- `AdapterOutboxRecord`
- `VersionNegotiation`

`to_wire()` **MUST** convert dataclasses into JSON-compatible objects: timestamps
use RFC3339 strings, tuples become arrays, Python aliases such as `from_` /
`as_` become `from` / `as`, and `schema_version` plus `profile` are added.

Every transport wire envelope **MUST** carry:

```yaml
spec_version: "0.2.0-draft"
schema_version: "0.2"
profile: "HLP-industrial"
```

Version negotiation **MUST** fail fast. If peers share no `spec_version`,
`schema_version`, or `profile`, implementations **MUST** return
`VERSION_UNSUPPORTED` rather than silently downgrading to ambiguous semantics.

## Conformance

An implementation claiming HLP 0.2.0-draft compatibility **MUST**:

1. Support all seven first-class objects.
2. Implement all 23 operations.
3. Enforce the Task state machine.
4. Enforce the immutability rules (including append-only `steering_log` and
   `PermissionGrant`).
5. Emit audit events for every state-changing protocol operation.
6. Validate operation preconditions.
7. Satisfy the integration contracts when routed into existing agent harness or
   capability systems.
8. Support the full semantics of `task.interrupt` (human-initiated pause) and
   `task.amend` (steering without restart), including the `steer` adapter
   action and `state_patch` / `edited_artifact_ref` resume semantics.
9. If claiming event-streaming integration, support non-destructive
   `HarnessEventDelivery` projection and acknowledge events only after
   successful HLP projection.

`HLP-compatible` and `HLP-integrated` claims do not imply `HLP-industrial`.
Industrial claims additionally require per-task CAS, idempotency keys, durable
outbox, reducer-ready audit payloads, permission scope grammar, object/wire
JSON schemas, and version negotiation evidence.

## Open Issues

The following topics remain intentionally draft-scoped:

| Issue | Draft stance |
| --- | --- |
| Transport binding | Not specified; implementations may choose HTTP, gRPC, WebSocket, stdio, or host APIs. |
| Checkpoint expiration default | Implementation-defined; pure suspension plus configuration is recommended. A `kind=interrupt` checkpoint **SHOULD** remain purely suspended, since a human-initiated interrupt means "await human". |
| Delegation depth | Allowed through `delegable`, but limits are host policy. |
| Ledger conflict handling | Last-write-wins plus audit is acceptable in this draft. A single pending checkpoint per task is **SHOULD**; use a checkpoint's `proposed_actions` to ask about multiple things at once. |
| Multi-reviewer verdicts | Not standardized; single reviewer is the baseline. |
| Cross-project artifact references | Require explicit authorization; mechanism is host-defined. |
| Version compatibility | Expected to follow semantic versioning after implementation feedback. |

## Reference Flow

```text
Human Alice                 HLP                         Agent Devin
  | task.create              |                             |
  | task.assign              | -> harness delegate(TaskID) |
  | task.amend               | -> harness steer            | (steering_log += "focus on auth"; no state change)
  | task.interrupt           | -> harness block            | (-> blocked; system raises kind=interrupt checkpoint)
  | checkpoint.resolve       | -> harness resume           | (approve + state_patch -> in_progress; resume from patch)
  |                           | <- needs_approval           |
  | <- checkpoint notice      | -> harness block            |
  | checkpoint.resolve        | -> harness resume           |
  |                           | <- artifact(plan v1)        |
  | review.submit(plan, approved) | -> in_progress         | (plan approved, continue implementation)
  |                           | <- artifact(deliverable v2) |
  | review.submit(changes)    | -> in_progress              |
  |                           | <- artifact.commit(v3)      |
  | review.submit(approved)   | -> accepted -> completed    |
  |                           | -> ledger.write             |
  | audit.replay              | reconstructs the flow       |
```

This flow exercises task assignment, continuous control (amend steering,
interrupt, state_patch resume), checkpoint gating, plan vs deliverable review,
artifact delivery, rework, completion, ledger persistence, and audit replay.

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| 0.1.0-draft | 2026-06-19 | Initial draft. |
| 0.2.0-draft | 2026-07-02 | Continuous-control extension: added `task.interrupt` / `task.amend` + `steering_log`; `PermissionGrant` / `autonomy` pre-authorization; `Checkpoint.proposed_actions` batch approval with partial approve/deny; `CheckpointResolution.state_patch` / `edited_artifact_ref` resume-with-state; `Review.kind` distinguishing plan vs deliverable review; state machine gains the interrupt edge and the plan-approved return to `in_progress`. See `docs/plans/2026-07-02-hlp-continuous-control-extension.md`. |
