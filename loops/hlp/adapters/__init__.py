"""HLP adapter package: contracts, fakes, process/CLI, and framework shims.

Depth levels:
- **first-class**: real CLI/harness projection (Codex, Claude, Kimi, Pi, process)
- **shape-compatible**: thin Python framework entry points (OpenAI/LangGraph/CrewAI)
- **testing**: Fake*/InMemory* for offline unit tests and demos
"""

from __future__ import annotations

from .callable import PythonCallableAgentAdapter
from .cli import (
    ClaudeCodeCLIAdapter,
    HermesCLIAdapter,
    HermsCLIAdapter,
    KimiCLIAdapter,
    PiHarnessAdapter,
)
from .codex import CodexCLIAdapter, CodexHarnessAdapter
from .fake import FakeAgentAdapter, FakeHarnessAdapter, InMemoryAgentAdapter
from .frameworks import (
    CrewAIAdapter,
    LangGraphAdapter,
    OpenAIAgentsSDKAdapter,
    OpenAIPythonSDKAdapter,
)
from .process import (
    ProcessAgentAdapter,
    PromptCLIAdapter,
    chat_mode_prompt,
    cli_operation_prompt,
    prompt_for_adapter_operation,
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
    "CodexCLIAdapter",
    "CodexHarnessAdapter",
    "CrewAIAdapter",
    "FakeAgentAdapter",
    "FakeHarnessAdapter",
    "HarnessAdapter",
    "HarnessCapabilities",
    "HarnessEvent",
    "HarnessEventDelivery",
    "HermesCLIAdapter",
    "HermsCLIAdapter",
    "InMemoryAgentAdapter",
    "KimiCLIAdapter",
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
    "chat_mode_prompt",
    "cli_operation_prompt",
    "prompt_for_adapter_operation",
]
