from __future__ import annotations

from src.agent_platform.executors.base import BaseExecutor, ExecutionPlan
from src.agent_platform.runtime.models import RunContext
from src.agent_platform.spec.models import AgentSpec
from src.agent_platform.types import ExecutionMode


class SupervisorExecutor(BaseExecutor):
    mode = ExecutionMode.SUPERVISOR

    def prepare_run(self, spec: AgentSpec, run_context: RunContext) -> ExecutionPlan:
        return self._base_plan(spec, run_context, dynamic_worker_enabled=False)
