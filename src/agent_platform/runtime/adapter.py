from __future__ import annotations

from src import config as sys_config
from src.agent_platform.runtime.memory_service import memory_namespaces_to_context_payload
from src.agent_platform.spec.models import AgentSpec, WorkerSpec
from src.agent_platform.types import ExecutionMode, dedupe_strings

_MODE_MAP = {
    ExecutionMode.SINGLE: "disabled",
    ExecutionMode.SUPERVISOR: "supervisor",
    ExecutionMode.DEEP_AGENTS: "deep_agents",
    ExecutionMode.SWARM_HANDOFF: "swarm",
}


def build_dynamic_context_from_platform_config(config_json: dict | None) -> dict:
    raw = config_json or {}
    spec_payload = raw.get("spec")
    if not isinstance(spec_payload, dict):
        return {}

    spec = AgentSpec.model_validate(spec_payload)
    worker_order = spec.routing_policy.topological_order or [worker.key for worker in spec.workers]
    worker_map = {worker.key: worker for worker in spec.workers}
    entry_worker = worker_map.get(spec.routing_policy.entry_worker) or next(iter(worker_map.values()), None)

    all_tools = dedupe_strings(
        tool_id
        for worker in spec.workers
        for tool_id in worker.tool_binding.tool_ids
    )
    all_knowledges = dedupe_strings(
        knowledge_id
        for worker in spec.workers
        for knowledge_id in (worker.retrieval.knowledge_ids if worker.retrieval else [])
    )
    all_mcps = dedupe_strings(
        server_name
        for worker in spec.workers
        for server_name in worker.mcp_binding.server_names
    )
    all_skills = dedupe_strings(
        skill_id
        for worker in spec.workers
        for skill_id in worker.skills
    )

    if spec.execution_mode is ExecutionMode.SINGLE:
        return {
            "multi_agent_mode": "disabled",
            "team_goal": spec.goal,
            "task_scope": spec.task_scope,
            "communication_protocol": "hybrid",
            "max_parallel_tasks": 1,
            "allow_cross_agent_comm": False,
            "system_prompt": spec.system_prompt,
            "supervisor_system_prompt": spec.supervisor_prompt,
            "model": _worker_model(entry_worker),
            "tools": list(all_tools),
            "knowledges": list(all_knowledges),
            "mcps": list(all_mcps),
            "skills": list(all_skills),
            "memory_namespaces": memory_namespaces_to_context_payload(spec.memory_policy.namespaces),
            "subagents": [],
            "spawn_enabled": False,
            "max_spawn_concurrency": 0,
        }

    subagents = [
        _worker_to_subagent(
            worker_map[worker_key],
            worker_order=worker_order,
            worker_map=worker_map,
            default_model=_worker_model(entry_worker),
        )
        for worker_key in worker_order
        if worker_key in worker_map
    ]

    return {
        "multi_agent_mode": _MODE_MAP.get(spec.execution_mode, "disabled"),
        "team_goal": spec.goal,
        "task_scope": spec.task_scope,
        "communication_protocol": "hybrid",
        "max_parallel_tasks": spec.performance_policy.max_parallel_workers,
        "allow_cross_agent_comm": False,
        "system_prompt": spec.system_prompt,
        "supervisor_system_prompt": spec.supervisor_prompt,
        "model": _worker_model(entry_worker),
        "tools": list(all_tools),
        "knowledges": list(all_knowledges),
        "mcps": list(all_mcps),
        "skills": list(all_skills),
        "memory_namespaces": memory_namespaces_to_context_payload(spec.memory_policy.namespaces),
        "subagents": subagents,
        "spawn_enabled": spec.performance_policy.max_dynamic_workers > 0,
        "max_spawn_concurrency": spec.performance_policy.max_dynamic_workers,
    }


def _worker_to_subagent(
    worker: WorkerSpec,
    *,
    worker_order: list[str],
    worker_map: dict[str, WorkerSpec],
    default_model: str,
) -> dict:
    depends_on = [
        worker_map[dependency].name if dependency in worker_map else dependency for dependency in worker.dependencies
    ]
    allowed_targets = [
        worker_map[target].name if target in worker_map else target for target in worker.allowed_next
    ]
    if not allowed_targets:
        fallback_target = _default_next_worker(worker.key, worker_order, worker_map)
        if fallback_target:
            allowed_targets = [fallback_target]

    knowledges = worker.retrieval.knowledge_ids if worker.retrieval else []
    return {
        "name": worker.name,
        "description": worker.description,
        "system_prompt": worker.system_prompt,
        "tools": list(worker.tool_binding.tool_ids),
        "model": worker.model or default_model,
        "knowledges": list(knowledges),
        "mcps": list(worker.mcp_binding.server_names),
        "skills": list(worker.skills),
        "depends_on": depends_on,
        "allowed_targets": allowed_targets,
        "communication_mode": "hybrid",
        "max_retries": 1,
        "plugin": "default",
    }


def _default_next_worker(
    worker_key: str,
    worker_order: list[str],
    worker_map: dict[str, WorkerSpec],
) -> str | None:
    try:
        index = worker_order.index(worker_key)
    except ValueError:
        return None

    for candidate in worker_order[index + 1 :]:
        if candidate in worker_map:
            return worker_map[candidate].name
    return None


def _worker_model(worker: WorkerSpec | None) -> str:
    if worker and worker.model:
        return worker.model
    return sys_config.default_model
