# CapabilityRef Boundary Refactor Plan

## Goal

Move capability awareness out of HLP core. HLP should record human-relevant external evidence, while `CapabilityRef` becomes an optional integration pattern owned by L0/host ecosystems.

## Design

- Add a generic `ExternalRef` value object to represent opaque external evidence.
- Replace `Constraints.must_use_capabilities` with `Constraints.external_refs`.
- Treat capability refs as `ExternalRef(kind="capability", namespace=..., id=..., version=...)`, not as a first-class HLP object.
- Move `CapabilityRef` language from HLP core spec/conformance into integration contracts and L0 route docs as an optional profile.
- Strengthen site verification so HLP core cannot regress to requiring capability refs.

## Tasks

1. Add failing protocol tests for `ExternalRef` and public API exports.
2. Implement `ExternalRef` in `loops.hlp.objects` and export it from `loops.hlp` and `loops`.
3. Update HLP specs and architecture docs so core `TaskSpec.constraints` carries `external_refs`, not `must_use_capabilities`.
4. Update L0/contracts/conformance/site docs so `CapabilityRef` is optional integration evidence, not a HLP core requirement.
5. Update `verify-site.mjs` with assertions for the new boundary.
6. Run protocol tests, site build, site verification, browser inspection, commit, deploy, and live content checks.

## Verification

- `uv run pytest tests/test_hlp_protocol.py tests/test_hlp_sdk.py`
- `BASE_PATH=/ SITE_URL=https://ontheloops.com npm run build`
- `BASE_PATH=/ SITE_URL=https://ontheloops.com npm run verify:site`
- `npm run inspect:site -- http://127.0.0.1:4180/`
- GitHub Pages workflow success and live HTML checks.
