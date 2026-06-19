from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AAPBridge(Protocol):
    """HACP → AAP 层间接口契约 (spec §5.1)。

    这是 L2 调用 L1 的唯一合法通道。参考实现提供一个 InMemoryAAPBridge
    只记录调用、不真实执行 agent——用于验证 HACP 在正确时机调用正确方法。

    真实 AAP 实现 (A2A runtime 等) 注入此接口即可接入 Loops 栈。
    TaskID 必须贯穿 (spec §5.1 铁律)。
    """

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        """委派子任务给 agent，返回 run_id。run.correlation_id = task_id。"""
        ...

    async def block(self, run_id: str, checkpoint_id: str, reason: str) -> None:
        """阻塞 run，等待 HACP checkpoint.resolve。"""
        ...

    async def resume(self, run_id: str, resolution: Any) -> None:
        """恢复被 block 的 run。resolution 来自 checkpoint.resolve。"""
        ...

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        """交接给新 agent，返回新 run_id，correlation_id 保持。"""
        ...


@dataclass
class InMemoryAAPBridge:
    """参考实现 stub：记录所有调用，不执行真实 agent。

    用于测试和协议验证——确证 HACP 在正确时机调用了正确的 AAP 方法，
    TaskID 正确贯穿。真实部署时替换为 A2A-backed 实现。
    """

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _run_counter: int = field(default=0, repr=False)
    _run_to_task: dict[str, str] = field(default_factory=dict, repr=False)

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        self._run_counter += 1
        run_id = f"run_{self._run_counter:06d}"
        self._run_to_task[run_id] = task_id  # correlation 贯穿
        self.calls.append((
            "delegate",
            {"run_id": run_id, "task_id": task_id, "agent_id": agent_id,
             "capability": capability, "parent_run": parent_run},
        ))
        return run_id

    async def block(self, run_id: str, checkpoint_id: str, reason: str) -> None:
        self.calls.append((
            "block",
            {"run_id": run_id, "checkpoint_id": checkpoint_id, "reason": reason},
        ))

    async def resume(self, run_id: str, resolution: Any) -> None:
        self.calls.append((
            "resume",
            {"run_id": run_id, "resolution": resolution},
        ))

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        self._run_counter += 1
        new_run_id = f"run_{self._run_counter:06d}"
        # handoff 保持 correlation_id (spec §5.1)
        self._run_to_task[new_run_id] = self._run_to_task.get(run_id, "")
        self.calls.append((
            "handoff",
            {"from_run": run_id, "to_run": new_run_id, "to_agent": to_agent},
        ))
        return new_run_id

    def task_of_run(self, run_id: str) -> str | None:
        """查 run_id 对应的 task_id——验证 correlation 贯穿 (spec §5.1 铁律)。"""
        return self._run_to_task.get(run_id)

    def calls_of(self, method: str) -> list[tuple[str, dict[str, Any]]]:
        return [c for c in self.calls if c[0] == method]
