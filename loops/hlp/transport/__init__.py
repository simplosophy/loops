"""HLP HTTP reference transport binding (spec §7.1).

Stdlib-only reference binding: `HLPHttpServer` serves the 23 protocol
operations plus audit-event SSE over HTTP/JSON; `HttpHLPWireClient` is the
wire-level reference client. The wire contract is the deliverable (§6.4);
production deployments rebind with their own framework.
"""

from __future__ import annotations

from .client import HttpHLPWireClient, TransportError
from .server import HLPHttpServer

__all__ = [
    "HLPHttpServer",
    "HttpHLPWireClient",
    "TransportError",
]
