from __future__ import annotations

# Re-exported so tests can keep monkeypatching loops.tui.controller.subprocess.run
# (the /diff implementation lives in _session_cmds but shares the module object).
import subprocess as subprocess

from ._base import TUIResult as TUIResult
from ._base import TUISessionError as TUISessionError
from ._base import TUIUsageError as TUIUsageError
from ._base import _ControllerBase
from ._control_cmds import ControlCmds
from ._hlp_cmds import HlpCmds
from ._session_cmds import SessionCmds
from ._work_cmds import WorkCmds


class TUIController(SessionCmds, WorkCmds, HlpCmds, ControlCmds, _ControllerBase):
    """TUI host controller: parses user input and drives HLP sessions.

    Composed from domain command mixins over _ControllerBase; command dispatch
    chains SessionCmds → WorkCmds → HlpCmds → ControlCmds → _ControllerBase
    via super().
    """
