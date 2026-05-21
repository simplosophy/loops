"""Core shell tool."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from loop0.policy import ApprovalRequest
from loop0.profiles import ToolProfile
from loop0.tools.base import BaseTool, ToolContext, ToolResult

_CONTROL_SPLIT_RE = re.compile(r"\|\||&&|;|\|")
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_COMMON_EXECUTABLE_DIRS = {
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
}


@dataclass
class ShellSession:
    session_id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int | None = None


class ShellProcessManager:
    """Tracks background shell sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ShellSession] = {}

    async def start(self, command: str, cwd: Path) -> ShellSession:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        session = ShellSession(session_id=f"sh_{uuid4().hex[:12]}", command=command, process=process)
        self._sessions[session.session_id] = session
        asyncio.create_task(self._read_stream(session, process.stdout, session.stdout), name=f"{session.session_id}_stdout")
        asyncio.create_task(self._read_stream(session, process.stderr, session.stderr), name=f"{session.session_id}_stderr")
        asyncio.create_task(self._watch(session), name=f"{session.session_id}_watch")
        return session

    async def _read_stream(self, session: ShellSession, stream: Any, sink: list[str]) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            sink.append(chunk.decode("utf-8", errors="replace"))

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
        entries = [*[(line, "stdout") for line in session.stdout], *[(line, "stderr") for line in session.stderr]]
        sliced = entries[max(offset, 0) : max(offset, 0) + max(limit, 1)]
        return {
            "session_id": session_id,
            "offset": offset,
            "next_offset": max(offset, 0) + len(sliced),
            "lines": [{"stream": stream, "text": text} for text, stream in sliced],
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
            session.process.kill()
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
            "Operations: run, poll, log, write, kill."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["run", "poll", "log", "write", "kill"]},
                "command": {"type": "string"},
                "background": {"type": "boolean", "default": False},
                "session_id": {"type": "string"},
                "timeout_seconds": {"type": "number"},
                "max_output_chars": {"type": "integer"},
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
        command = str(args.get("command") or "").strip()
        if not command:
            return ToolResult.failure("shell.run requires command", status="invalid_args", op="run")

        valid, reason = self._validate_command(command)
        if not valid:
            return ToolResult.failure(f"Blocked: {reason}", status="blocked", op="run", command=command)

        background = bool(args.get("background", False))
        external_paths = self._external_paths(command, ctx.workspace)
        if external_paths and ctx.policy.shell_external_path_policy == "deny":
            return ToolResult.failure(
                "Blocked: Shell command references paths outside the workspace: " + ", ".join(external_paths),
                status="blocked",
                op="run",
                command=command,
                external_paths=external_paths,
            )

        approval_reason = self._approval_reason(command, ctx, background=background, external_paths=external_paths)
        if approval_reason:
            approved = await ctx.request_approval(
                ApprovalRequest(
                    reason=approval_reason,
                    tool_name=self.profile.name,
                    risk="high" if background else "medium",
                    metadata={"command": command, "background": background},
                )
            )
            if not approved:
                return ToolResult.failure(
                    f"Blocked: {approval_reason}",
                    status="blocked",
                    op="run",
                    command=command,
                    background=background,
                )

        workspace = ctx.workspace.expanduser().resolve(strict=False)
        workspace.mkdir(parents=True, exist_ok=True)

        if background:
            session = await self.process_manager.start(command, workspace)
            return self._json_result(
                {"session_id": session.session_id, "status": "started", "command": command},
                op="run",
                command=command,
                background=True,
                cwd=str(workspace),
                session_id=session.session_id,
            )

        timeout = float(args.get("timeout_seconds") or ctx.policy.shell_timeout_seconds)
        max_chars = int(args.get("max_output_chars") or ctx.policy.shell_max_output_chars)
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_raw, stderr_raw = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            return ToolResult.failure(
                f"Command timed out after {timeout:g} seconds",
                status="timeout",
                op="run",
                command=command,
                background=False,
                cwd=str(workspace),
                timeout_seconds=timeout,
            )

        stdout = stdout_raw.decode("utf-8", errors="replace")
        stderr = stderr_raw.decode("utf-8", errors="replace")
        output = _format_command_output(stdout, stderr, process.returncode, max_chars=max_chars)
        metadata = {
            "op": "run",
            "command": command,
            "background": False,
            "cwd": str(workspace),
            "timeout_seconds": timeout,
            "returncode": process.returncode,
            "stdout_chars": len(stdout),
            "stderr_chars": len(stderr),
        }
        if process.returncode == 0:
            return ToolResult.success(output, **metadata)
        return ToolResult.failure(
            output or f"Command failed with exit code {process.returncode}",
            **metadata,
        )

    def _approval_reason(
        self,
        command: str,
        ctx: ToolContext,
        *,
        background: bool,
        external_paths: list[str],
    ) -> str | None:
        del command
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
    def _external_paths(command: str, workspace: Path) -> list[str]:
        workspace_resolved = workspace.expanduser().resolve(strict=False)
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
                    resolved = path if path.is_absolute() else workspace_resolved / path
                    resolved = resolved.resolve(strict=False)
                    try:
                        resolved.relative_to(workspace_resolved)
                    except ValueError:
                        paths.append(str(resolved))
        except ValueError:
            return []
        return sorted(set(paths))

    @staticmethod
    def _json_result(payload: dict[str, Any], **metadata: Any) -> ToolResult:
        import json

        return ToolResult.success(json.dumps(payload, ensure_ascii=False, sort_keys=True), **metadata)


def _required(args: dict[str, Any], name: str) -> str:
    value = str(args.get(name) or "").strip()
    if not value:
        raise ValueError(f"shell op requires {name}")
    return value


def _looks_like_path(token: str) -> bool:
    if not token or token.startswith("-") or _URI_RE.match(token):
        return False
    return token in {".", "..", "~"} or token.startswith(("/", "./", "../", "~/"))


def _format_command_output(stdout: str, stderr: str, returncode: int | None, *, max_chars: int) -> str:
    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append("[stderr]\n" + stderr)
    text = "\n".join(part.rstrip("\n") for part in parts if part)
    if returncode not in (0, None) and not text:
        text = f"Command failed with exit code {returncode}"
    if len(text) > max_chars:
        return text[:max_chars].rstrip("\n") + "\n... [output truncated]"
    return text
