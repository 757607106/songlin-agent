from __future__ import annotations

from graphlib import CycleError, TopologicalSorter

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintValidationResult
from src.agent_platform.types import ExecutionMode, WorkerKind


class AgentBlueprintValidator:
    def validate(self, blueprint: AgentBlueprint | dict) -> BlueprintValidationResult:
        normalized = blueprint if isinstance(blueprint, AgentBlueprint) else AgentBlueprint.model_validate(blueprint)
        errors: list[str] = []
        warnings: list[str] = []
        workers = normalized.workers

        if normalized.execution_mode is ExecutionMode.SINGLE and len(workers) > 1:
            errors.append("single 模式最多只能声明 1 个 worker")

        if normalized.execution_mode is not ExecutionMode.SINGLE and not workers:
            errors.append(f"{normalized.execution_mode.value} 模式至少需要 1 个 worker")

        keys = [worker.key for worker in workers]
        names = [worker.name for worker in workers]
        if len(keys) != len(set(keys)):
            errors.append("worker key 必须唯一")
        if len(names) != len(set(names)):
            errors.append("worker name 必须唯一")

        known_keys = set(keys)
        for worker in workers:
            missing_dependencies = [dependency for dependency in worker.depends_on if dependency not in known_keys]
            if missing_dependencies:
                errors.append(
                    f"worker `{worker.key}` 引用了不存在的依赖: {', '.join(sorted(missing_dependencies))}"
                )
            missing_allowed_targets = [target for target in worker.allowed_next if target not in known_keys]
            if missing_allowed_targets:
                errors.append(
                    f"worker `{worker.key}` 引用了不存在的 allowed_next: {', '.join(sorted(missing_allowed_targets))}"
                )
            if (
                worker.kind is WorkerKind.RETRIEVAL
                and not worker.knowledge_ids
                and not normalized.knowledge_ids
            ):
                warnings.append(f"retrieval worker `{worker.key}` 未配置知识源")
            if worker.allow_dynamic_spawn and normalized.execution_mode is ExecutionMode.SUPERVISOR:
                warnings.append(f"supervisor 模式默认忽略 `{worker.key}` 的动态 spawn 配置")

        dependency_order: list[str] = []
        if workers:
            graph = {worker.key: set(worker.depends_on) for worker in workers}
            try:
                dependency_order = list(TopologicalSorter(graph).static_order())
            except CycleError as exc:
                errors.append(f"worker 依赖存在环: {exc}")

        return BlueprintValidationResult(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            dependency_order=dependency_order,
            normalized_blueprint=normalized,
        )
