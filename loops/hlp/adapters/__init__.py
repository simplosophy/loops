"""HLP adapter package: contracts, fakes, process/CLI, and framework shims.

Depth levels:
- **first-class**: real CLI/harness projection (Codex, Claude, Kimi, Pi, process)
- **shape-compatible**: thin Python framework entry points (OpenAI/LangGraph/CrewAI)
- **testing**: Fake*/InMemory* for offline unit tests and demos
"""

from __future__ import annotations

from ._harness import HarnessAdapterBase
from .callable import PythonCallableAgentAdapter
from .claude import ClaudeCodeCLIAdapter, ClaudeCodeHarnessAdapter
from .codex import CodexCLIAdapter, CodexHarnessAdapter
from .fake import FakeAgentAdapter, FakeHarnessAdapter, InMemoryAgentAdapter
from .frameworks import (
    CrewAIAdapter,
    LangGraphAdapter,
    OpenAIAgentsSDKAdapter,
    OpenAIPythonSDKAdapter,
)
from .hermes import HermesCLIAdapter, HermsCLIAdapter
from .kimi import KimiCLIAdapter, KimiHarnessAdapter
from .pi import PiHarnessAdapter
from .process import (
    ProcessAgentAdapter,
    PromptCLIAdapter,
    StreamChunk,
    chat_mode_prompt,
    cli_operation_prompt,
    format_harness_stream_line,
    make_streaming_prompt_runner,
    prompt_for_adapter_operation,
    run_prompt_process_streaming,
)
from .protocol import (
    AgentAdapter,
    AgentAdapterError,
    AgentRunHandle,
    HarnessAdapter,
    HarnessCapabilities,
    HarnessEvent,
    HarnessEventDelivery,
    ProcessResult,
    ProcessRunner,
    ReliableHarnessEventAdapter,
)

__all__ = [
    "AgentAdapter",
    "AgentAdapterError",
    "AgentRunHandle",
    "ClaudeCodeCLIAdapter",
    "ClaudeCodeHarnessAdapter",
    "CodexCLIAdapter",
    "CodexHarnessAdapter",
    "CrewAIAdapter",
    "FakeAgentAdapter",
    "FakeHarnessAdapter",
    "HarnessAdapter",
    "HarnessAdapterBase",
    "HarnessCapabilities",
    "HarnessEvent",
    "HarnessEventDelivery",
    "HermesCLIAdapter",
    "HermsCLIAdapter",
    "InMemoryAgentAdapter",
    "KimiCLIAdapter",
    "KimiHarnessAdapter",
    "LangGraphAdapter",
    "OpenAIAgentsSDKAdapter",
    "OpenAIPythonSDKAdapter",
    "PiHarnessAdapter",
    "ProcessAgentAdapter",
    "ProcessResult",
    "ProcessRunner",
    "PromptCLIAdapter",
    "PythonCallableAgentAdapter",
    "ReliableHarnessEventAdapter",
    "StreamChunk",
    "chat_mode_prompt",
    "cli_operation_prompt",
    "format_harness_stream_line",
    "make_streaming_prompt_runner",
    "prompt_for_adapter_operation",
    "run_prompt_process_streaming",
]
