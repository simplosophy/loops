from __future__ import annotations

from .adapters import AgentAdapter, FakeAgentAdapter

# Compatibility names retained for existing code while HLP public semantics move
# from the historical AAP wording to the generic agent adapter contract.
AAPBridge = AgentAdapter
InMemoryAAPBridge = FakeAgentAdapter
