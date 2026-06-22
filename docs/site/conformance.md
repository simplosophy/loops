# Conformance

Loops conformance is claimed per layer. An implementation may conform to CAP,
AAP, HLP, or to the complete stack.

Normative keywords on this site follow RFC 2119 usage: **MUST**, **MUST NOT**,
**SHOULD**, **SHOULD NOT**, and **MAY**.

## Claim Levels

| Claim | Meaning |
| --- | --- |
| CAP-compatible | The implementation exposes the L0 capability profile. |
| AAP-compatible | The implementation exposes the L1 agent delegation profile. |
| HLP-compatible | The implementation implements the L2 Human Loop Protocol. |
| Loops stack-compatible | The implementation satisfies all three layers and the inter-layer contracts. |

Do not claim full-stack compatibility if only one layer is implemented.

## CAP 0.1.0-draft Requirements

An implementation claiming CAP compatibility **MUST**:

1. Provide `capability.list`, `capability.describe`, and `capability.invoke`.
2. Give every capability a globally unique `(capability_id, version)`.
3. Publish an input schema in every capability manifest.
4. Return a structured `InvokeResult` from invocation.
5. Use CAP error semantics for `NOT_FOUND`, `INVALID_INPUT`,
   `PERMISSION_DENIED`, `EXECUTION_FAILED`, and `TIMEOUT`.

An implementation **MAY** support only Tool capabilities, only Skill
capabilities, or both.

## AAP 0.1.0-draft Requirements

An implementation claiming AAP compatibility **MUST**:

1. Support `agent.discover`, `agent.delegate`, `agent.block`, `agent.resume`,
   and `agent.handoff`.
2. Maintain the AAP run states: `running`, `blocked`, `completed`, and `failed`.
3. Attach `correlation_id` to all runs and events.
4. Preserve HLP TaskID as `Run.correlation_id`.
5. Emit the required event stream: `run.started`, `run.progress`,
   `run.blocked`, `run.completed`, and `run.failed`.
6. Use AAP error semantics for agent lookup, capability mismatch, refused
   delegation, missing runs, and invalid transitions.

An implementation **MAY** use A2A, ACP, AGNTCY, or a custom runtime underneath
the profile.

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
7. Use the inter-layer contracts when operating as part of a full Loops stack.

An implementation **MAY** choose its own transport, persistence layer, Task
types, Artifact types, and policies for open issues that remain draft-scoped.

## Full Stack Requirements

A complete Loops stack **MUST** satisfy CAP, AAP, HLP, and the four cross-layer
contracts:

| Contract | Required evidence |
| --- | --- |
| `CapabilityRef` | Upper layers reference capabilities only by `(capability_id, version)` and never by transport endpoint. |
| TaskID correlation | `HLP Task.id = AAP Run.correlation_id` for every delegated run. |
| Checkpoint-to-Block | `checkpoint.raise` blocks the corresponding AAP run; `checkpoint.resolve` resumes it. |
| Ownership-to-Handoff | HLP ownership transfer maps to AAP handoff while preserving correlation. |

## Evidence Checklist

Before publishing a compatibility claim, produce evidence for each layer:

| Evidence | CAP | AAP | HLP | Full stack |
| --- | --- | --- | --- | --- |
| Public manifest or API description | Required | Required | Recommended | Required |
| State machine tests | Recommended | Required | Required | Required |
| Immutable record tests | Not applicable | Recommended | Required | Required |
| Error semantic tests | Required | Required | Required | Required |
| Cross-layer correlation trace | Not applicable | Required | Required | Required |
| Audit replay demonstration | Not applicable | Recommended | Required | Required |

## Non-Conforming Patterns

The following patterns are incompatible with Loops conformance:

- A human review system that mutates task specs in place instead of creating a
  new task or version.
- An agent runtime that loses the original TaskID during delegation or handoff.
- A capability registry that requires upper layers to know whether a tool uses
  stdio, SSE, HTTP, or another transport.
- A checkpoint implementation that lets an agent resume itself without a human
  or authorized system resolution.
- An audit log that can be rewritten or deleted after protocol operations occur.

## Draft Policy

The 0.1.0-draft line is intended for early implementation and feedback. Draft
implementations should state which open issues they have chosen to resolve
locally, especially transport binding, checkpoint expiration, ledger conflict
handling, and multi-reviewer verdict aggregation.
