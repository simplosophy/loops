"""Core shell tool."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shlex
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from loops.loop0.policy import ApprovalRequest
from loops.loop0.profiles import ToolProfile
from loops.loop0.tools.base import BaseTool, ToolContext, ToolResult

_CONTROL_SPLIT_RE = re.compile(r"\|\||&&|;|\||\n")
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_COMMON_EXECUTABLE_DIRS = {
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
}


@dataclass(frozen=True)
class ShellCommandOutcome:
    """Terminal condition for a foreground shell command."""

    type: str = "exit"
    exit_code: int | None = None


@dataclass(frozen=True)
class ShellCommandOutput:
    """Structured stdout/stderr result for one foreground command."""

    command: str
    stdout: str = ""
    stderr: str = ""
    outcome: ShellCommandOutcome = field(default_factory=ShellCommandOutcome)

    @property
    def exit_code(self) -> int | None:
        return self.outcome.exit_code

    @property
    def status(self) -> str:
        return "timeout" if self.outcome.type == "timeout" else "completed"

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "status": self.status,
            "outcome": {"type": self.outcome.type},
        }
        if self.outcome.type == "exit":
            payload["outcome"]["exit_code"] = self.outcome.exit_code
            if self.outcome.exit_code is not None:
                payload["exit_code"] = self.outcome.exit_code
        return payload


@dataclass(frozen=True)
class ShellLogEntry:
    index: int
    stream: str
    text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ShellSession:
    session_id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    log_entries: list[ShellLogEntry] = field(default_factory=list)
    returncode: int | None = None


class ShellProcessManager:
    """Tracks background shell sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ShellSession] = {}

    async def start(self, command: str, cwd: Path, *, env: dict[str, str] | None = None) -> ShellSession:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            env=_merged_env(env),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        session = ShellSession(session_id=f"sh_{uuid4().hex[:12]}", command=command, process=process)
        self._sessions[session.session_id] = session
        asyncio.create_task(
            self._read_stream(session, process.stdout, session.stdout, stream_name="stdout"),
            name=f"{session.session_id}_stdout",
        )
        asyncio.create_task(
            self._read_stream(session, process.stderr, session.stderr, stream_name="stderr"),
            name=f"{session.session_id}_stderr",
        )
        asyncio.create_task(self._watch(session), name=f"{session.session_id}_watch")
        return session

    async def _read_stream(self, session: ShellSession, stream: Any, sink: list[str], *, stream_name: str) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            sink.append(text)
            session.log_entries.append(
                ShellLogEntry(index=len(session.log_entries), stream=stream_name, text=text)
            )

    async def _watch(self, session: ShellSession) -> None:
        session.returncode = await session.process.wait()
        session.completed_at = datetime.now(timezone.utc)

    def get(self, session_id: str) -> ShellSession | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict[str, Any]]:
        return [self._session_dict(session) for session in self._sessions.values()]

    def poll(self, session_id: str) -> dict[str, Any]:
        session = self._require(session_id)
        if session.process.returncode is not None:
            session.returncode = session.process.returncode
            session.completed_at = session.completed_at or datetime.now(timezone.utc)
        return self._session_dict(session)

    def log(self, session_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        session = self._require(session_id)
        normalized_offset = max(offset, 0)
        normalized_limit = max(limit, 1)
        entries = session.log_entries
        sliced = entries[normalized_offset : normalized_offset + normalized_limit]
        return {
            "session_id": session_id,
            "offset": normalized_offset,
            "next_offset": normalized_offset + len(sliced),
            "total": len(entries),
            "lines": [
                {
                    "index": entry.index,
                    "stream": entry.stream,
                    "text": entry.text,
                    "created_at": entry.created_at.isoformat(),
                }
                for entry in sliced
            ],
        }

    async def write(self, session_id: str, data: str, *, eof: bool = False) -> dict[str, Any]:
        session = self._require(session_id)
        if session.process.stdin is None:
            raise ValueError("Session stdin is not available")
        payload = data.encode("utf-8")
        session.process.stdin.write(payload)
        await session.process.stdin.drain()
        if eof:
            session.process.stdin.close()
        return {"session_id": session_id, "bytes_written": len(payload), "eof": eof}

    async def kill(self, session_id: str) -> dict[str, Any]:
        session = self._require(session_id)
        if session.process.returncode is None:
            _kill_process_tree(session.process)
            await session.process.wait()
        session.returncode = session.process.returncode
        session.completed_at = session.completed_at or datetime.now(timezone.utc)
        return self._session_dict(session)

    def _require(self, session_id: str) -> ShellSession:
        session = self.get(session_id)
        if session is None:
            raise ValueError(f"Unknown shell session: {session_id}")
        return session

    @staticmethod
    def _session_dict(session: ShellSession) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "command": session.command,
            "running": session.process.returncode is None and session.returncode is None,
            "returncode": session.returncode if session.returncode is not None else session.process.returncode,
            "started_at": session.started_at.isoformat(),
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        }


class ShellTool(BaseTool):
    """The only core tool: shell execution and shell session control."""

    def __init__(self, *, process_manager: ShellProcessManager | None = None) -> None:
        self.process_manager = process_manager or ShellProcessManager()

    profile = ToolProfile(
        name="shell",
        description=(
            "Execute shell commands or manage background shell sessions. "
            "Operations: run, list, poll, log, write, kill."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["run", "list", "poll", "log", "write", "kill"]},
                "command": {"type": "string"},
                "commands": {"type": "array", "items": {"type": "string"}},
                "background": {"type": "boolean", "default": False},
                "session_id": {"type": "string"},
                "cwd": {"type": "string"},
                "working_directory": {"type": "string"},
                "env": {"type": "object", "additionalProperties": {"type": "string"}},
                "timeout_seconds": {"type": "number"},
                "timeout_ms": {"type": "number"},
                "max_output_chars": {"type": "integer"},
                "max_output_length": {"type": "integer"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
                "data": {"type": "string"},
                "eof": {"type": "boolean"},
            },
            "required": ["op"],
        },
        effects=frozenset({"process", "filesystem", "network"}),
        risk="medium",
        source="core",
        requires_approval=None,
    )

    async def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        op = str(args.get("op") or "run").strip().lower()
        if op == "run":
            return await self._run(ctx, args)
        if op == "list":
            return self._json_result({"sessions": self.process_manager.list()}, op=op)
        if op == "poll":
            session_id = _required(args, "session_id")
            return self._json_result(self.process_manager.poll(session_id), op=op, session_id=session_id)
        if op == "log":
            session_id = _required(args, "session_id")
            return self._json_result(
                self.process_manager.log(
                    session_id,
                    offset=int(args.get("offset", 0) or 0),
                    limit=int(args.get("limit", 100) or 100),
                ),
                op=op,
                session_id=session_id,
            )
        if op == "write":
            session_id = _required(args, "session_id")
            result = await self.process_manager.write(
                session_id,
                str(args.get("data") or ""),
                eof=bool(args.get("eof", False)),
            )
            return self._json_result(result, op=op, session_id=session_id)
        if op == "kill":
            session_id = _required(args, "session_id")
            return self._json_result(await self.process_manager.kill(session_id), op=op, session_id=session_id)
        return ToolResult.failure(f"Unknown shell op: {op}", status="invalid_args", op=op)

    async def _run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            commands = _coerce_commands(args)
            env = _coerce_env(args.get("env"))
            timeout = _coerce_timeout_seconds(args, default=ctx.policy.shell_timeout_seconds)
            max_chars = _coerce_max_output_chars(args, default=ctx.policy.shell_max_output_chars)
        except ValueError as exc:
            return ToolResult.failure(str(exc), status="invalid_args", op="run")

        for command in commands:
            valid, reason = self._validate_command(command)
            if not valid:
                return ToolResult.failure(f"Blocked: {reason}", status="blocked", op="run", command=command)

        background = bool(args.get("background", False))
        if background and len(commands) != 1:
            return ToolResult.failure(
                "shell.run background sessions require exactly one command",
                status="invalid_args",
                op="run",
                commands=list(commands),
            )

        workspace = ctx.workspace.expanduser().resolve(strict=False)
        workspace.mkdir(parents=True, exist_ok=True)
        cwd = _resolve_cwd(args, workspace)

        external_paths = []
        if not _is_relative_to(cwd, workspace):
            external_paths.append(str(cwd))
        for command in commands:
            external_paths.extend(self._external_paths(command, cwd, workspace))
        external_paths = sorted(set(external_paths))
        if external_paths and ctx.policy.shell_external_path_policy == "deny":
            return ToolResult.failure(
                "Blocked: Shell command references paths outside the workspace: " + ", ".join(external_paths),
                status="blocked",
                op="run",
                command=commands[0] if len(commands) == 1 else None,
                commands=list(commands),
                external_paths=external_paths,
            )

        approval_reason = self._approval_reason(
            commands,
            ctx,
            background=background,
            external_paths=external_paths,
        )
        if approval_reason:
            approved = await ctx.request_approval(
                ApprovalRequest(
                    reason=approval_reason,
                    tool_name=self.profile.name,
                    risk="high" if background else "medium",
                    metadata={
                        "command": commands[0] if len(commands) == 1 else None,
                        "commands": list(commands),
                        "background": background,
                        "cwd": str(cwd),
                    },
                )
            )
            if not approved:
                return ToolResult.failure(
                    f"Blocked: {approval_reason}",
                    status="blocked",
                    op="run",
                    command=commands[0] if len(commands) == 1 else None,
                    commands=list(commands),
                    background=background,
                )

        if not cwd.exists() or not cwd.is_dir():
            return ToolResult.failure(
                f"shell.run cwd does not exist or is not a directory: {cwd}",
                status="invalid_args",
                op="run",
                cwd=str(cwd),
            )

        if background:
            command = commands[0]
            session = await self.process_manager.start(command, cwd, env=env)
            return self._json_result(
                {"session_id": session.session_id, "status": "started", "command": command},
                op="run",
                command=command,
                background=True,
                cwd=str(cwd),
                session_id=session.session_id,
                env_keys=sorted(env) if env else [],
            )

        outputs: list[ShellCommandOutput] = []
        deadline = asyncio.get_running_loop().time() + timeout
        for command in commands:
            if ctx.check_cancelled():
                metadata = _run_metadata(
                    commands,
                    outputs,
                    background=False,
                    cwd=cwd,
                    timeout_seconds=timeout,
                    max_output_chars=max_chars,
                    env=env,
                )
                return ToolResult.failure("Command cancelled", status="cancelled", **metadata)

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                outputs.append(
                    ShellCommandOutput(command=command, outcome=ShellCommandOutcome(type="timeout"))
                )
            else:
                outputs.append(await _execute_command(command, cwd=cwd, env=env, timeout_seconds=remaining))

            latest = outputs[-1]
            if latest.status == "timeout" or latest.exit_code not in (0, None):
                break

        output = _render_command_outputs(outputs, max_chars=max_chars)
        metadata = _run_metadata(
            commands,
            outputs,
            background=False,
            cwd=cwd,
            timeout_seconds=timeout,
            max_output_chars=max_chars,
            env=env,
        )
        if all(entry.status != "timeout" and entry.exit_code in (0, None) for entry in outputs):
            return ToolResult.success(output, **metadata)

        status = "timeout" if any(entry.status == "timeout" for entry in outputs) else "error"
        return ToolResult.failure(
            output,
            status=status,
            **metadata,
        )

    def _approval_reason(
        self,
        commands: Sequence[str],
        ctx: ToolContext,
        *,
        background: bool,
        external_paths: list[str],
    ) -> str | None:
        del commands
        if background and ctx.policy.shell_require_approval_for_background:
            return "Background shell sessions require approval."
        if external_paths and ctx.policy.shell_external_path_policy == "ask":
            return "Shell command references paths outside the workspace: " + ", ".join(external_paths)
        return None

    @staticmethod
    def _validate_command(command: str) -> tuple[bool, str]:
        blocked_commands = {
            "sudo",
            "su",
            "doas",
            "pkexec",
            "dd",
            "mkfs",
            "fdisk",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            "chmod",
            "chown",
            "mount",
            "umount",
        }
        blocked_patterns = [
            r"rm\s+.*--no-preserve-root",
            r"rm\s+-rf\s+/\s*$",
            r":\(\)",
            r"curl\s+.*\|\s*(?:sh|bash|zsh)",
            r"wget\s+.*\|\s*(?:sh|bash|zsh)",
        ]
        for pattern in blocked_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False, "command matches a blocked security pattern"
        try:
            for segment in _CONTROL_SPLIT_RE.split(command):
                segment = segment.strip()
                if not segment or segment.startswith("#"):
                    continue
                tokens = shlex.split(segment)
                if not tokens:
                    continue
                base = Path(tokens[0]).name
                if base in blocked_commands:
                    return False, f"command '{base}' is blocked"
        except ValueError as exc:
            return False, f"command parse error: {exc}"
        return True, ""

    @staticmethod
    def _external_paths(command: str, cwd: Path, workspace: Path) -> list[str]:
        workspace_resolved = workspace.expanduser().resolve(strict=False)
        cwd_resolved = cwd.expanduser().resolve(strict=False)
        paths: list[str] = []
        try:
            for segment in _CONTROL_SPLIT_RE.split(command):
                tokens = shlex.split(segment)
                for index, token in enumerate(tokens):
                    if not _looks_like_path(token):
                        continue
                    path = Path(token).expanduser()
                    if index == 0 and path.parent.as_posix() in _COMMON_EXECUTABLE_DIRS:
                        continue
                    resolved = path if path.is_absolute() else cwd_resolved / path
                    resolved = resolved.resolve(strict=False)
                    if not _is_relative_to(resolved, workspace_resolved):
                        paths.append(str(resolved))
        except ValueError:
            return []
        return sorted(set(paths))

    @staticmethod
    def _json_result(payload: dict[str, Any], **metadata: Any) -> ToolResult:
        import json

        return ToolResult.success(json.dumps(payload, ensure_ascii=False, sort_keys=True), **metadata)


async def _execute_command(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout_seconds: float,
) -> ShellCommandOutput:
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        env=_merged_env(env),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        return ShellCommandOutput(
            command=command,
            stdout=stdout_raw.decode("utf-8", errors="replace"),
            stderr=stderr_raw.decode("utf-8", errors="replace"),
            outcome=ShellCommandOutcome(type="exit", exit_code=process.returncode),
        )
    except TimeoutError:
        _kill_process_tree(process)
        stdout_raw, stderr_raw = await process.communicate()
        return ShellCommandOutput(
            command=command,
            stdout=stdout_raw.decode("utf-8", errors="replace"),
            stderr=stderr_raw.decode("utf-8", errors="replace"),
            outcome=ShellCommandOutcome(type="timeout"),
        )


def _run_metadata(
    commands: Sequence[str],
    outputs: Sequence[ShellCommandOutput],
    *,
    background: bool,
    cwd: Path,
    timeout_seconds: float,
    max_output_chars: int,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "op": "run",
        "command": commands[0] if len(commands) == 1 else None,
        "commands": list(commands),
        "command_count": len(commands),
        "background": background,
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "max_output_chars": max_output_chars,
        "returncode": outputs[-1].exit_code if outputs else None,
        "stdout_chars": sum(len(output.stdout) for output in outputs),
        "stderr_chars": sum(len(output.stderr) for output in outputs),
        "outputs": [output.as_payload() for output in outputs],
    }
    if env:
        metadata["env_keys"] = sorted(env)
    return metadata


def _coerce_commands(args: dict[str, Any]) -> tuple[str, ...]:
    commands_value = _first_present(args, "commands")
    if commands_value is not None:
        if isinstance(commands_value, (str, bytes, bytearray)) or not isinstance(commands_value, Sequence):
            raise ValueError("shell.run commands must be a sequence of command strings")
        normalized: list[str] = []
        for command in commands_value:
            if command is None:
                continue
            text = str(command).strip()
            if text:
                normalized.append(text)
        commands = tuple(normalized)
    else:
        command = str(args.get("command") or "").strip()
        commands = (command,) if command else ()
    if not commands:
        raise ValueError("shell.run requires command or commands")
    return commands


def _coerce_env(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("shell.run env must be an object")
    env: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if not key:
            raise ValueError("shell.run env keys must be non-empty")
        if raw_value is None:
            continue
        env[key] = str(raw_value)
    return env


def _coerce_timeout_seconds(args: dict[str, Any], *, default: float) -> float:
    value = _first_present(args, "timeout_seconds")
    if value is not None:
        timeout = float(value)
    else:
        timeout_ms = _first_present(args, "timeout_ms", "timeoutMs")
        timeout = float(timeout_ms) / 1000 if timeout_ms is not None else float(default)
    if timeout <= 0:
        raise ValueError("shell.run timeout must be greater than zero")
    return timeout


def _coerce_max_output_chars(args: dict[str, Any], *, default: int) -> int:
    value = _first_present(args, "max_output_chars", "max_output_length", "maxOutputLength")
    if value is None:
        return max(0, int(default))
    return max(0, int(value))


def _resolve_cwd(args: dict[str, Any], workspace: Path) -> Path:
    raw = _first_present(args, "cwd", "working_directory", "workingDirectory")
    if raw is None or str(raw).strip() == "":
        return workspace
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = workspace / path
    return path.resolve(strict=False)


def _first_present(args: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in args and args[name] is not None:
            return args[name]
    return None


def _merged_env(env: dict[str, str] | None) -> dict[str, str] | None:
    if not env:
        return None
    merged = os.environ.copy()
    merged.update(env)
    return merged


def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if hasattr(os, "killpg"):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
            return
    with contextlib.suppress(ProcessLookupError):
        process.kill()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _render_command_outputs(outputs: Sequence[ShellCommandOutput], *, max_chars: int) -> str:
    if not outputs:
        return "(no output)"
    if max_chars <= 0:
        return ""
    include_command = len(outputs) > 1
    text = "\n\n".join(_render_command_output(output, include_command=include_command) for output in outputs)
    if len(text) > max_chars:
        return text[:max_chars].rstrip("\n") + "\n... [output truncated]"
    return text


def _render_command_output(output: ShellCommandOutput, *, include_command: bool) -> str:
    lines: list[str] = []
    if include_command:
        lines.append(f"$ {output.command}")

    stdout = output.stdout.rstrip("\n")
    stderr = output.stderr.rstrip("\n")
    if stdout:
        lines.append(stdout)
    if stderr:
        if stdout:
            lines.append("")
        lines.append("stderr:")
        lines.append(stderr)
    if output.exit_code not in (None, 0):
        lines.append(f"exit code: {output.exit_code}")
    if output.status == "timeout":
        lines.append("status: timeout")

    text = "\n".join(lines).strip()
    return text if text else "(no output)"


def _required(args: dict[str, Any], name: str) -> str:
    value = str(args.get(name) or "").strip()
    if not value:
        raise ValueError(f"shell op requires {name}")
    return value


def _looks_like_path(token: str) -> bool:
    if not token or token.startswith("-") or _URI_RE.match(token):
        return False
    return token in {".", "..", "~"} or token.startswith(("/", "./", "../", "~/"))
