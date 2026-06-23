# HLP-first API Refactor Plan

## Goal

Make Human Loop Protocol (HLP) the external product surface of the project. The public API should lead with HLP protocol objects, SDK, adapters, and host. `loop0`, `loop1`, and `loop2` remain internal/evolutionary implementation layers rather than the product story.

## Scope

- Flip top-level `loops` exports from loop0 runtime compatibility to HLP-first exports.
- Remove top-level `sys.modules` compatibility aliases for `loops.providers`, `loops.tools`, `loops.agent`, and similar loop0 paths.
- Add a minimal `HLPHost` public object that wires store, adapter, event bus, and `HLPClient` as the embedding surface.
- Remove AAP compatibility aliases from public exports and rename `HumanLoopOperations.aap` to `adapter`.
- Update tests, examples, README, and architecture docs to treat loop0 as optional/internal runtime and `loops.hlp` / top-level `loops` as the HLP product API.

## Non-goals for this pass

- Physically move all `loops/loop2/*` implementation files into `loops/hlp/*`.
- Remove `loops.loop0`; it remains useful as a minimal runtime and demo adapter target.
- Implement the full HLP Host/channel runtime. This pass introduces the public host seam and leaves richer channel behavior for later.

## Architecture Decision

The product identity is HLP. `loops` and `loops.hlp` should both point users at HLP concepts. Internal layer names can remain while implementation is still evolving, but they must not be the main public API or documentation spine.

## Verification

- Tests must prove `import loops` exposes HLP symbols and does not expose loop0 runtime shortcuts such as `agent`.
- HLP tests must use `AgentAdapter` naming, not AAP aliases.
- loop0 tests must import from `loops.loop0` explicitly.
- Full test suite must pass after the break.
