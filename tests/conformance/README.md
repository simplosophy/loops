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
  harness event projection into checkpoints and artifacts. Event-streaming
  integrations must retain unacknowledged events when projection fails and move
  per-run cursors forward only after successful projection.
- `HLP-industrial` reference slice: per-task revision, task-scoped
  idempotency-key replay across every existing Task aggregate mutation that
  advances `Task.revision`, stale revision conflicts before adapter calls, and
  stable replay for generated checkpoints/artifacts/reviews. It also covers
  permission scope grammar, wildcard matching, expiry, deny precedence, and
  tamper-evident audit hash-chain verification plus reducer-ready
  subject/task/change payloads.
  JSON schema registry and version negotiation checks cover first-class object
  schemas, ProtocolError, AuditEvent, HarnessEvent delivery, PermissionGrant,
  ProposedAction, VersionNegotiation, AdapterOperationContext,
  AdapterOutboxRecord, and dataclass wire serialization aliases. Adapter outbox
  tests verify durable intent before side effects,
  operation context propagation for delegate, handoff, cancel, steer, block,
  and resume, and succeeded status after local commit.

`HLP-compatible` and `HLP-integrated` do not imply `HLP-industrial`. Industrial
claims additionally need a documented production profile for CAS, idempotency,
durable outbox, reducer-ready audit payloads, permission grammar, schema
envelopes, and version negotiation.

The suite is intentionally offline. Real local CLI smoke tests remain opt-in
because they depend on user-installed Codex/Kimi/Claude binaries and credentials.
