from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..objects import AdapterOperationContext
from ..schema import to_wire
from . import _parsing as parsing
from . import _util as util
from .fake import FakeAgentAdapter
from .protocol import (
    AgentAdapterError,
    AgentRunHandle,
    ProcessResult,
    ProcessRunner,
)

StreamChunkKind = Literal["status", "text", "thinking", "error", "raw"]
StreamLineCallback = Callable[[str], Awaitable[None] | None]
StreamChunkCallback = Callable[["StreamChunk"], Awaitable[None] | None]


@dataclass(frozen=True)
class StreamChunk:
    """A compact, host-ready slice of harness process output."""

    kind: StreamChunkKind
    text: str
    newline: bool = True


async def run_json_process(
    command: tuple[str, ...],
    request: dict[str, Any],
    timeout: float,
) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    payload = json.dumps(request, sort_keys=True).encode()
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(payload),
            timeout=timeout,
        )
    except TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return ProcessResult(
            exit_code=124,
            stdout=stdout.decode(errors="replace"),
            stderr=(stderr.decode(errors="replace") + "\nprocess timed out").strip(),
        )
    return ProcessResult(
        exit_code=process.returncode or 0,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


async def run_prompt_process(
    command: tuple[str, ...],
    request: dict[str, Any],
    timeout: float,
) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return ProcessResult(
            exit_code=124,
            stdout=stdout.decode(errors="replace"),
            stderr=(stderr.decode(errors="replace") + "\nprocess timed out").strip(),
        )
    return ProcessResult(
        exit_code=process.returncode or 0,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


def format_harness_stream_line(line: str) -> StreamChunk | None:
    """Map a raw harness stdout/stderr line into a compact TUI stream chunk.

    Suppresses high-frequency Pi ``thinking_delta`` noise while keeping status
    milestones and assistant ``text_delta`` fragments for live display.
    """
    stripped = line.strip()
    if not stripped:
        return None
    if not stripped.startswith("{"):
        text = stripped if len(stripped) <= 240 else stripped[:237] + "..."
        return StreamChunk(kind="raw", text=text)

    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        text = stripped if len(stripped) <= 240 else stripped[:237] + "..."
        return StreamChunk(kind="raw", text=text)
    if not isinstance(event, dict):
        return None

    event_type = str(event.get("type") or "")
    if event_type in {"session", "message_start", "message_end"}:
        return None
    if event_type in {"agent_start", "turn_start", "turn.started"}:
        return StreamChunk(kind="status", text=event_type.replace("_", " ").replace(".", " "))
    if event_type in {"agent_end", "turn_end", "turn.completed", "turn.failed"}:
        return StreamChunk(kind="status", text=event_type.replace("_", " ").replace(".", " "))
    if event_type == "error" or event.get("error"):
        message = event.get("message") or event.get("error")
        if isinstance(message, dict):
            message = message.get("message") or message
        return StreamChunk(kind="error", text=str(message or stripped)[:240])

    if event_type == "message_update":
        ame = event.get("assistantMessageEvent")
        if not isinstance(ame, dict):
            return None
        ame_type = str(ame.get("type") or "")
        if ame_type == "text_delta":
            delta = str(ame.get("delta") or "")
            if not delta:
                return None
            return StreamChunk(kind="text", text=delta, newline=False)
        if ame_type == "text_start":
            return StreamChunk(kind="status", text="assistant text")
        if ame_type == "text_end":
            content = str(ame.get("content") or "").strip()
            if content and len(content) <= 200:
                return StreamChunk(kind="status", text="text complete")
            return None
        if ame_type == "thinking_start":
            return StreamChunk(kind="thinking", text="thinking…")
        if ame_type in {"thinking_delta", "thinking_end"}:
            return None
        return None

    # Kimi stream-json: role-shaped lines (assistant reply + meta noise)
    role = str(event.get("role") or "")
    if role == "assistant":
        reply = event.get("content")
        if isinstance(reply, str) and reply:
            return StreamChunk(kind="text", text=reply, newline=False)
        return None
    if role == "meta":
        return None

    # Claude Code stream-json: system / assistant / result envelopes
    if event_type == "system":
        return None
    if event_type == "assistant":
        message = event.get("message")
        if not isinstance(message, dict):
            return None
        texts: list[str] = []
        thinking = False
        for block in message.get("content") or ():
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "text":
                texts.append(str(block.get("text") or ""))
            elif block_type == "thinking":
                thinking = True
        text = "".join(texts)
        if text:
            return StreamChunk(kind="text", text=text, newline=False)
        if thinking:
            return StreamChunk(kind="thinking", text="thinking…")
        return None
    if event_type == "result":
        if event.get("is_error"):
            return StreamChunk(
                kind="error",
                text=str(event.get("result") or "claude result error")[:240],
            )
        return None

    # Codex / HLP-style JSONL events
    if (
        event_type.startswith("hlp.")
        or event_type.startswith("pi.")
        or event_type
        in {
            "needs_approval",
            "needs_choice",
            "needs_input",
            "artifact",
            "item.completed",
            "thread.started",
        }
    ):
        kind = event_type
        prompt = ""
        for key in ("hlp", "pi", "human_loop"):
            nested = event.get(key)
            if isinstance(nested, dict):
                kind = str(nested.get("kind") or kind)
                prompt = str(nested.get("prompt") or nested.get("summary") or "")
                break
        if event.get("item") and isinstance(event["item"], dict):
            prompt = str(event["item"].get("message") or prompt)
        label = f"{kind}" + (f": {prompt}" if prompt else "")
        return StreamChunk(kind="status", text=label[:240])

    # Final-ish payloads with summary
    summary = event.get("summary")
    if isinstance(summary, str) and summary.strip():
        return StreamChunk(kind="status", text=f"summary: {summary.strip()[:200]}")
    return None


async def _emit_stream_chunk(
    chunk: StreamChunk,
    *,
    on_chunk: StreamChunkCallback | None,
    on_line: StreamLineCallback | None,
) -> None:
    if on_chunk is not None:
        result = on_chunk(chunk)
        if inspect.isawaitable(result):
            await result
        return
    if on_line is None:
        return
    if chunk.kind == "text" and not chunk.newline:
        text = chunk.text
    elif chunk.kind == "text":
        text = chunk.text
    elif chunk.kind == "thinking":
        text = f"⋯ {chunk.text}"
    elif chunk.kind == "error":
        text = f"⋯ error: {chunk.text}"
    else:
        text = f"⋯ {chunk.text}"
    result = on_line(text if chunk.newline else text)
    if inspect.isawaitable(result):
        await result


async def run_prompt_process_streaming(
    command: tuple[str, ...],
    request: dict[str, Any],
    timeout: float,
    *,
    on_chunk: StreamChunkCallback | None = None,
    on_line: StreamLineCallback | None = None,
    on_stderr_line: StreamLineCallback | None = None,
) -> ProcessResult:
    """Run a prompt CLI while streaming stdout/stderr lines to host callbacks.

    Collects full stdout/stderr for the usual parse path so adapters keep
    identical post-run semantics (process_results / projection).
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    async def _read_stream(
        stream: asyncio.StreamReader | None,
        *,
        sink: list[str],
        is_stderr: bool = False,
    ) -> None:
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                break
            text = raw.decode(errors="replace")
            sink.append(text)
            line = text.rstrip("\n")
            if is_stderr:
                cb = on_stderr_line or on_line
                if cb is not None and line.strip():
                    result = cb(f"⋯ stderr: {line.strip()[:240]}")
                    if inspect.isawaitable(result):
                        await result
                continue
            chunk = format_harness_stream_line(line)
            if chunk is not None:
                await _emit_stream_chunk(chunk, on_chunk=on_chunk, on_line=on_line)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(process.stdout, sink=stdout_parts),
                _read_stream(process.stderr, sink=stderr_parts, is_stderr=True),
                process.wait(),
            ),
            timeout=timeout,
        )
    except TimeoutError:
        process.kill()
        try:
            await process.wait()
        except Exception:
            pass
        # Drain remaining buffers if any.
        if process.stdout is not None:
            rest = await process.stdout.read()
            if rest:
                stdout_parts.append(rest.decode(errors="replace"))
        if process.stderr is not None:
            rest = await process.stderr.read()
            if rest:
                stderr_parts.append(rest.decode(errors="replace"))
        return ProcessResult(
            exit_code=124,
            stdout="".join(stdout_parts),
            stderr=("".join(stderr_parts) + "\nprocess timed out").strip(),
        )
    return ProcessResult(
        exit_code=process.returncode or 0,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
    )


def make_streaming_prompt_runner(
    *,
    on_chunk: StreamChunkCallback | None = None,
    on_line: StreamLineCallback | None = None,
    on_stderr_line: StreamLineCallback | None = None,
) -> ProcessRunner:
    """Build a ProcessRunner that streams harness output to host callbacks."""

    async def runner(
        command: tuple[str, ...],
        request: dict[str, Any],
        timeout: float,
    ) -> ProcessResult:
        return await run_prompt_process_streaming(
            command,
            request,
            timeout,
            on_chunk=on_chunk,
            on_line=on_line,
            on_stderr_line=on_stderr_line,
        )

    return runner


def cli_operation_prompt(request: dict[str, Any]) -> str:
    """Protocol-mode prompt: full HLP operation envelope for adapter contracts."""
    return (
        "You are executing an HLP adapter operation.\n"
        "Return exactly one JSON object and no markdown. The JSON object must "
        "include correlation_id exactly as provided. For delegate, include a "
        "stable run_id string, status, and a short summary.\n\n"
        "HLP request:\n"
        f"{json.dumps(request, indent=2, sort_keys=True)}"
    )


def _user_message_from_request(request: dict[str, Any]) -> str:
    """Extract free-text user content from delegate input or steer amendment."""
    operation = str(request.get("operation") or "")
    if operation == "steer":
        amendment = request.get("amendment")
        if isinstance(amendment, dict):
            text = str(amendment.get("text") or amendment.get("message") or "").strip()
            if text:
                return text
        elif amendment is not None:
            text = str(getattr(amendment, "text", "") or amendment).strip()
            if text:
                return text

    raw_input = request.get("input")
    if isinstance(raw_input, dict):
        goal = str(
            raw_input.get("goal") or raw_input.get("message") or raw_input.get("prompt") or ""
        ).strip()
        if goal:
            return goal
        if raw_input:
            return json.dumps(raw_input, sort_keys=True)
    elif raw_input is not None:
        return str(raw_input).strip()
    return str(request.get("goal") or "Continue the task.").strip()


def chat_mode_prompt(request: dict[str, Any]) -> str:
    """Chat-oriented prompt for TUI/user free-text on prompt-CLI harnesses.

    Puts the user message first so coding agents behave like a chat turn, while
    still requiring a JSON (or JSONL) result that preserves HLP correlation.
    Used for ``delegate`` (first turn) and ``steer`` (follow-up turns via amend).
    """
    correlation = str(request.get("correlation_id") or request.get("task_id") or "")
    goal = _user_message_from_request(request)
    run_id = str(request.get("run_id") or "").strip()
    run_line = f"- run_id SHOULD stay: {run_id}\n" if run_id else ""

    return (
        f"{goal}\n"
        "\n"
        "---\n"
        "Human-loop session constraints (keep these; do not ignore the user message "
        "above):\n"
        f"- correlation_id MUST be exactly: {correlation}\n"
        f"{run_line}"
        "- Prefer one final JSON object (no markdown fences) with keys:\n"
        "  run_id (stable string), correlation_id, status, summary\n"
        "- Put your full reply text for the user in `summary`.\n"
        "- Optional JSONL human-loop events may use nested `hlp` or `pi` payloads "
        "with kind needs_approval / needs_choice / needs_input / artifact when a "
        "human decision or delivery is required.\n"
        "- Do not restate this entire protocol envelope as the user-facing answer.\n"
    )


def prompt_for_adapter_operation(
    request: dict[str, Any],
    *,
    mode: str = "protocol",
) -> str:
    """Select chat vs protocol prompt body for a harness operation request."""
    operation = str(request.get("operation") or "")
    if mode == "chat" and operation in {"delegate", "steer"}:
        return chat_mode_prompt(request)
    return cli_operation_prompt(request)


class ProcessAgentAdapter(FakeAgentAdapter):
    """Generic JSON-over-stdin/stdout adapter for CLI agents."""

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        name: str = "process",
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self.command = command
        self.name = name
        self.runner = runner or run_json_process
        self.timeout = timeout
        self.process_results: dict[str, dict[str, Any]] = {}

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        request = {
            "operation": "delegate",
            "task_id": task_id,
            "agent_id": agent_id,
            "capability": capability,
            "input": input,
            "parent_run": parent_run,
            "correlation_id": task_id,
        }
        if operation_context is not None:
            request["operation_context"] = to_wire(operation_context)
        payload = await self._execute("delegate", request)
        util.validate_correlation(payload, task_id, self.name, "delegate")
        if not payload.get("run_id"):
            raise AgentAdapterError(
                self.name,
                "delegate",
                "delegate response must include run_id",
                details={"payload": payload},
            )
        run_id = str(payload["run_id"])
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.process_results[run_id] = payload
        self.calls.append(
            (
                "delegate",
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "capability": capability,
                    "input": input,
                    "parent_run": parent_run,
                    "operation_context": (
                        to_wire(operation_context) if operation_context is not None else None
                    ),
                },
            )
        )
        return run_id

    async def block(
        self,
        run_id: str,
        checkpoint_id: str,
        reason: str,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "block", context=context)
        await self._execute(
            "block",
            {
                "operation": "block",
                "run_id": run_id,
                "checkpoint_id": checkpoint_id,
                "reason": reason,
                "correlation_id": handle.correlation_id,
                "operation_context": to_wire(context) if context is not None else None,
            },
        )
        await FakeAgentAdapter.block(self, run_id, checkpoint_id, reason, context=context)

    async def resume(
        self,
        run_id: str,
        resolution: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "resume", context=context)
        await self._execute(
            "resume",
            {
                "operation": "resume",
                "run_id": run_id,
                "resolution": resolution,
                "correlation_id": handle.correlation_id,
                "operation_context": to_wire(context) if context is not None else None,
            },
        )
        await FakeAgentAdapter.resume(self, run_id, resolution, context=context)

    async def steer(
        self,
        run_id: str,
        amendment: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "steer", context=context)
        amendment_payload = util.adapter_payload(amendment)
        payload = await self._execute(
            "steer",
            {
                "operation": "steer",
                "run_id": run_id,
                "amendment": amendment_payload,
                "correlation_id": handle.correlation_id,
                "operation_context": to_wire(context) if context is not None else None,
            },
        )
        # Follow-up chat turns (TUI amend → steer) must refresh process_results so
        # hosts do not keep showing the previous delegate summary.
        if isinstance(payload, dict):
            self.process_results[run_id] = payload
        await FakeAgentAdapter.steer(self, run_id, amendment_payload, context=context)

    async def handoff(
        self,
        run_id: str,
        to_agent: str,
        context: dict[str, Any],
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        current = self._require_run(run_id, "handoff", context=operation_context)
        payload = await self._execute(
            "handoff",
            {
                "operation": "handoff",
                "run_id": run_id,
                "to_agent": to_agent,
                "context": context,
                "correlation_id": current.correlation_id,
                **(
                    {"operation_context": to_wire(operation_context)}
                    if operation_context is not None
                    else {}
                ),
            },
        )
        util.validate_correlation(payload, current.correlation_id, self.name, "handoff")
        new_run_id = str(payload.get("run_id") or payload.get("to_run") or self._next_run_id())
        self._runs[new_run_id] = AgentRunHandle(
            run_id=new_run_id,
            task_id=current.task_id,
            agent_id=to_agent,
            correlation_id=current.correlation_id,
            capability=current.capability,
            parent_run=run_id,
        )
        self.process_results[new_run_id] = payload
        self.calls.append(
            (
                "handoff",
                {
                    "from_run": run_id,
                    "to_run": new_run_id,
                    "to_agent": to_agent,
                    "context": context,
                    "operation_context": (
                        to_wire(operation_context) if operation_context is not None else None
                    ),
                },
            )
        )
        return new_run_id

    async def cancel(
        self,
        run_id: str,
        reason: str,
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "cancel", context=operation_context)
        await self._execute(
            "cancel",
            {
                "operation": "cancel",
                "run_id": run_id,
                "reason": reason,
                "correlation_id": handle.correlation_id,
                **(
                    {"operation_context": to_wire(operation_context)}
                    if operation_context is not None
                    else {}
                ),
            },
        )
        await FakeAgentAdapter.cancel(
            self,
            run_id,
            reason,
            operation_context=operation_context,
        )

    async def healthcheck(self) -> dict[str, Any]:
        result = {
            "status": "ok",
            "adapter": self.name,
            "runs": len(self._runs),
            "command": self.command,
            "executable": self.command[0] if self.command else "",
            "timeout": self.timeout,
        }
        self.calls.append(("healthcheck", result))
        return result

    async def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.runner(self.command, request, self.timeout)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process runner raised an exception",
                details={
                    "command": self.command,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        if result.exit_code != 0:
            raise AgentAdapterError(
                self.name,
                operation,
                "process command failed",
                details={
                    "command": self.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        if not result.stdout.strip():
            return {}
        try:
            payload = parsing.parse_process_stdout(result.stdout)
        except ValueError as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout was not valid JSON",
                details={"stdout": result.stdout, "stderr": result.stderr},
            ) from exc
        if not isinstance(payload, dict):
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout JSON must be an object",
                details={"stdout": result.stdout},
            )
        return payload

    def _next_run_id(self) -> str:
        self._run_counter += 1
        return f"run_{self._run_counter:06d}"


class PromptCLIAdapter(ProcessAgentAdapter):
    """One-shot prompt adapter for local agent CLIs.

    Codex, Kimi, and Claude Code expose non-interactive prompt modes rather
    than HLP's generic JSON-over-stdin process contract. This adapter keeps the
    HLP boundary structured by embedding the operation request in the prompt and
    requiring the CLI to print a JSON result that carries the correlation id.

    ``prompt_mode``:
    - ``protocol`` (default): full HLP operation JSON envelope (adapter contracts)
    - ``chat``: user message first for TUI free-text; lifecycle ops stay protocol
    """

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        name: str = "prompt-cli",
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        prompt_mode: str = "protocol",
    ) -> None:
        super().__init__(
            command,
            name=name,
            runner=runner or run_prompt_process,
            timeout=timeout,
        )
        if prompt_mode not in {"protocol", "chat"}:
            raise ValueError(f"unsupported prompt_mode: {prompt_mode}")
        self.prompt_mode = prompt_mode

    async def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        prompt = prompt_for_adapter_operation(request, mode=self.prompt_mode)
        command = (*self.command, prompt)
        try:
            result = self.runner(command, request, self.timeout)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process runner raised an exception",
                details={
                    "command": command,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        if result.exit_code != 0:
            raise AgentAdapterError(
                self.name,
                operation,
                "process command failed",
                details={
                    "command": command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        if not result.stdout.strip():
            return {}
        try:
            payload = parsing.parse_cli_stdout(result.stdout)
        except ValueError as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout did not contain a JSON object",
                details={"stdout": result.stdout, "stderr": result.stderr},
            ) from exc
        if not isinstance(payload, dict):
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout JSON must be an object",
                details={"stdout": result.stdout},
            )
        return payload

    async def healthcheck(self) -> dict[str, Any]:
        result = await super().healthcheck()
        result["prompt_mode"] = True
        result["prompt_style"] = self.prompt_mode
        return result
