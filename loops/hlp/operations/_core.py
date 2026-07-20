from __future__ import annotations

from ._base import HumanLoopOperationsBase
from ._demo import DemoOps
from .artifact import ArtifactOps
from .audit import AuditOps
from .checkpoint import CheckpointOps
from .ledger import LedgerOps
from .ownership import OwnershipOps
from .review import ReviewOps
from .task import TaskOps

# ════════════════════════════════════════════════════════════
# HLP protocol operations (spec §4)
#
# Every operation follows a uniform structure:
#   1. precondition checks (spec §4.3) → raise ProtocolError on failure
#   2. state transition (spec §3.3)
#   3. audit record (spec §4.2)
#   4. cross-layer contract call (spec §5.1, when an agent adapter is involved)
#
# All operations are async — leaving room for a future transport (spec §7.1).
# ════════════════════════════════════════════════════════════


class HumanLoopOperations(
    DemoOps,
    TaskOps,
    CheckpointOps,
    OwnershipOps,
    ReviewOps,
    ArtifactOps,
    LedgerOps,
    AuditOps,
    HumanLoopOperationsBase,
):
    """Entry point for HLP protocol operations (spec §4.1, 23 in total).

    Holds store + audit + agent adapter; the facade of the protocol layer.
    Upper layers (transport/CLI) call into this; this class is transport-agnostic.
    """
