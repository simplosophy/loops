# HLP Conformance

Conformance is claimed for HLP. L1 and L0 integrations provide evidence that
HLP can route work into existing agent and capability ecosystems without losing
task identity, checkpoint control, or provenance.

Normative keywords on this site follow RFC 2119 usage: **MUST**, **MUST NOT**,
**SHOULD**, **SHOULD NOT**, and **MAY**.

## Claim Levels

| Claim | Meaning |
| --- | --- |
| HLP-compatible | The implementation supports the HLP object model, operations, state machine, immutability, and audit requirements. |
| HLP-integrated | The implementation is HLP-compatible and preserves HLP contracts through one or more agent/capability adapters. |

Do not claim HLP integration if the lower runtime loses HLP task correlation or
lets agents bypass human checkpoints.

## HLP 0.1.0-draft Requirements

An implementation claiming HLP compatibility **MUST**:

1. Support all seven first-class objects: Task, Checkpoint, Ownership, Review,
   Artifact, Ledger, and Audit.
2. Implement all 21 HLP operations.
3. Enforce the HLP Task state machine.
4. Enforce immutability for Task specs, Artifact versions, Reviews, Ledger
   entries, and Audit events.
5. Produce audit events for every protocol operation that changes state.
6. Validate operation preconditions before state changes.
7. Keep HLP transport-agnostic: HTTP, gRPC, WebSocket, event bus, or in-process
   APIs are implementation choices, not protocol requirements.

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
| Ownership-to-Handoff | Ownership transfer preserves task correlation through runtime handoff. |
| CapabilityRef | Task constraints reference capabilities by `(capability_id, version)` without transport endpoints. |

The evidence can come from A2A, ACP, AGNTCY-style meshes, MCP, Agent Skills, a
custom host runtime, or another existing system. HLP does not require a specific
lower protocol.

## Evidence Checklist

Before publishing a compatibility claim, produce evidence for:

| Evidence | HLP-compatible | HLP-integrated |
| --- | --- | --- |
| Public API or protocol description | Required | Required |
| State machine tests | Required | Required |
| Immutable record tests | Required | Required |
| Error semantic tests | Required | Required |
| Audit replay demonstration | Required | Required |
| Cross-runtime correlation trace | Recommended | Required |
| Checkpoint block/resume trace | Recommended | Required |
| Capability provenance trace | Recommended | Required when task constraints use capabilities |

## Non-Conforming Patterns

The following patterns are incompatible with HLP conformance:

- A human review system that mutates task specs in place instead of creating a
  new task or version.
- An agent runtime that loses the original TaskID during delegation, retry, or
  handoff.
- A capability registry that requires HLP task specs to know stdio commands,
  SSE endpoints, HTTP paths, or local function names.
- A checkpoint implementation that lets an agent resume itself without a human
  or authorized system resolution.
- An audit log that can be rewritten or deleted after protocol operations occur.

## Draft Policy

The 0.1.0-draft line is intended for early implementation and feedback. Draft
implementations should state which open issues they have chosen to resolve
locally, especially transport binding, checkpoint expiration, ledger conflict
handling, and multi-reviewer verdict aggregation.
