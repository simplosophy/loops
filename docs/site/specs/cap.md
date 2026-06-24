---
title: L0 Capability Protocol Routes
outline: [2, 3]
---

# L0 Capability Protocol Routes

HLP does not define a new tool or capability protocol. This page is an
integration guide for routing HLP task constraints to existing capability
ecosystems such as MCP servers, Agent Skills, local tools, or function-calling
registries.

HLP only needs stable capability references. Actual invocation remains owned by
the agent harness or host platform.

## What HLP Needs From L0

| HLP need | L0 expectation |
| --- | --- |
| Name required capabilities | Provide stable `(capability_id, version)` references. |
| Hide transport | Keep stdio, SSE, HTTP, local function names, and credentials below HLP. |
| Explain inputs | Expose enough manifest/schema data for task constraints and review. |
| Preserve provenance | Let artifacts and audit events reference which capability was used. |
| Report failures | Return structured errors through the agent harness or host platform. |

The HLP task schema uses `CapabilityRef` for this boundary:

```yaml
CapabilityRef:
  capability_id: "cap:code-review"
  version: "2.1.0"
```

## Existing Protocol Routes

| Route | Use when | HLP adapter focus |
| --- | --- | --- |
| MCP | Tools are exposed through MCP servers. | Map tool names and versions into stable `CapabilityRef` values and keep transport below the agent harness. |
| Agent Skills | Capabilities are packaged with instructions, resources, and permission expectations. | Treat the skill package as the capability identity and record skill version in provenance. |
| Local tools | The host platform invokes in-process or CLI tools. | Publish a manifest/registry entry so HLP never depends on raw command strings. |
| Function calling | Capabilities are model-provider functions. | Add host-side discovery and stable ids before referencing them from HLP tasks. |

## Adapter Boundary

HLP should never call a capability directly. The normal path is:

```text
HLP Task.constraints.must_use_capabilities
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

- Assign stable ids and versions to capabilities that HLP tasks may require.
- Keep transport endpoints and credentials out of HLP task specs.
- Expose enough manifest data for humans to understand why a task requires a
  capability.
- Record capability use in artifact provenance or audit evidence.
- Route invocation through the agent harness or host platform, not through HLP
  operations.

For the exact HLP-side boundary, see [Integration Contracts](./contracts).
