from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.blueprint.models import AgentBlueprint, BlueprintWorker
from src.agent_platform.example_catalog import agent_example_registry
from src.agent_platform.runtime.adapter import build_dynamic_context_from_platform_config
from src.agent_platform.runtime.runtime_context_service import runtime_context_service
from src.agent_platform.spec.compiler import AgentSpecCompiler
from src.agent_platform.types import ExecutionMode, WorkerKind


def test_platform_runtime_adapter_maps_supervisor_spec_to_dynamic_context():
    blueprint = AgentBlueprint(
        name="SQL Insight Agent",
        description="Analyse database questions",
        goal="Understand questions and produce SQL-backed insights",
        execution_mode=ExecutionMode.SUPERVISOR,
        system_prompt="Coordinate workers carefully.",
        supervisor_prompt="Route by dependency order.",
        default_model="openai/gpt-4.1",
        max_parallel_workers=3,
        max_dynamic_workers=0,
        workers=[
            BlueprintWorker(
                key="planner_worker",
                name="Planner Worker",
                description="Clarify the user goal",
                kind=WorkerKind.REASONING,
                tools=["clarify_user_intent"],
                allowed_next=["sql_worker"],
            ),
            BlueprintWorker(
                key="sql_worker",
                name="SQL Worker",
                description="Generate and validate SQL",
                kind=WorkerKind.TOOL,
                tools=["run_sql"],
                knowledge_ids=["sales_schema"],
                mcps=["chart-mcp"],
                skills=["langchain-rag"],
                depends_on=["planner_worker"],
            ),
        ],
    )
    spec = AgentSpecCompiler().compile(blueprint)

    context = build_dynamic_context_from_platform_config(
        {
            "version": "agent_platform_v2",
            "spec": spec.model_dump(mode="json"),
        }
    )

    assert context["multi_agent_mode"] == "supervisor"
    assert context["system_prompt"] == "Coordinate workers carefully."
    assert context["supervisor_system_prompt"] == "Route by dependency order."
    assert context["max_parallel_tasks"] == 3
    assert context["model"] == "openai/gpt-4.1"
    assert set(context["tools"]) == {"clarify_user_intent", "run_sql"}
    assert context["knowledges"] == ["sales_schema"]
    assert context["mcps"] == ["chart-mcp"]
    assert context["skills"] == ["langchain-rag"]
    assert len(context["subagents"]) == 2
    assert context["subagents"][0]["name"] == "Planner Worker"
    assert context["subagents"][0]["allowed_targets"] == ["SQL Worker"]
    assert context["subagents"][1]["depends_on"] == ["Planner Worker"]


def test_platform_runtime_adapter_maps_dependencies_to_runtime_subagent_names():
    example = agent_example_registry.get("legacy/knowledge_qa_minimal")

    context = build_dynamic_context_from_platform_config(
        {
            "version": "agent_platform_v2",
            "spec": example.spec.model_dump(mode="json"),
        }
    )

    worker_map = {worker["name"]: worker for worker in context["subagents"]}

    assert worker_map["Knowledge Retriever"]["depends_on"] == ["Intake Worker"]
    assert worker_map["Answer Reviewer"]["depends_on"] == ["Knowledge Retriever"]

    validation = runtime_context_service.validate_team(context, strict=True)

    assert validation["valid"] is True
    assert validation["errors"] == []


def test_platform_runtime_adapter_maps_single_spec_to_disabled_mode():
    blueprint = AgentBlueprint(
        name="Research Agent",
        description="Answer user questions",
        goal="Produce direct answers",
        execution_mode=ExecutionMode.SINGLE,
        system_prompt="Answer directly.",
        default_model="openai/gpt-4.1-mini",
        tools=["web_search"],
        knowledge_ids=["product_docs"],
        workers=[
            BlueprintWorker(
                key="assistant_worker",
                name="Assistant Worker",
                description="Single worker",
                kind=WorkerKind.REASONING,
            )
        ],
    )
    spec = AgentSpecCompiler().compile(blueprint)

    context = build_dynamic_context_from_platform_config(
        {
            "version": "agent_platform_v2",
            "spec": spec.model_dump(mode="json"),
        }
    )

    assert context["multi_agent_mode"] == "disabled"
    assert context["subagents"] == []
    assert context["tools"] == ["web_search"]
    assert context["knowledges"] == ["product_docs"]
    assert context["memory_namespaces"] == {
        "user_preferences": "/memory/users/{user_id}/preferences",
        "user_facts": "/memory/users/{user_id}/facts",
        "agent_playbooks": "/memory/agents/research_agent/playbooks",
    }
    assert context["spawn_enabled"] is False
