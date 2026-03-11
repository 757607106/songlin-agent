from __future__ import annotations

from src.agent_platform.executors.base import BaseExecutor, ExecutionPlan
from src.agent_platform.runtime.models import RunContext
from src.agent_platform.spec.models import AgentSpec
from src.agent_platform.types import ExecutionMode


class SwarmHandoffExecutor(BaseExecutor):
    mode = ExecutionMode.SWARM_HANDOFF

    def prepare_run(self, spec: AgentSpec, run_context: RunContext) -> ExecutionPlan:
        dynamic_worker_enabled = any(worker.allow_dynamic_spawn for worker in spec.workers)
        return self._base_plan(spec, run_context, dynamic_worker_enabled=dynamic_worker_enabled)
