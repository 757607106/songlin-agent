from __future__ import annotations

import json
import os
import sys
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.reporter.runtime import build_reporter_supervisor_graph  # noqa: E402
from src.agents.reporter.context import ReporterContext  # noqa: E402


class FakeRunnable:
    def __init__(self, name: str, behavior):
        self.name = name
        self._behavior = behavior

    async def ainvoke(self, state):
        payload = self._behavior(self.name, state)
        return {"messages": [AIMessage(content=json.dumps(payload, ensure_ascii=False))]}


def _stable_behavior(name: str, _state) -> dict:
    mapping = {
        "schema_worker": {"status": "SCHEMA_READY"},
        "clarification_worker": {"status": "CLARIFY_CLEAR"},
        "sample_retrieval_worker": {"status": "SAMPLE_READY"},
        "sql_generation_worker": {"status": "SQL_READY"},
        "sql_validation_worker": {"status": "PASS"},
        "sql_execution_worker": {"status": "EXEC_SUCCESS", "summary": "查询已执行"},
        "analysis_worker": {"status": "ANALYSIS_READY", "summary": "分析已完成"},
        "chart_worker": {"status": "CHART_READY", "summary": "图表已生成"},
        "error_recovery_worker": {"status": "BLOCKED"},
    }
    return mapping[name]


async def _build_fake_reporter_graph(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "create_agent",
        lambda *, name, **kwargs: FakeRunnable(name, _stable_behavior),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_deep_agent",
        lambda *, name, **kwargs: FakeRunnable(name, _stable_behavior),
    )
    return await build_reporter_supervisor_graph(
        model=object(),
        context=ReporterContext(
            model="gpt-4.1",
            mcps=["mcp-server-chart"],
            use_generated_skills=False,
            enable_interrupt_on=True,
        ),
        tool_map={},
        mcp_tools=[],
        skill_sources=[],
    )


@pytest.mark.asyncio
async def test_reporter_output_regression_is_stable_across_repeated_runs(monkeypatch: pytest.MonkeyPatch):
    graph = await _build_fake_reporter_graph(monkeypatch)

    results = []
    for _ in range(3):
        results.append(await graph.ainvoke({"messages": [HumanMessage(content="show me revenue trend")] }))

    route_logs = [result["route_log"] for result in results]
    stage_statuses = [
        {key: value["status"] for key, value in result["stage_outputs"].items()}
        for result in results
    ]

    assert route_logs == [
        [
            "schema_worker",
            "clarification_worker",
            "sample_retrieval_worker",
            "sql_generation_worker",
            "sql_validation_worker",
            "sql_execution_worker",
            "analysis_worker",
            "chart_worker",
        ]
    ] * 3
    assert stage_statuses[0] == stage_statuses[1] == stage_statuses[2]
    assert results[0]["stage_outputs"]["sql_execution_worker"]["summary"] == "查询已执行"
    assert results[0]["stage_outputs"]["analysis_worker"]["summary"] == "分析已完成"


@pytest.mark.asyncio
async def test_reporter_fake_driver_performance_smoke_budget(monkeypatch: pytest.MonkeyPatch):
    graph = await _build_fake_reporter_graph(monkeypatch)

    started_at = time.perf_counter()
    for _ in range(10):
        await graph.ainvoke({"messages": [HumanMessage(content="show me revenue trend")]})
    elapsed = time.perf_counter() - started_at

    # Fake drivers should keep the supervisor regression suite comfortably fast.
    assert elapsed < 3.0
