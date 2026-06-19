---
title: CAP — Capability Protocol Profile
outline: [2, 3]
---

# CAP — Capability Protocol Profile

| Field | Value |
| --- | --- |
| Version | 0.1.0-draft |
| Status | Draft |
| Layer | L0, bottom layer of the Loops Protocol Stack |
| Document type | Conformance profile |
| Primary concern | Agent-callable tools and skills |

CAP defines the minimum L0 surface required for agents to discover and invoke
capabilities in the Loops Protocol Stack.

CAP is not a replacement for MCP or Skills. It is the profile that lets existing
capability systems participate in a layered stack without leaking transport
details upward.

Normative keywords follow RFC 2119.

## Scope

CAP governs:

- Capability identity and versioning.
- Capability manifests.
- Discovery through list and describe operations.
- Invocation result shape.
- Capability error semantics.
- `CapabilityRef` as the only legal upper-layer reference.

CAP does not govern:

- Who the caller is; HACP and the host platform own that context.
- Agent sessions, memory, or run state.
- Organization RBAC or billing.
- How an agent decides which capability to call.
- The concrete transport used by an MCP server, Skills runtime, or local host.

## Capability

```yaml
Capability:
  capability_id: string
  version: string
  kind: "tool" | "skill"
  manifest: CapabilityManifest
```

Rules:

- `(capability_id, version)` **MUST** be globally unique within the capability
  source.
- `version` **SHOULD** follow semantic versioning.
- `kind` **MUST** be either `tool` or `skill`.

## CapabilityRef

`CapabilityRef` is CAP's cross-layer reference object.

```yaml
CapabilityRef:
  capability_id: string
  version: string
```

Rules:

- AAP and HACP **MUST** use `CapabilityRef` to refer to capabilities.
- Upper layers **MUST NOT** depend on transport details such as stdio commands,
  SSE endpoints, HTTP paths, or local function names.

## Tool and Skill Granularity

| Dimension | Tool | Skill |
| --- | --- | --- |
| Shape | Single callable function | Packaged capability |
| Prompt template | No | Yes |
| Bundled resources | No | Yes |
| Permission declaration | Optional or host-defined | Required by manifest |
| Invocation semantics | `input -> output` | `vars -> result + side effects` |
| Typical mapping | MCP tool | Skills protocol |

A skill **MUST** be reducible to a package of tools, prompt instructions,
resources, and permission declarations. This prevents CAP from splitting into
two unrelated capability models.

## Capability Manifest

```yaml
CapabilityManifest:
  capability_id: string
  version: string
  kind: "tool" | "skill"
  name: string
  description: string
  input_schema: JSONSchema
  output_schema: JSONSchema | null
  prompt_template: string | null
  resources: [Resource] | null
  required_permissions: [string] | null
```

Rules:

- `input_schema` **MUST** be present.
- `output_schema` **SHOULD** be present.
- `prompt_template`, `resources`, and `required_permissions` are required for
  skills when the underlying Skills system supports them.
- Custom manifest fields **MAY** be added, but they **MUST NOT** be required by
  upper layers to preserve basic CAP compatibility.

## Discovery

```yaml
capability.list() -> [CapabilityManifest]
capability.describe(capability_id, version) -> CapabilityManifest | NOT_FOUND
```

Rules:

- A conforming L0 **MUST** provide both operations.
- `describe` **MUST** return `NOT_FOUND` for unknown id/version pairs.
- A registry **MAY** cache manifests, but invocation must still validate against
  the manifest contract.

## Invocation

```yaml
capability.invoke(ref: CapabilityRef, input: object) -> InvokeResult

InvokeResult:
  ok: boolean
  output: object | null
  error: CapabilityError | null
  duration_ms: integer
```

Rules:

- `invoke` **MUST** validate `input` against `input_schema`.
- If validation fails, `invoke` **MUST** return `INVALID_INPUT`.
- If `output_schema` is declared, successful output **MUST** conform to it.
- The CAP contract is synchronous from the caller's perspective. Implementations
  **MAY** use asynchronous internals as long as the protocol result preserves the
  `InvokeResult` shape.

## Errors

| Code | Meaning |
| --- | --- |
| `NOT_FOUND` | Capability id/version does not exist |
| `INVALID_INPUT` | Input failed schema validation |
| `PERMISSION_DENIED` | Required permission is missing |
| `EXECUTION_FAILED` | Capability failed during execution |
| `TIMEOUT` | Capability execution exceeded deadline |

## Reference Mappings

### MCP

| CAP profile requirement | MCP mapping |
| --- | --- |
| `capability.list` | `tools/list` |
| `capability.describe` | `tools/list` plus id/version filtering or host registry |
| `capability.invoke` | `tools/call` |
| `input_schema` | MCP tool `inputSchema` |
| Transport hiding | Host-level adapter over stdio, SSE, or HTTP |

Any MCP server that exposes tools with input schemas can satisfy the Tool
portion of CAP through a thin adapter.

### Skills

| CAP profile requirement | Skills mapping |
| --- | --- |
| Capability manifest | Skill manifest |
| `capability.invoke` | Skill invocation |
| Prompt template | Skill instructions or template |
| Resources | Skill resources |
| Permissions | Skill permission declaration |

Skills naturally satisfy the Skill portion of CAP when they expose manifests and
invocation semantics.

### Function Calling

Function-calling registries can satisfy CAP Tool invocation semantics, but they
usually lack discovery. A host registry must provide `list`, `describe`, and
stable `CapabilityRef` values before claiming CAP compatibility.

## Inter-layer Contracts

CAP is L0. Upper layers refer to it only through `CapabilityRef`.

| Upper layer | Allowed behavior | Forbidden behavior |
| --- | --- | --- |
| AAP | Invoke capabilities by reference | Depend on MCP transport or raw tool endpoint |
| HACP | Declare required capabilities by reference | Call tools directly |

Example task constraint:

```yaml
constraints:
  must_use_capabilities:
    - capability_id: "cap:code-review"
      version: "2.1.0"
```

## Conformance

An implementation claiming CAP 0.1.0-draft compatibility **MUST**:

1. Provide `capability.list`, `capability.describe`, and `capability.invoke`.
2. Give every capability a globally unique `(capability_id, version)`.
3. Include `input_schema` in every manifest.
4. Return `InvokeResult` from invocation.
5. Use the defined error semantics.

An implementation **MAY**:

- Support only tools.
- Support only skills.
- Support both tools and skills.
- Choose any transport.
- Add custom manifest fields.

## Open Issues

| Issue | Draft stance |
| --- | --- |
| Version fallback | Semantic versioning plus explicit compatibility declarations are recommended. |
| Long-running capabilities | Asynchronous internals are allowed; progress protocol is not standardized. |
| Side-effect declarations | A future manifest field such as `side_effects` is expected. |
| Skill permission schema | Align with Skills ecosystem evolution. |

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| 0.1.0-draft | 2026-06-19 | Initial L0 conformance profile for capability sources. |
