from __future__ import annotations

from src.agent_platform.executors.base import BaseExecutor
from src.agent_platform.executors.deep_agents_executor import DeepAgentsExecutor
from src.agent_platform.executors.single_executor import SingleExecutor
from src.agent_platform.executors.supervisor_executor import SupervisorExecutor
from src.agent_platform.executors.swarm_handoff_executor import SwarmHandoffExecutor
from src.agent_platform.types import ExecutionMode


class ExecutorRegistry:
    def __init__(self, executors: list[BaseExecutor] | None = None):
        self._executors: dict[ExecutionMode, BaseExecutor] = {}
        for executor in executors or [
            SingleExecutor(),
            SupervisorExecutor(),
            DeepAgentsExecutor(),
            SwarmHandoffExecutor(),
        ]:
            self.register(executor)

    def register(self, executor: BaseExecutor) -> None:
        self._executors[executor.mode] = executor

    def get(self, mode: ExecutionMode | str) -> BaseExecutor:
        resolved_mode = mode if isinstance(mode, ExecutionMode) else ExecutionMode(mode)
        try:
            return self._executors[resolved_mode]
        except KeyError as exc:
            raise KeyError(f"未注册的执行器模式: {resolved_mode}") from exc
