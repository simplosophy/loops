---
title: L0 Capability Protocol Routes
outline: [2, 3]
---

# L0 Capability Protocol Routes

HLP does not define a new tool or capability protocol. This page is an
integration guide for recording human-relevant capability evidence from
existing capability ecosystems such as MCP servers, Agent Skills, local tools,
or function-calling registries.

HLP core does not require capability references. When capability evidence is
useful for a human decision or audit replay, HLP may store an opaque external
reference. Actual discovery, authorization, schema handling, and invocation
remain owned by the agent harness, host platform, or L0 ecosystem.

## What HLP Needs From L0

| HLP need | L0 expectation |
| --- | --- |
| Explain capability evidence | Provide a stable external id only when the evidence matters to a human decision or audit. |
| Hide transport | Keep stdio, SSE, HTTP, local function names, and credentials below HLP. |
| Explain inputs | Expose enough manifest/schema data through the host or harness for task constraints and review. |
| Preserve provenance | Let artifacts and audit events reference which capability was used. |
| Report failures | Return structured errors through the agent harness or host platform. |

Capability integrations may standardize a profile over HLP `ExternalRef`:

```yaml
ExternalRef:
  kind: "capability"
  namespace: "mcp"
  id: "cap:code-review"
  version: "2.1.0"
  label: "Code review tool"
```

## Existing Protocol Routes

| Route | Use when | HLP adapter focus |
| --- | --- | --- |
| MCP | Tools are exposed through MCP servers. | Map tool names and versions into `ExternalRef(kind="capability")` only when HLP needs evidence; keep transport below the agent harness. |
| Agent Skills | Capabilities are packaged with instructions, resources, and permission expectations. | Treat the skill package as the capability identity and record skill version in provenance. |
| Local tools | The host platform invokes in-process or CLI tools. | Publish a manifest/registry entry so HLP never depends on raw command strings. |
| Function calling | Capabilities are model-provider functions. | Add host-side discovery and stable ids before referencing them from HLP tasks. |

## Adapter Boundary

HLP should never call a capability directly. The normal path is:

```text
HLP ExternalRef evidence, if needed
  -> L1 agent harness
  -> selected L0 capability route
  -> tool, skill, or function implementation
```

HLP records intent and provenance. The agent harness decides how to invoke the
capability, handle retries, and translate provider-specific errors.

## What HLP Does Not Standardize

HLP does not choose:

- MCP transport.
- Skill package format.
- Function-calling provider schema.
- Tool authentication.
- Sandbox policy.
- Retry, timeout, or rate-limit behavior.

Those decisions belong to the capability ecosystem or the host platform.

## Implementation Checklist

- Assign stable ids and versions to capabilities that may appear in human
  decisions, artifact provenance, or audit evidence.
- Keep transport endpoints and credentials out of HLP task specs.
- Expose enough manifest data for humans to understand why a task requires a
  capability.
- Record capability use in artifact provenance or audit evidence.
- Route invocation through the agent harness or host platform, not through HLP
  operations.

For the exact HLP-side boundary, see [Integration Contracts](./contracts).
