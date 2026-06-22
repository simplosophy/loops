"""loops public SDK surface.

The current implementation lives in :mod:`loops.loop0`. Top-level imports are
kept as a compatibility layer while loop1 and loop2 are introduced.

Layer packages:
    loops.loop0  — agent runtime kernel (owns execution)
    loops.loop2  — HLP reference implementation (owns human-loop work)

loop2 is imported explicitly as ``from loops.loop2 import ...`` rather than
re-exported at the top level, to keep the loop0 runtime API as the default
surface and the HLP protocol layer opt-in.
"""

from __future__ import annotations

import sys
from importlib import import_module

from loops.loop0 import (
    Agent,
    AgentEvent,
    AgentPolicy,
    AgentResult,
    AgentSpec,
    AgentState,
    ApprovalRequest,
    CallableEventSink,
    EventLogger,
    EventSink,
    InMemoryEventLogger,
    InMemoryEventSink,
    InteractionContext,
    MemoryRecord,
    Message,
    NullEventSink,
    PromptRenderContext,
    PromptTemplate,
    StdlibEventLogger,
    ToolCall,
    UserInput,
    agent,
    get_logger,
)

_COMPAT_MODULES = (
    "agent",
    "components",
    "components.base",
    "events",
    "io",
    "logging",
    "policy",
    "profiles",
    "prompt",
    "providers",
    "providers.adapter",
    "providers.base",
    "providers.openai",
    "runtime",
    "state",
    "tools",
    "tools.base",
    "tools.shell",
    "types",
)

for _alias in _COMPAT_MODULES:
    _module = import_module(f"{__name__}.loop0.{_alias}")
    sys.modules[f"{__name__}.{_alias}"] = _module
    if "." not in _alias and _alias not in globals():
        setattr(sys.modules[__name__], _alias, _module)

del import_module, sys, _alias, _module

__all__ = [
    "Agent",
    "AgentEvent",
    "AgentPolicy",
    "AgentResult",
    "AgentSpec",
    "AgentState",
    "ApprovalRequest",
    "CallableEventSink",
    "EventLogger",
    "EventSink",
    "InMemoryEventLogger",
    "InMemoryEventSink",
    "InteractionContext",
    "MemoryRecord",
    "Message",
    "NullEventSink",
    "PromptRenderContext",
    "PromptTemplate",
    "StdlibEventLogger",
    "ToolCall",
    "UserInput",
    "agent",
    "get_logger",
]
