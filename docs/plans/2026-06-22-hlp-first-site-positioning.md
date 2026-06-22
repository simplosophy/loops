# HLP-first Site and Specification Positioning

> Date: 2026-06-22
> Scope: Reposition the project around Human Loop Protocol (HLP).

## Goal

Make HLP the primary protocol this project defines. L1 and L0 protocol material
should become introductory routing pages that explain how HLP connects to
existing agent and capability ecosystems.

## Decisions

- HLP remains the only complete protocol specification.
- L1 is described as agent protocol routes: A2A, ACP, AGNTCY-style meshes, or
  custom runtimes.
- L0 is described as capability protocol routes: MCP, Agent Skills, local
  tools, or function-calling registries.
- The former AAP/CAP pages are retained as stable routes but rewritten as
  integration guides, not conformance profiles.
- Conformance is claimed for HLP. Lower layers provide integration evidence,
  not independent Loops protocol compatibility claims.

## Files To Update

- Site navigation, homepage, overview, implementation guide, integration map,
  conformance, contracts, and HLP spec page.
- L1/L0 route pages under `docs/site/specs/`.
- Source specifications under `docs/specs/`.
- Architecture docs and notes.
- Site diagrams and Open Graph assets.

## Verification

- Build the VitePress site.
- Run the site verification script.
- Run Python tests to ensure docs-only changes did not affect the reference
  implementation.
- Grep for old “AAP/CAP conformance profile” and “Loops defines all three
  layers” framing.
