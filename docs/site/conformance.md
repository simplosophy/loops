# HLP Conformance

Conformance is claimed for HLP. Harness, L1, and L0 integrations provide
evidence that HLP can wrap existing agent and capability ecosystems without
losing task identity, checkpoint control, artifact review, or provenance.

Normative keywords on this site follow RFC 2119 usage: **MUST**, **MUST NOT**,
**SHOULD**, **SHOULD NOT**, and **MAY**.

## Claim Levels

| Claim | Meaning |
| --- | --- |
| HLP-compatible | The implementation supports the HLP object model, operations, state machine, immutability, and audit requirements. |
| HLP-integrated | The implementation is HLP-compatible and preserves HLP contracts through one or more agent/capability adapters. |
| HLP-industrial | A separate production profile covering CAS, idempotency, durable outbox, reducer-ready audit, permission grammar, schema envelopes, and version negotiation. |

Do not claim HLP integration if the lower harness loses HLP task correlation,
lets agents bypass human checkpoints, or cannot project human-facing harness
events into HLP objects.

Do not claim `HLP-compatible` or `HLP-integrated` as evidence for
`HLP-industrial`; the industrial profile requires explicit production
consistency and durability evidence.

## Executable Suite

The repository includes an offline conformance suite for the 0.2.0-draft line:

```bash
uv run pytest tests/conformance -q
```

`tests/conformance/test_hlp_compatible_profile.py` exercises the HLP-compatible
claim: required objects, all 23 operations, state transitions, immutable records,
preconditions, audit query/replay, and the 0.2.0 continuous-control values.

`tests/conformance/test_hlp_integrated_profile.py` exercises the HLP-integrated
claim: adapter correlation, checkpoint/artifact projection, resume payloads,
reliable event cursor acknowledgement, and fail-fast behavior when an external
process adapter does not return a run id.

`tests/conformance/test_hlp_industrial_profile.py` exercises the current
industrial reference slice: per-task revision, stale revision conflicts before
adapter calls, task-scoped idempotency-key replay, and stable replay for
generated checkpoints and artifacts. It also covers permission scope grammar,
wildcard matching, grant expiry, deny precedence, and tamper-evident audit
hash-chain verification. Audit coverage also checks reducer-ready subject,
task snapshot, and change payloads. JSON schema registry and version
negotiation checks cover first-class object schemas, ProtocolError, AuditEvent,
HarnessEvent delivery, PermissionGrant, ProposedAction, VersionNegotiation, and
dataclass wire serialization aliases. Adapter outbox coverage verifies that HLP persists
adapter intent before side effects, passes `AdapterOperationContext` through
fake and process adapters for delegate, handoff, cancel, steer, block, and
resume, and marks committed outbox records succeeded.

## HLP 0.2.0-draft Requirements

An implementation claiming HLP compatibility **MUST**:

1. Support all seven first-class objects: Task, Checkpoint, Ownership, Review,
   Artifact, Ledger, and Audit.
2. Implement all 23 HLP operations.
3. Enforce the HLP Task state machine.
4. Enforce immutability for Task specs, Artifact versions, Reviews, Ledger
   entries, and Audit events, including the append-only `steering_log` and
   `PermissionGrant` value objects.
5. Produce audit events for every protocol operation that changes state.
6. Validate operation preconditions before state changes.
7. Keep HLP transport-agnostic: HTTP, gRPC, WebSocket, event bus, or in-process
   APIs are implementation choices, not protocol requirements.
8. Support the full semantics of `task.interrupt` (human-initiated pause) and
   `task.amend` (steering without restart), including the `steer` adapter
   action and `state_patch` / `edited_artifact_ref` resume semantics.

An implementation **MAY** choose its own persistence layer, Task types, Artifact
types, notification channels, identity model, RBAC model, and policies for open
issues that remain draft-scoped.

## Integration Evidence

An implementation claiming HLP integration **MUST** provide evidence for the
contracts it uses:

| Contract | Required evidence |
| --- | --- |
| TaskID correlation | Every delegated run/event carries the HLP `Task.id` as correlation. |
| Checkpoint-to-Block | `checkpoint.raise` blocks the corresponding run; `checkpoint.resolve` resumes it. |
| Harness event projection | Approval, input, choice, and artifact events become HLP checkpoints or artifacts. |
| Reliable event delivery | Event-streaming adapters retain unacknowledged events on projection failure and acknowledge only successful per-run prefixes. |
| Task CAS and idempotency | Task aggregate mutations expose `revision`, reject stale `expected_task_revision`, and replay matching `idempotency_key` requests without duplicate side effects. |
| Permission scope grammar | Grants normalize scope strings, ignore expired grants, and give active matching deny entries precedence over allow entries. |
| Audit hash chain and reducer payload | Audit events carry reducer-ready subject/task/change payloads, schema/profile metadata, `prev_hash`, and a canonical SHA-256 hash that detects mutation. |
| Schema and version negotiation | Wire objects validate against registered JSON schemas and unsupported spec/schema/profile combinations fail fast. |
| Adapter outbox context | Adapter side effects receive stable `operation_context` metadata and have durable outbox records for retry/dedupe evidence. |
| Ownership-to-Handoff | Ownership transfer preserves task correlation through harness handoff. |
| External evidence reference | Capability evidence, when used, is stored as opaque external references without transport endpoints. |

The evidence can come from A2A, ACP, AGNTCY-style meshes, MCP, Agent Skills, a
custom host platform, an existing agent harness, or another existing system. HLP
does not require a specific lower protocol.

## Evidence Checklist

Before publishing a compatibility claim, produce evidence for:

| Evidence | HLP-compatible | HLP-integrated |
| --- | --- | --- |
| Public API or protocol description | Required | Required |
| State machine tests | Required, covered by `tests/conformance` | Required |
| Immutable record tests | Required, covered by `tests/conformance` | Required |
| Error semantic tests | Required, covered by `tests/conformance` | Required |
| Audit replay demonstration | Required, covered by `tests/conformance` | Required |
| Cross-harness correlation trace | Recommended | Required, covered by `tests/conformance` |
| Checkpoint block/resume trace | Recommended | Required, covered by `tests/conformance` |
| Harness event projection trace | Recommended | Required when wrapping an existing harness; covered by `tests/conformance` |
| Capability provenance trace | Optional | Required only when the integration claims capability evidence support |

## Non-Conforming Patterns

The following patterns are incompatible with HLP conformance:

- A human review system that mutates task specs in place instead of creating a
  new task or version.
- An agent harness that loses the original TaskID during delegation, retry, or
  handoff.
- A harness wrapper that exposes approvals only as opaque log lines instead of
  HLP checkpoints.
- A capability registry that requires HLP task specs or external evidence refs
  to know stdio commands, SSE endpoints, HTTP paths, or local function names.
- A checkpoint implementation that lets an agent resume itself without a human
  or authorized system resolution.
- An audit log that can be rewritten or deleted after protocol operations occur.

## Draft Policy

The 0.2.0-draft line is intended for early implementation and feedback. Draft
implementations should state which open issues they have chosen to resolve
locally, especially transport binding, checkpoint expiration, ledger conflict
handling, and multi-reviewer verdict aggregation.
