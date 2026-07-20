from __future__ import annotations

from ..objects import AdapterOperationContext, Task
from ..types import ProtocolError
from ._base import HumanLoopOperationsBase, _TaskOperationReplay


class OwnershipOps(HumanLoopOperationsBase):
    # ────────────────── Ownership (spec §4.1) ──────────────────

    async def ownership_transfer(
        self,
        task_id: str,
        to: str,
        via: str,
        *,
        actor: str = "system",
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """ownership.transfer (spec §4.1, §3.5). Internal assignee transfer."""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "ownership.transfer",
            {
                "to": to,
                "via": via,
                "actor": actor,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if task.is_terminal:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "cannot transfer ownership of terminal task",
            )
        run_id = self.store.run_of_task(task_id)
        new_run_id: str | None = None
        adapter_context: AdapterOperationContext | None = None
        if via == "handoff" and run_id is not None and to != task.ownership.assignee:
            handoff_context = {
                "task_id": task.id,
                "from": task.ownership.assignee,
                "to": to,
                "via": via,
            }
            adapter_request = {
                "adapter_action": "handoff",
                "run_id": run_id,
                "to_agent": to,
                "context": handoff_context,
            }
            adapter_context = self._adapter_context(task, idempotency)
            outbox_request = self._prepare_adapter_outbox(
                adapter_context,
                adapter_request,
            )
            new_run_id = await self._call_adapter_with_context(
                self.adapter.handoff,
                outbox_request["run_id"],
                outbox_request["to_agent"],
                outbox_request["context"],
                context=adapter_context,
            )
        task.ownership = task.ownership.transfer(to, via=via)  # type: ignore[arg-type]
        if new_run_id is not None:
            self.store.bind_run(task_id, new_run_id)
        self._audit(
            actor=actor,
            action="ownership.transferred",
            subject=("task", task.id),
            task_id=task.id,
            after={"assignee": to, "via": via},
        )
        self._commit_task_operation(
            task,
            idempotency,
            task,
            adapter_result=new_run_id,
        )
        return task

    async def ownership_delegate(
        self,
        task_id: str,
        to_agent: str,
        *,
        actor: str,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """ownership.delegate (spec §4.1, §3.5). The agent delegates downward; requires delegable."""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "ownership.delegate",
            {
                "to_agent": to_agent,
                "actor": actor,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if not task.ownership.delegable:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "task is not delegable (ownership.delegable=false)",
            )
        if task.is_terminal:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "cannot delegate terminal task",
            )
        parent_run = self.store.run_of_task(task_id)
        adapter_request = {
            "adapter_action": "delegate",
            "task_id": task_id,
            "agent_id": to_agent,
            "capability": "",
            "input": {"goal": task.spec.goal},
            "parent_run": parent_run,
        }
        adapter_context = self._adapter_context(task, idempotency)
        outbox_request = self._prepare_adapter_outbox(
            adapter_context,
            adapter_request,
        )
        run_id = await self._call_adapter_with_context(
            self.adapter.delegate,
            context=adapter_context,
            task_id=outbox_request["task_id"],
            agent_id=outbox_request["agent_id"],
            capability=outbox_request["capability"],
            input=outbox_request["input"],
            parent_run=outbox_request["parent_run"],
        )
        # chained delegation: recorded in the chain (spec §7.3)
        task.ownership = task.ownership.transfer(to_agent, via="assign")
        self.store.bind_run(task_id, run_id)
        self._audit(
            actor=actor,
            action="ownership.delegated",
            subject=("task", task.id),
            task_id=task.id,
            after={"delegatee": to_agent},
        )
        self._commit_task_operation(task, idempotency, task, adapter_result=run_id)
        return task
