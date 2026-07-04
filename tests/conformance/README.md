# HLP Conformance Tests

These tests are the executable evidence for HLP 0.2.0-draft compatibility.

Run:

```bash
uv run pytest tests/conformance -q
```

Profiles covered here:

- `HLP-compatible`: object model, 23 operations, state machine, immutability,
  preconditions, audit, and replay.
- `HLP-integrated`: adapter correlation, block/resume/steer contract calls, and
  harness event projection into checkpoints and artifacts.

The suite is intentionally offline. Real local CLI smoke tests remain opt-in
because they depend on user-installed Codex/Kimi/Claude binaries and credentials.
