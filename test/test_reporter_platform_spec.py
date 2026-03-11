from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.reporter import build_reporter_blueprint, build_reporter_spec
from src.agent_platform.reporter.runtime import _next_worker_for_stage
from src.agent_platform.types import ExecutionMode
from src.agents.reporter.context import ReporterContext


def test_reporter_blueprint_preserves_supervisor_flow_with_sample_and_chart():
    context = ReporterContext(
        model="gpt-4.1",
        mcps=["mcp-server-chart"],
        use_generated_skills=False,
        enable_interrupt_on=True,
        interrupt_on_db_execute_query=True,
        interrupt_on_save_query_history=False,
    )

    blueprint = build_reporter_blueprint(context)

    assert blueprint.execution_mode is ExecutionMode.SUPERVISOR
    assert blueprint.max_parallel_workers == 1
    assert blueprint.interrupt_on_tools == ["db_execute_query"]
    assert [worker.key for worker in blueprint.workers] == [
        "schema_worker",
        "clarification_worker",
        "sample_retrieval_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
        "analysis_worker",
        "chart_worker",
        "error_recovery_worker",
    ]


def test_reporter_spec_omits_sample_and_chart_when_skills_and_mcp_are_absent():
    context = ReporterContext(
        model="gpt-4.1",
        mcps=[],
        use_generated_skills=True,
        generated_skill_ids=["sales_skill"],
        enable_interrupt_on=True,
        interrupt_on_db_execute_query=True,
        interrupt_on_save_query_history=True,
    )

    spec = build_reporter_spec(context)
    worker_keys = [worker.key for worker in spec.workers]
    worker_map = {worker.key: worker for worker in spec.workers}

    assert spec.execution_mode is ExecutionMode.SUPERVISOR
    assert worker_keys == [
        "schema_worker",
        "clarification_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
        "analysis_worker",
        "error_recovery_worker",
    ]
    assert spec.routing_policy.topological_order == worker_keys
    assert spec.interrupt_policy.approval_required_tools == [
        "db_execute_query",
        "save_query_history",
    ]
    assert spec.memory_policy.long_term_namespace == "builtin/reporter"
    assert spec.memory_policy.namespaces.agent_playbooks == "/memory/agents/builtin/reporter/playbooks"
    assert worker_map["sql_execution_worker"].tool_binding.tool_ids == [
        "db_execute_query",
        "save_query_history",
    ]
    assert worker_map["sql_validation_worker"].allowed_next == [
        "sql_execution_worker",
        "error_recovery_worker",
    ]
    assert worker_map["error_recovery_worker"].allowed_next == worker_keys[:-1]


def test_reporter_runtime_routes_analysis_to_chart_or_end():
    with_chart = build_reporter_spec(
        ReporterContext(model="gpt-4.1", mcps=["mcp-server-chart"], use_generated_skills=False)
    )
    without_chart = build_reporter_spec(
        ReporterContext(model="gpt-4.1", mcps=[], use_generated_skills=False)
    )

    assert _next_worker_for_stage("analysis_worker", {"status": "ANALYSIS_READY"}, spec=with_chart) == "chart_worker"
    assert _next_worker_for_stage("analysis_worker", {"status": "ANALYSIS_READY"}, spec=without_chart) == "__end__"


def test_reporter_runtime_maps_recovery_next_stage():
    spec = build_reporter_spec(
        ReporterContext(model="gpt-4.1", mcps=[], use_generated_skills=True, generated_skill_ids=["sales_skill"])
    )

    assert _next_worker_for_stage(
        "error_recovery_worker",
        {"status": "RECOVERED", "next_stage": "sql_validation"},
        spec=spec,
    ) == "sql_validation_worker"
    assert _next_worker_for_stage(
        "error_recovery_worker",
        {"status": "BLOCKED", "next_stage": "sql_validation"},
        spec=spec,
    ) == "__end__"
