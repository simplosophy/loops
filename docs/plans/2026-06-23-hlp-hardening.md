# HLP Hardening Plan

## Goal

Strengthen the HLP reference implementation after architecture review, focusing on protocol trust boundaries rather than broad product features.

## Status

Implemented in the 2026-06-23 hardening pass for embedded/reference semantics. Production durable store v2, audit hash chain, and transactional outbox remain follow-up work.

## Scope

- Keep `loop2` as the HLP control plane and preserve the `AgentAdapter` boundary.
- Make adapter failure semantics honest: HLP state must not advance when the required adapter operation fails.
- Stop SDK/read APIs from returning mutable live aggregate objects.
- Add a minimal identity policy for human/agent role checks and checkpoint authorization.
- Align event bus usage with the public `EventBus.publish(HLPEvent)` protocol.
- Improve run correlation for handoff, delegate, cancel, and checkpoint resume payloads.
- Document durable store v2 and audit hash-chain work as a follow-up if it is too large for this pass.

## Non-goals

- No loop0/loop1 dependency.
- No HTTP/gRPC server.
- No mandatory third-party SDK dependency.
- No full SQLite object-table migration in this pass unless the focused test surface remains small.

## Implementation Steps

1. Add failing tests for adapter failure rollback, SDK/read snapshot isolation, custom `EventBus`, checkpoint authorization, handoff/cancel run binding, and completed lifecycle.
2. Refactor `HumanLoopStore` to expose read snapshots while keeping internal mutation access for `HumanLoopOperations`.
3. Reorder adapter-coupled operations so external adapter calls happen before HLP state/audit commits, or explicitly fail before state advances.
4. Add identity checks and action-specific checkpoint resolution validation.
5. Update adapter helpers for correlation validation, unknown-run errors, richer resume payloads, LangGraph config normalization, and safer prompt serialization.
6. Update architecture/spec docs and notes with the remaining store/audit hardening roadmap.
7. Run focused HLP tests, demo commands, and full test suite.

## Architecture Fit

This plan preserves the existing layering principle: `loop2` owns HLP coordination semantics, and lower runtime behavior is reached only through explicit adapter commands. The changes tighten interface contracts and failure boundaries without adding cross-layer imports or transport assumptions.
