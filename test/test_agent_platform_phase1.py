from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform import (
    AgentBlueprint,
    AgentBlueprintValidator,
    AgentRuntimeFacade,
    AgentSpecCompiler,
    BlueprintWorker,
    ExecutionMode,
    RetrievalMode,
    RunContext,
    WorkerKind,
)


def test_blueprint_validator_rejects_duplicate_worker_keys():
    blueprint = AgentBlueprint(
        name="Data Squad",
        goal="Analyze sales data",
        execution_mode=ExecutionMode.SUPERVISOR,
        workers=[
            BlueprintWorker(key="shared", name="Schema Worker"),
            BlueprintWorker(key="shared", name="SQL Worker"),
        ],
    )

    result = AgentBlueprintValidator().validate(blueprint)

    assert result.valid is False
    assert "worker key 必须唯一" in result.errors


def test_compiler_builds_default_single_worker_spec():
    blueprint = AgentBlueprint(
        name="Report Assistant",
        description="Generate business summaries",
        goal="Answer one reporting question",
        execution_mode=ExecutionMode.SINGLE,
        tools=["calculator"],
        knowledge_ids=["sales-kb"],
        retrieval_mode=RetrievalMode.HYBRID,
        interrupt_on_tools=["db_execute_query"],
    )

    spec = AgentSpecCompiler().compile(blueprint)

    assert spec.execution_mode is ExecutionMode.SINGLE
    assert len(spec.workers) == 1
    assert spec.routing_policy.entry_worker == spec.workers[0].key
    assert spec.workers[0].tool_binding.tool_ids == ["calculator"]
    assert spec.workers[0].retrieval is not None
    assert spec.memory_policy.short_term_backend == "thread_state"
    assert spec.memory_policy.namespaces.user_preferences == "/memory/users/{user_id}/preferences"
    assert spec.memory_policy.namespaces.user_facts == "/memory/users/{user_id}/facts"
    assert spec.memory_policy.namespaces.agent_playbooks == "/memory/agents/report_assistant/playbooks"
    assert spec.interrupt_policy.approval_required_tools == ["db_execute_query"]


def test_compiler_builds_supervisor_spec_with_dependency_order():
    blueprint = AgentBlueprint(
        name="DB Reporter",
        goal="Generate a reviewed SQL report",
        execution_mode=ExecutionMode.SUPERVISOR,
        default_model="gpt-4.1",
        max_parallel_workers=3,
        workers=[
            BlueprintWorker(
                key="schema_worker",
                name="Schema Worker",
                description="Inspect schema",
                kind=WorkerKind.RETRIEVAL,
                knowledge_ids=["db-schema"],
            ),
            BlueprintWorker(
                key="sql_worker",
                name="SQL Worker",
                description="Generate SQL",
                kind=WorkerKind.TOOL,
                tools=["generate_sql"],
                depends_on=["schema_worker"],
            ),
            BlueprintWorker(
                key="analysis_worker",
                name="Analysis Worker",
                description="Explain results",
                depends_on=["sql_worker"],
            ),
        ],
    )

    spec = AgentSpecCompiler().compile(blueprint)

    assert spec.routing_policy.topological_order == ["schema_worker", "sql_worker", "analysis_worker"]
    assert spec.routing_policy.entry_worker == "schema_worker"
    assert spec.performance_policy.max_parallel_workers == 3
    assert spec.workers[1].tool_binding.tool_ids == ["generate_sql"]
    assert spec.workers[0].retrieval is not None
    assert spec.workers[0].model == "gpt-4.1"


def test_runtime_facade_selects_deep_agents_executor_and_run_context():
    blueprint = AgentBlueprint(
        name="Research Team",
        goal="Investigate and summarize market signals",
        execution_mode=ExecutionMode.DEEP_AGENTS,
        max_dynamic_workers=4,
        workers=[
            BlueprintWorker(
                key="planner",
                name="Planner",
                description="Plan the work",
                allow_dynamic_spawn=True,
            ),
            BlueprintWorker(
                key="researcher",
                name="Researcher",
                description="Search and retrieve evidence",
                kind=WorkerKind.RETRIEVAL,
                depends_on=["planner"],
                knowledge_ids=["market-kb"],
            ),
        ],
    )

    facade = AgentRuntimeFacade()
    spec, run_context, plan = facade.prepare_blueprint_run(
        blueprint,
        thread_id="thread-1",
        user_id="user-1",
        attachments=[{"file_path": "/tmp/input.md"}],
        metadata={"source": "unit-test"},
    )

    assert spec.execution_mode is ExecutionMode.DEEP_AGENTS
    assert run_context == RunContext(
        run_id=run_context.run_id,
        thread_id="thread-1",
        user_id="user-1",
        agent_spec_id=spec.spec_id,
        attachments=[{"file_path": "/tmp/input.md"}],
        approved_interrupts={},
        metadata={"source": "unit-test"},
        started_at=run_context.started_at,
    )
    assert plan.executor_mode is ExecutionMode.DEEP_AGENTS
    assert plan.worker_order == ["planner", "researcher"]
    assert plan.dynamic_worker_enabled is True
    assert plan.max_dynamic_workers == 4


def test_runtime_facade_prepare_run_uses_existing_spec():
    blueprint = AgentBlueprint(
        name="Analyst",
        goal="Summarize one request",
    )
    compiler = AgentSpecCompiler()
    spec = compiler.compile(blueprint)
    run_context = RunContext(
        thread_id="thread-2",
        user_id="user-2",
        agent_spec_id=spec.spec_id,
    )

    plan = AgentRuntimeFacade(compiler=compiler).prepare_run(spec, run_context)

    assert plan.executor_mode is ExecutionMode.SINGLE
    assert plan.entry_worker == spec.routing_policy.entry_worker
    assert plan.dynamic_worker_enabled is False
