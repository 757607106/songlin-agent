from __future__ import annotations

import uuid

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker
from src.agent_platform.blueprint.validator import AgentBlueprintValidator
from src.agent_platform.spec.models import (
    AgentSpec,
    InterruptPolicy,
    MemoryNamespaceSpec,
    McpBindingSpec,
    MemoryPolicy,
    PerformancePolicy,
    RetrievalSpec,
    RoutingPolicy,
    ToolBindingSpec,
    WorkerSpec,
)
from src.agent_platform.types import ExecutionMode, dedupe_strings, slugify_name


class AgentSpecCompiler:
    def __init__(self, validator: AgentBlueprintValidator | None = None):
        self._validator = validator or AgentBlueprintValidator()

    def compile(self, blueprint: AgentBlueprint | dict) -> AgentSpec:
        validation = self._validator.validate(blueprint)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))

        normalized = validation.normalized_blueprint
        workers = normalized.workers or [self._build_default_single_worker(normalized)]
        dependency_order = validation.dependency_order or [worker.key for worker in workers]

        spec_workers = [self._compile_worker(normalized, worker) for worker in workers]
        memory_namespace_source = normalized.long_term_memory_namespace or slugify_name(
            normalized.name,
            fallback="agent",
        )
        memory_namespace = memory_namespace_source.strip("/")

        return AgentSpec(
            spec_id=uuid.uuid4().hex,
            name=normalized.name,
            description=normalized.description,
            goal=normalized.goal,
            task_scope=normalized.task_scope,
            execution_mode=normalized.execution_mode,
            system_prompt=normalized.system_prompt,
            supervisor_prompt=normalized.supervisor_prompt,
            product_agent=normalized.product_agent,
            workers=spec_workers,
            routing_policy=RoutingPolicy(
                mode=normalized.execution_mode,
                entry_worker=dependency_order[0],
                topological_order=dependency_order,
            ),
            memory_policy=MemoryPolicy(
                short_term_backend="thread_state",
                long_term_namespace=memory_namespace,
                namespaces=MemoryNamespaceSpec(
                    user_preferences="/memory/users/{user_id}/preferences",
                    user_facts="/memory/users/{user_id}/facts",
                    agent_playbooks=f"/memory/agents/{memory_namespace}/playbooks",
                ),
            ),
            interrupt_policy=InterruptPolicy(
                approval_required_tools=normalized.interrupt_on_tools,
            ),
            performance_policy=PerformancePolicy(
                max_parallel_workers=normalized.max_parallel_workers,
                max_dynamic_workers=self._max_dynamic_workers(normalized),
                max_worker_steps=normalized.max_worker_steps,
            ),
            compile_notes=validation.warnings,
        )

    @staticmethod
    def _build_default_single_worker(blueprint: AgentBlueprint) -> BlueprintWorker:
        return BlueprintWorker(
            key=slugify_name(blueprint.name, fallback="worker"),
            name=blueprint.name,
            description=blueprint.description,
            objective=blueprint.goal,
            system_prompt=blueprint.system_prompt,
            model=blueprint.default_model,
        )

    @staticmethod
    def _max_dynamic_workers(blueprint: AgentBlueprint) -> int:
        if blueprint.execution_mode in {ExecutionMode.DEEP_AGENTS, ExecutionMode.SWARM_HANDOFF}:
            return blueprint.max_dynamic_workers
        return 0

    @staticmethod
    def _compile_worker(blueprint: AgentBlueprint, worker: BlueprintWorker) -> WorkerSpec:
        tool_ids = dedupe_strings([*blueprint.tools, *worker.tools])
        server_names = dedupe_strings([*blueprint.mcps, *worker.mcps])
        knowledge_ids = dedupe_strings([*blueprint.knowledge_ids, *worker.knowledge_ids])
        retrieval = None
        if knowledge_ids:
            retrieval = RetrievalSpec(knowledge_ids=knowledge_ids, mode=blueprint.retrieval_mode)

        return WorkerSpec(
            key=worker.key or worker.name,
            name=worker.name,
            description=worker.description,
            objective=worker.objective or worker.description or blueprint.goal,
            system_prompt=worker.system_prompt,
            kind=worker.kind,
            model=worker.model or blueprint.default_model,
            dependencies=worker.depends_on,
            allowed_next=worker.allowed_next,
            skills=dedupe_strings([*blueprint.skills, *worker.skills]),
            tool_binding=ToolBindingSpec(tool_ids=tool_ids),
            mcp_binding=McpBindingSpec(server_names=server_names),
            retrieval=retrieval,
            allow_dynamic_spawn=(
                worker.allow_dynamic_spawn
                and blueprint.execution_mode in {ExecutionMode.DEEP_AGENTS, ExecutionMode.SWARM_HANDOFF}
            ),
        )
