from __future__ import annotations

from src.agent_platform.blueprint.models import AgentBlueprint
from src.agent_platform.executors.base import ExecutionPlan
from src.agent_platform.executors.registry import ExecutorRegistry
from src.agent_platform.runtime.models import RunContext
from src.agent_platform.spec.compiler import AgentSpecCompiler
from src.agent_platform.spec.models import AgentSpec


class AgentRuntimeFacade:
    def __init__(
        self,
        *,
        compiler: AgentSpecCompiler | None = None,
        registry: ExecutorRegistry | None = None,
    ):
        self._compiler = compiler or AgentSpecCompiler()
        self._registry = registry or ExecutorRegistry()

    def compile_blueprint(self, blueprint: AgentBlueprint | dict) -> AgentSpec:
        return self._compiler.compile(blueprint)

    def prepare_run(self, spec: AgentSpec, run_context: RunContext) -> ExecutionPlan:
        executor = self._registry.get(spec.execution_mode)
        return executor.prepare_run(spec, run_context)

    def prepare_blueprint_run(
        self,
        blueprint: AgentBlueprint | dict,
        *,
        thread_id: str,
        user_id: str,
        attachments: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> tuple[AgentSpec, RunContext, ExecutionPlan]:
        spec = self.compile_blueprint(blueprint)
        run_context = RunContext(
            thread_id=thread_id,
            user_id=user_id,
            agent_spec_id=spec.spec_id,
            attachments=attachments or [],
            metadata=metadata or {},
        )
        return spec, run_context, self.prepare_run(spec, run_context)
