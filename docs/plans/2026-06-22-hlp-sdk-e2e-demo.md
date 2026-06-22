# HLP End-to-End SDK and Demo Plan

## Goal

Build an industrial-grade Human Loop Protocol (HLP) SDK and runnable end-to-end demo. The SDK must keep HLP focused on human responsibility loops while integrating with major agent runtimes through explicit adapters.

## Architecture

HLP is a control-plane SDK, not a replacement agent runtime. It owns Task, Checkpoint, Review, Artifact, Ledger, Audit, and the human responsibility semantics around them. External agents, CLIs, and frameworks are connected through adapter contracts that preserve `task_id` as the correlation id.

The core package remains transport-agnostic and does not import `loop0` or `loop1`. Optional framework integrations live behind adapters so OpenAI, Codex, Claude Code, LangGraph, CrewAI, and similar ecosystems do not become mandatory dependencies.

## Compatibility Scope

The first compatibility target is adapter shape, not deep vendor coupling:

- OpenAI Agents SDK: in-process Python adapter target.
- OpenAI Python SDK: direct model adapter target for baseline agent loops.
- Codex CLI: process adapter target.
- Claude Code CLI / Agent SDK: process or SDK adapter target.
- LangGraph or CrewAI: in-process Python adapter target.
- `herms`: until the concrete project is confirmed, support it through the generic process adapter contract.

## Files

- Create `loops/hlp/__init__.py`: stable public HLP SDK import surface.
- Create `loops/loop2/sdk.py`: `HLPClient`, high-level lifecycle methods, and end-to-end workflow helpers.
- Create `loops/loop2/adapters.py`: `AgentAdapter`, `AgentRunHandle`, process/fake adapter base types, and compatibility aliases.
- Create `loops/loop2/events.py`: structured SDK event records and in-memory event bus.
- Create `loops/loop2/sqlite_store.py`: durable SQLite-backed `HumanLoopStore` implementation.
- Create `examples/hlp_e2e_demo.py`: dependency-free demo using deterministic fake agent behavior.
- Modify `loops/loop2/operations.py`: accept the new adapter protocol while preserving existing behavior.
- Modify `loops/loop2/__init__.py`: export the new SDK surface.
- Modify `pyproject.toml`: add an HLP demo console script.
- Create `tests/test_hlp_sdk.py`: SDK facade, adapter contract, SQLite persistence, and demo-level flow tests.

## Task 1: SDK Facade Contract

Write failing tests that import `HLPClient` from `loops.hlp`, create a task, delegate it to an adapter, start the run, raise and resolve a checkpoint, commit an artifact, submit review, write ledger state, and replay audit history. The test must assert that:

- SDK users do not need to call `HumanLoopOperations` directly.
- The assigned adapter receives `delegate`, `block`, and `resume`.
- The task id is retained as adapter correlation id.
- Audit replay contains the lifecycle actions.

Then implement `loops/hlp/__init__.py` and `loops/loop2/sdk.py` as a thin, typed facade over the existing protocol operations.

Verification:

```bash
uv run pytest tests/test_hlp_sdk.py -q
```

## Task 2: Agent Adapter Contract

Write failing tests for a new `AgentAdapter` protocol and deterministic fake adapter. The adapter must support:

- `delegate`
- `block`
- `resume`
- `handoff`
- `cancel`
- `healthcheck`

Then implement `loops/loop2/adapters.py` and keep `AAPBridge` as a compatibility alias for existing code paths during the transition.

Verification:

```bash
uv run pytest tests/test_hlp_sdk.py::test_fake_agent_adapter_records_contract_calls -q
uv run pytest tests/test_loop2_hlp.py -q
```

## Task 3: SDK Events

Write failing tests that subscribe to SDK events and verify lifecycle events are emitted in order for task creation, delegation, checkpoint, resolution, artifact commit, review, ledger write, and audit replay.

Then implement `loops/loop2/events.py` and emit events from `HLPClient` methods without moving protocol state ownership out of `HumanLoopOperations`.

Verification:

```bash
uv run pytest tests/test_hlp_sdk.py::test_hlp_client_emits_lifecycle_events_in_order -q
```

## Task 4: Durable Store

Write failing tests proving that task, checkpoint, artifact, review, ledger, run binding, and audit data survive a client restart with the same SQLite file.

Then implement `SQLiteHumanLoopStore` using the Python standard library `sqlite3`. Keep serialization explicit and versioned so later Postgres support can reuse the same boundaries.

Verification:

```bash
uv run pytest tests/test_hlp_sdk.py::test_sqlite_store_persists_hlp_state_across_restart -q
```

## Task 5: End-to-End Demo

Write a failing test that runs the demo function without external credentials. The demo must return a structured result containing:

- `task_id`
- `run_id`
- checkpoint decision
- final artifact id and version
- approved review id
- ledger status
- audit action list

Then implement `examples/hlp_e2e_demo.py` with a deterministic fake agent adapter. Add a console script so users can run:

```bash
uv run loops-hlp-demo
```

Verification:

```bash
uv run loops-hlp-demo
uv run pytest tests/test_hlp_sdk.py::test_hlp_e2e_demo_runs_without_external_services -q
```

## Task 6: Documentation and Public Surface

Update README and architecture docs to describe HLP as the public SDK for human responsibility loops. Keep L0/L1 as referenced protocol/runtime layers rather than first-class project focus.

Verification:

```bash
uv run pytest -q
```

## Task 7: Real Adapter Execution Contracts

Extend adapter entry points beyond naming wrappers:

- `ProcessAgentAdapter` executes a JSON-over-stdin/stdout runner and wraps process failures in `AgentAdapterError`.
- `CodexCLIAdapter`, `ClaudeCodeCLIAdapter`, and `HermsCLIAdapter` accept command, runner, and timeout parameters.
- `OpenAIPythonSDKAdapter` accepts an injected OpenAI Python SDK client and calls `client.responses.create(...)`.
- `HLPClient` process adapter flows drive `delegate`, `block`, and `resume` through the runner during checkpoint lifecycles.

Verification:

```bash
uv run pytest tests/test_hlp_sdk.py::test_process_agent_adapter_executes_json_runner_contract -q
uv run pytest tests/test_hlp_sdk.py::test_process_agent_adapter_raises_structured_error_on_failure -q
uv run pytest tests/test_hlp_sdk.py::test_process_agent_adapter_wraps_runner_exception -q
uv run pytest tests/test_hlp_sdk.py::test_openai_python_sdk_adapter_uses_responses_client -q
uv run pytest tests/test_hlp_sdk.py::test_openai_python_sdk_adapter_wraps_client_exception -q
uv run pytest tests/test_hlp_sdk.py::test_hlp_client_drives_process_adapter_block_and_resume -q
```

## Acceptance Criteria

- `from loops.hlp import HLPClient` is the preferred SDK entry point.
- A deterministic e2e demo runs with no network, no credentials, and no optional framework dependency.
- The adapter contract can represent in-process frameworks and CLI/process agents.
- SQLite persistence proves restart-safe HLP state for the core objects used by the demo.
- Existing loop2 protocol tests still pass.
- Documentation clearly states that OpenAI Agents SDK, OpenAI Python SDK, Codex CLI, Claude Code, LangGraph/CrewAI, and unknown frameworks such as `herms` are adapter targets, not core dependencies.
- Process and OpenAI Python SDK adapters perform real delegated execution through injected runners or clients while preserving `task_id` correlation.
