"""HLP HTTP reference transport binding (spec §7.1 open issue).

Stdlib-only reference binding: a thin HTTP/JSON layer over
``HumanLoopOperations``. The wire contract is the deliverable; production
deployments are expected to rebind with their own framework (the spec is
transport-agnostic by design).

Endpoints
---------

- ``POST /v1/ops/<object.verb>`` — all 23 protocol operations plus
  ``human.inbox``, ``pending.outbox``, ``checkpoints.expire_due``.
- ``GET /v1/events?after=<seq>`` — SSE stream of audit events (§3.9).
- ``GET /v1/version`` — spec/schema/profile versions (§6.4).
- ``GET /v1/health`` — liveness + adapter healthcheck.

Errors map ``ProtocolError`` codes to their §6.1 HTTP analogies with the
§6.2 error object as the body. Mutating operations require the
``X-HLP-Principal`` header; real authentication is deployment-side (§1.2).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..objects import (
    ArtifactPayload,
    CheckpointOption,
    Evidence,
    InputRef,
    ProposedAction,
    ReviewComment,
)
from ..operations import HumanLoopOperations
from ..schema import to_wire
from ..sdk import HLPClient
from ..types import (
    HLP_PROFILE,
    HLP_REALTIME_PROFILE,
    HLP_REALTIME_SPEC_VERSION,
    HLP_SCHEMA_VERSION,
    HLP_SPEC_VERSION,
    ProtocolError,
)

_ERROR_STATUS: dict[str, int] = {
    "INVALID_SPEC": 400,
    "PRECONDITION_FAILED": 412,
    "UNAUTHORIZED": 401,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "IMMUTABLE_VIOLATION": 409,
    "DEADLINE_EXCEEDED": 408,
    "CHECKPOINT_EXPIRED": 410,
    "VERSION_UNSUPPORTED": 409,
}

# Ops that read but never mutate; everything else requires X-HLP-Principal.
_READ_OPS = frozenset(
    {
        "task.get",
        "task.list",
        "artifact.get",
        "ledger.read",
        "ledger.history",
        "audit.query",
        "audit.replay",
        "human.inbox",
        "pending.outbox",
    }
)

_OP_PATH = re.compile(r"^/v1/ops/([a-z]+\.[a-z_]+)$")

# Actor binding per mutating op: these params are bound to X-HLP-Principal
# (the body value is ignored). Agent-attributed params (raised_by,
# produced_by, ledger.write's task-scoped by) are taken from the body as-is.
_ACTOR_BIND: dict[str, tuple[str, ...]] = {
    "task.create": ("principal",),
    "task.cancel": ("by",),
    "task.interrupt": ("by",),
    "task.amend": ("by",),
    "checkpoint.resolve": ("by",),
    "ownership.transfer": ("actor",),
    "ownership.delegate": ("actor",),
    "review.submit": ("reviewer",),
    "review.comment": ("by",),
}


def _options(values: Any) -> tuple[CheckpointOption, ...]:
    return tuple(CheckpointOption(**value) for value in values or ())


def _proposed_actions(values: Any) -> tuple[ProposedAction, ...]:
    return tuple(ProposedAction(**value) for value in values or ())


def _evidence(values: Any) -> tuple[Evidence, ...]:
    return tuple(Evidence(**value) for value in values or ())


def _inputs(values: Any) -> tuple[InputRef, ...]:
    return tuple(InputRef(**value) for value in values or ())


def _comments(values: Any) -> tuple[ReviewComment, ...]:
    return tuple(ReviewComment(**value) for value in values or ())


def _strings(values: Any) -> tuple[str, ...]:
    return tuple(str(value) for value in values or ())


def _payload(value: Any) -> ArtifactPayload:
    if not isinstance(value, dict):
        raise ProtocolError("INVALID_SPEC", "artifact payload must be an object")
    return ArtifactPayload(**value)


def _comment(value: Any) -> ReviewComment:
    if not isinstance(value, dict):
        raise ProtocolError("INVALID_SPEC", "review comment must be an object")
    return ReviewComment(**value)


def _now_param(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


# op -> (method name, param builders). Builders run on the wire value before
# dispatch; unlisted params pass through unchanged.
DispatchEntry = tuple[str, dict[str, Callable[[Any], Any]]]

_DISPATCH: dict[str, DispatchEntry] = {
    "task.create": (
        "task_create",
        {"acceptance_criteria": _strings, "inputs": _inputs},
    ),
    "task.assign": ("task_assign", {}),
    "task.start": ("task_start", {}),
    "task.cancel": ("task_cancel", {}),
    "task.interrupt": ("task_interrupt", {}),
    "task.amend": ("task_amend", {}),
    "task.get": ("task_get", {}),
    "task.list": ("task_list", {}),
    "checkpoint.raise": (
        "checkpoint_raise",
        {
            "options": _options,
            "proposed_actions": _proposed_actions,
            "context": _evidence,
        },
    ),
    "checkpoint.resolve": (
        "checkpoint_resolve",
        {"approved_actions": _strings, "denied_actions": _strings},
    ),
    "checkpoint.expire": ("checkpoint_expire", {}),
    "checkpoints.expire_due": ("expire_due_checkpoints", {"now": _now_param}),
    "ownership.transfer": ("ownership_transfer", {}),
    "ownership.delegate": ("ownership_delegate", {}),
    "review.submit": (
        "review_submit",
        {"comments": _comments, "requested_changes": _strings},
    ),
    "review.comment": ("review_comment", {"comment": _comment}),
    "artifact.commit": ("artifact_commit", {"payload": _payload}),
    "artifact.get": ("artifact_get", {}),
    "artifact.reference": ("artifact_reference", {}),
    "ledger.read": ("ledger_read", {}),
    "ledger.write": ("ledger_write", {}),
    "ledger.history": ("ledger_history", {}),
    "audit.query": ("audit_query", {}),
    "audit.replay": ("audit_replay", {}),
    "human.inbox": ("human_inbox", {}),
    "pending.outbox": ("pending_adapter_outbox", {}),
}


@dataclass
class HLPHttpServer:
    """Stdlib HTTP reference binding over HumanLoopOperations."""

    operations: HumanLoopOperations
    host: str = "127.0.0.1"
    port: int = 0
    ops_timeout: float = 60.0
    sse_poll_interval: float = 0.25
    sse_max_seconds: float = 30.0
    _httpd: ThreadingHTTPServer | None = field(default=None, init=False, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _loop_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _http_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _sdk_client: HLPClient | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Facade for the few methods that live on HLPClient (e.g. human_inbox).
        self._sdk_client = HLPClient(
            store=self.operations.store,
            adapter=self.operations.adapter,
        )

    @property
    def address(self) -> str:
        if self._httpd is None:
            raise RuntimeError("server not started")
        host, port = self._httpd.server_address[:2]
        if isinstance(host, bytes):
            host = host.decode()
        return f"http://{host}:{port}"

    def start(self) -> HLPHttpServer:
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, name="hlp-transport-loop", daemon=True
        )
        self._loop_thread.start()
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.daemon_threads = True
        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever, name="hlp-transport-http", daemon=True
        )
        self._http_thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None

    # ── internal API used by the request handler ──

    def run_op(self, coro: Any) -> Any:
        if self._loop is None:
            raise RuntimeError("server not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=self.ops_timeout)

    def audit_events_after(self, seq: int) -> list:
        return [event for event in self.operations.store.audit_log.all() if event.seq > seq]


def _make_handler(app: HLPHttpServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "HLPHttp/0.2"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib name
            pass  # quiet by default; hosts log upstream

        # ── helpers ──

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(to_wire(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: int, code: str, message: str, details: Any = None) -> None:
            self._send_json(
                status,
                {
                    "error": {
                        "code": code,
                        "message": message,
                        "details": details or {},
                        "retryable": code in {"CONFLICT", "DEADLINE_EXCEEDED"},
                    }
                },
            )

        def _send_protocol_error(self, exc: ProtocolError) -> None:
            status = _ERROR_STATUS.get(exc.code, 500)
            self._send_json(status, {"error": exc.to_dict()})

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError("INVALID_SPEC", "request body must be a JSON object") from exc
            if not isinstance(body, dict):
                raise ProtocolError("INVALID_SPEC", "request body must be a JSON object")
            return body

        # ── routes ──

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            try:
                if self.path == "/v1/health":
                    health: dict[str, Any] = {"status": "ok"}
                    adapter_healthcheck = getattr(app.operations.adapter, "healthcheck", None)
                    if callable(adapter_healthcheck):
                        health["adapter"] = app.run_op(adapter_healthcheck())
                    self._send_json(200, health)
                    return
                if self.path == "/v1/version":
                    self._send_json(
                        200,
                        {
                            "spec_version": HLP_SPEC_VERSION,
                            "schema_version": HLP_SCHEMA_VERSION,
                            "profile": HLP_PROFILE,
                            "realtime_spec_version": HLP_REALTIME_SPEC_VERSION,
                            "realtime_profile": HLP_REALTIME_PROFILE,
                        },
                    )
                    return
                if self.path.startswith("/v1/events"):
                    self._handle_events()
                    return
                self._send_error(404, "NOT_FOUND", f"unknown route: {self.path}")
            except ProtocolError as exc:
                self._send_protocol_error(exc)
            except Exception as exc:  # noqa: BLE001 - boundary: never leak traces
                self._send_error(500, "INTERNAL", exc.__class__.__name__)

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            try:
                match = _OP_PATH.match(self.path.split("?", 1)[0])
                if not match:
                    self._send_error(404, "NOT_FOUND", f"unknown route: {self.path}")
                    return
                self._handle_op(match.group(1))
            except ProtocolError as exc:
                self._send_protocol_error(exc)
            except TypeError as exc:
                self._send_error(400, "INVALID_SPEC", f"bad parameters: {exc}")
            except Exception as exc:  # noqa: BLE001 - boundary: never leak traces
                self._send_error(500, "INTERNAL", exc.__class__.__name__)

        # ── handlers ──

        def _handle_op(self, operation: str) -> None:
            entry = _DISPATCH.get(operation)
            if entry is None:
                raise ProtocolError("NOT_FOUND", f"unknown operation: {operation}")
            body = self._read_body()
            params = dict(body.get("params") or {})

            principal = (self.headers.get("X-HLP-Principal") or "").strip()
            if operation not in _READ_OPS:
                if not principal:
                    raise ProtocolError(
                        "UNAUTHORIZED",
                        "mutating operations require the X-HLP-Principal header",
                    )
                for key in _ACTOR_BIND.get(operation, ()):
                    params[key] = principal
            elif principal and operation == "human.inbox":
                params["principal"] = principal

            if body.get("expected_task_revision") is not None:
                params["expected_task_revision"] = body["expected_task_revision"]
            if body.get("idempotency_key") is not None:
                params["idempotency_key"] = body["idempotency_key"]

            method_name, builders = entry
            method = getattr(app.operations, method_name, None)
            if method is None:
                if app._sdk_client is None:
                    raise ProtocolError("NOT_FOUND", f"unknown operation: {operation}")
                method = getattr(app._sdk_client, method_name, None)
            if method is None:
                raise ProtocolError("NOT_FOUND", f"unknown operation: {operation}")
            built = {
                key: builders.get(key, lambda value: value)(value) for key, value in params.items()
            }
            result = app.run_op(method(**built))
            self._send_json(200, result)

        def _handle_events(self) -> None:
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            after = 0
            max_seconds = app.sse_max_seconds
            for pair in query.split("&"):
                if pair.startswith("after="):
                    after = int(pair.removeprefix("after=") or 0)
                elif pair.startswith("max_seconds="):
                    max_seconds = min(float(pair.removeprefix("max_seconds=")), app.sse_max_seconds)

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            deadline = time.monotonic() + max_seconds
            cursor = after
            try:
                while time.monotonic() < deadline:
                    events = app.audit_events_after(cursor)
                    for event in events:
                        cursor = event.seq
                        payload = json.dumps(to_wire(event), ensure_ascii=False)
                        self.wfile.write(f"id: {event.seq}\n".encode())
                        self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()
                    time.sleep(app.sse_poll_interval)
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler
