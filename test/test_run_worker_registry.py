from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker  # noqa: E402
from src.agent_platform.runtime.models import RunContext  # noqa: E402
from src.agent_platform.spec.compiler import AgentSpecCompiler  # noqa: E402
from src.agent_platform.types import ExecutionMode, WorkerKind  # noqa: E402
from src.agent_platform.workers.registry import WorkerTemplate, WorkerTemplateRegistry  # noqa: E402
from src.agent_platform.workers.runtime import RunWorkerRegistry  # noqa: E402


def _build_registry(*, max_dynamic_workers: int = 2) -> RunWorkerRegistry:
    spec = AgentSpecCompiler().compile(
        AgentBlueprint(
            name="Research Team",
            goal="Plan and delegate research work",
            execution_mode=ExecutionMode.DEEP_AGENTS,
            max_dynamic_workers=max_dynamic_workers,
            max_worker_steps=8,
            workers=[
                BlueprintWorker(
                    key="planner_worker",
                    name="Planner Worker",
                    kind=WorkerKind.REASONING,
                    allow_dynamic_spawn=True,
                    tools=["plan_tasks"],
                )
            ],
        )
    )
    run_context = RunContext(
        thread_id="thread-1",
        user_id="user-1",
        agent_spec_id=spec.spec_id,
    )
    templates = WorkerTemplateRegistry(
        [
            WorkerTemplate(
                template_id="legacy/research_planner",
                name="Research Planner",
                kind=WorkerKind.RETRIEVAL,
                description="Find evidence",
                objective="Research the assigned topic",
                tools=["web_search"],
                mcps=["browser-mcp"],
                knowledge_ids=["market-kb"],
                skills=["langchain-rag"],
            )
        ]
    )
    return RunWorkerRegistry(
        run_context=run_context,
        spec=spec,
        template_registry=templates,
        max_worker_timeout_seconds=600,
        max_worker_tokens=6000,
    )


def test_run_worker_registry_registers_static_and_dynamic_workers():
    registry = _build_registry()

    static_workers = registry.list_workers(lifecycle="static")
    assert [worker.worker_id for worker in static_workers] == ["planner_worker"]
    assert static_workers[0].context_scope == "thread_summary"
    assert static_workers[0].budget.max_steps == 8

    dynamic_worker = registry.spawn_worker(
        "legacy/research_planner",
        task_brief="Research revenue anomalies",
        context_scope="minimal",
        budget={"max_steps": 3, "timeout_seconds": 120, "max_tokens": 2000},
    )

    assert dynamic_worker.lifecycle == "dynamic"
    assert dynamic_worker.context_scope == "minimal"
    assert dynamic_worker.tools == ["web_search"]
    assert dynamic_worker.mcps == ["browser-mcp"]
    assert dynamic_worker.knowledge_ids == ["market-kb"]
    assert dynamic_worker.skills == ["langchain-rag"]

    events = registry.drain_events()
    assert [event.event_type for event in events] == ["worker.spawn"]
    assert events[0].payload["worker_id"] == dynamic_worker.worker_id


def test_run_worker_registry_send_to_worker_uses_run_scoped_inbox():
    registry = _build_registry()
    dynamic_worker = registry.spawn_worker(
        "legacy/research_planner",
        task_brief="Research revenue anomalies",
    )
    registry.drain_events()

    message = registry.send_to_worker(
        dynamic_worker.worker_id,
        {"instruction": "Focus on APAC region", "context_scope": "minimal"},
    )

    stored = registry.get_worker(dynamic_worker.worker_id)
    assert stored.inbox[0].message_id == message.message_id
    assert stored.inbox[0].payload == {
        "instruction": "Focus on APAC region",
        "context_scope": "minimal",
    }
    events = registry.drain_events()
    assert [event.event_type for event in events] == ["worker.send"]
    assert events[0].payload == {
        "worker_id": dynamic_worker.worker_id,
        "message_id": message.message_id,
    }


def test_run_worker_registry_enforces_dynamic_worker_limits():
    registry = _build_registry(max_dynamic_workers=1)
    registry.spawn_worker("legacy/research_planner", task_brief="first")

    with pytest.raises(ValueError, match="数量已达到上限"):
        registry.spawn_worker("legacy/research_planner", task_brief="second")


def test_run_worker_registry_enforces_budget_caps():
    registry = _build_registry()

    with pytest.raises(ValueError, match="步骤预算超过限制"):
        registry.spawn_worker(
            "legacy/research_planner",
            task_brief="overflow",
            budget={"max_steps": 20},
        )

    with pytest.raises(ValueError, match="超时预算超过限制"):
        registry.spawn_worker(
            "legacy/research_planner",
            task_brief="overflow",
            budget={"timeout_seconds": 601},
        )

    with pytest.raises(ValueError, match="token 预算超过限制"):
        registry.spawn_worker(
            "legacy/research_planner",
            task_brief="overflow",
            budget={"max_tokens": 6001},
        )
