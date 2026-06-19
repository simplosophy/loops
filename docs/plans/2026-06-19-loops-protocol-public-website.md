# Loops Protocol Public Website Plan

> Date: 2026-06-19
> Status: Implementation plan
> Scope: Rework the VitePress site in `docs/site/` into a complete English public-facing protocol website.

## Goal

Build an English website for the Loops Protocol Stack that is credible as a public protocol site: clear positioning, formal layer descriptions, implementation routes, conformance rules, inter-layer contracts, and a polished technical presentation.

## Source of Truth

- `docs/specs/HACP.md` defines the full HACP 0.1.0-draft protocol surface.
- `docs/specs/AAP.md` defines the AAP L1 conformance profile.
- `docs/specs/CAP.md` defines the CAP L0 conformance profile.
- `docs/architecture/LOOPS_STACK.md` and `docs/plans/2026-06-19-loops-protocol-stack.md` define the public positioning: Loops is a protocol stack, not another runtime framework.

## Site Information Architecture

- Home: protocol positioning, stack diagram, layer summaries, adoption paths.
- Overview: problem statement, stack model, design principles, responsibilities.
- Implementation Guide: role-based reading paths and adoption sequence.
- Conformance: what it means to claim CAP, AAP, HACP, or full-stack conformance.
- Inter-layer Contracts: quick reference for CapabilityRef, TaskID correlation, Checkpoint-to-Block, Ownership-to-Handoff.
- Specifications:
  - HACP: full English protocol page with objects, operations, state machine, errors, conformance, open issues, and example flow.
  - AAP: English conformance profile for agent-to-agent runtimes.
  - CAP: English conformance profile for capability providers.

## Quality Bar

- All rendered site copy is English.
- Pages use normative language where appropriate (`MUST`, `SHOULD`, `MAY`).
- The site explains what Loops creates versus what it profiles from existing ecosystems.
- The site is navigable by implementer role, not only by internal architecture layer.
- Build must pass with `npm run build`.
