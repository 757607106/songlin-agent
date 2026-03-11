from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from src.agent_platform.runtime.models import RunContext
from src.agent_platform.spec.models import AgentSpec
from src.agent_platform.types import ExecutionMode


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_mode: ExecutionMode
    spec_id: str
    run_id: str
    thread_id: str
    entry_worker: str
    worker_order: list[str] = Field(default_factory=list)
    interrupt_enabled: bool = False
    dynamic_worker_enabled: bool = False
    max_parallel_workers: int = 1
    max_dynamic_workers: int = 0


class BaseExecutor(ABC):
    mode: ExecutionMode

    @abstractmethod
    def prepare_run(self, spec: AgentSpec, run_context: RunContext) -> ExecutionPlan:
        raise NotImplementedError

    def _base_plan(
        self,
        spec: AgentSpec,
        run_context: RunContext,
        *,
        dynamic_worker_enabled: bool,
    ) -> ExecutionPlan:
        return ExecutionPlan(
            executor_mode=self.mode,
            spec_id=spec.spec_id,
            run_id=run_context.run_id,
            thread_id=run_context.thread_id,
            entry_worker=spec.routing_policy.entry_worker,
            worker_order=spec.routing_policy.topological_order,
            interrupt_enabled=bool(spec.interrupt_policy.approval_required_tools),
            dynamic_worker_enabled=dynamic_worker_enabled,
            max_parallel_workers=spec.performance_policy.max_parallel_workers,
            max_dynamic_workers=spec.performance_policy.max_dynamic_workers,
        )
