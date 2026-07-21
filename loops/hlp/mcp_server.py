"""L1 spike: HLP as MCP server (stdio, newline-delimited JSON-RPC 2.0).

Exposes HLP operations as MCP tools so any MCP-capable harness can project
human-loop events natively — no per-CLI output parsing required. This spike
covers the projection direction (harness → HLP) with three tools:

- ``hlp_checkpoint_raise`` — agent raises a decision checkpoint (needs_approval /
  needs_choice / needs_input as kind=approval/choice/input).
- ``hlp_artifact_commit`` — agent delivers an artifact (review_ready).
- ``hlp_inbox`` — poll the human inbox for resolutions (HLP → harness).

Protocol: stdio MCP, one JSON-RPC message per line. `initialize`,
`notifications/initialized`, `tools/list`, `tools/call`, `ping`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from .objects import ArtifactPayload, CheckpointOption
from .operations import HumanLoopOperations
from .schema import to_wire
from .sdk import HLPClient
from .store import HumanLoopStore

_SERVER_INFO = {
    "name": "loops-hlp-mcp",
    "version": "0.3.0",
}
_PROTOCOL_VERSION = "2024-11-05"

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "hlp_task_create",
        "description": "Create an HLP task (state=created) for a human principal.",
        "inputSchema": {
            "type": "object",
            "required": ["principal", "goal"],
            "properties": {
                "principal": {"type": "string"},
                "goal": {"type": "string"},
            },
        },
    },
    {
        "name": "hlp_task_assign",
        "description": "Assign an HLP task to an agent (created -> assigned).",
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "agent_id"],
            "properties": {
                "task_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
        },
    },
    {
        "name": "hlp_task_start",
        "description": "Mark an assigned HLP task in progress (assigned -> in_progress).",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {"task_id": {"type": "string"}},
        },
    },
    {
        "name": "hlp_checkpoint_raise",
        "description": (
            "Raise an HLP decision checkpoint (blocks the task until a human "
            "resolves it). kind: approval | choice | input."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "kind", "prompt"],
            "properties": {
                "task_id": {"type": "string"},
                "kind": {"type": "string", "enum": ["approval", "choice", "input"]},
                "prompt": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "label"],
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                    },
                },
                "raised_by": {"type": "string"},
            },
        },
    },
    {
        "name": "hlp_artifact_commit",
        "description": "Commit a deliverable artifact to HLP (moves the task to review_ready).",
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "type", "uri", "checksum"],
            "properties": {
                "task_id": {"type": "string"},
                "type": {"type": "string"},
                "uri": {"type": "string"},
                "checksum": {"type": "string"},
                "size": {"type": "integer"},
                "produced_by": {"type": "string"},
            },
        },
    },
    {
        "name": "hlp_inbox",
        "description": "Poll the HLP human inbox for a principal (pending checkpoints and reviews).",
        "inputSchema": {
            "type": "object",
            "required": ["principal"],
            "properties": {"principal": {"type": "string"}},
        },
    },
]


def _text(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


class HlpMcpServer:
    def __init__(self, operations: HumanLoopOperations) -> None:
        self.operations = operations
        self.client = HLPClient(store=operations.store, adapter=operations.adapter)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ops = self.operations
        if name == "hlp_task_create":
            task = await ops.task_create(
                principal=arguments["principal"],
                goal=arguments["goal"],
            )
            return {"task_id": task.id, "state": task.state}
        if name == "hlp_task_assign":
            task = await ops.task_assign(
                arguments["task_id"],
                arguments["agent_id"],
            )
            return {"task_id": task.id, "state": task.state}
        if name == "hlp_task_start":
            task = await ops.task_start(arguments["task_id"])
            return {"task_id": task.id, "state": task.state}
        if name == "hlp_checkpoint_raise":
            options = tuple(CheckpointOption(**option) for option in arguments.get("options") or ())
            checkpoint = await ops.checkpoint_raise(
                task_id=arguments["task_id"],
                kind=arguments["kind"],
                prompt=arguments["prompt"],
                options=options,
                raised_by=arguments.get("raised_by") or "agent",
            )
            return {"checkpoint_id": checkpoint.id, "state": checkpoint.state}
        if name == "hlp_artifact_commit":
            artifact = await ops.artifact_commit(
                task_id=arguments["task_id"],
                type=arguments["type"],
                payload=ArtifactPayload(
                    kind="ref",
                    uri=arguments["uri"],
                    checksum=arguments["checksum"],
                    size=int(arguments.get("size", 0)),
                ),
                produced_by=arguments.get("produced_by") or "agent",
            )
            return {"artifact_id": artifact.id, "version": artifact.version}
        if name == "hlp_inbox":
            items = await self.client.human_inbox(arguments["principal"])
            return to_wire(items)
        raise ValueError(f"unknown tool: {name}")


async def _dispatch(server: HlpMcpServer, message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "notifications/initialized" or method is None:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": _SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = await server.call_tool(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": _text(result)}
        except Exception as exc:  # noqa: BLE001 - spike: surface as MCP error result
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True},
            }
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


async def _serve(operations: HumanLoopOperations) -> None:
    server = HlpMcpServer(operations)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    writer_transport, writer_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)

    while True:
        line = await reader.readline()
        if not line:
            return
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = await _dispatch(server, message)
        if response is not None:
            writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()


def main() -> None:

    operations = HumanLoopOperations(store=HumanLoopStore())
    asyncio.run(_serve(operations))


if __name__ == "__main__":
    main()
