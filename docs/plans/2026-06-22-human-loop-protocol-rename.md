# Human Loop Protocol Rename Plan

> Date: 2026-06-22
> Status: In progress
> Scope: Rename the L2 protocol and reference implementation to Human Loop Protocol (HLP).

## Goal

Use Human Loop Protocol (HLP) as the public name for the L2 protocol across code, tests, specs, architecture docs, and the public site.

## Scope

- Rename public loop2 API types from the old acronym to Human Loop names.
- Rename spec and site pages from the old L2 acronym path to HLP-oriented paths.
- Update diagrams, conformance docs, protocol maps, plans, and notes so the stack reads HLP / AAP / CAP.
- Keep protocol semantics unchanged.

## Non-goals

- No changes to CAP or AAP semantics.
- No loop1 implementation work.
- No persistence or transport changes.

## Verification

- `uv run pytest -q`
- Site build and verification if site scripts are available.
- Repository search for stale L2 acronym references, excluding intentionally historical git data.
