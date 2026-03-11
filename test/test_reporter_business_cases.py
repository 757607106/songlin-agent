from __future__ import annotations

import json
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.reporter.runtime import build_reporter_supervisor_graph
from src.agents.reporter.context import ReporterContext


class FakeRunnable:
    def __init__(self, name: str, behavior):
        self.name = name
        self._behavior = behavior

    async def ainvoke(self, state):
        payload = self._behavior(self.name, state)
        return {"messages": [AIMessage(content=json.dumps(payload, ensure_ascii=False))]}


@pytest.mark.asyncio
async def test_reporter_business_case_uses_skills_and_skips_sample_worker(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY", "summary": "找到销售订单与客户表"},
            "clarification_worker": {"status": "CLARIFY_CLEAR", "clarified_scope": "按月统计订单金额"},
            "sql_generation_worker": {"status": "SQL_READY", "generated_sql": "select month, amount from orders"},
            "sql_validation_worker": {"status": "PASS", "summary": "SQL 可执行"},
            "sql_execution_worker": {"status": "EXEC_SUCCESS", "summary": "已查询 12 个月销售额"},
            "analysis_worker": {"status": "ANALYSIS_READY", "summary": "销售额在第四季度达到峰值"},
            "error_recovery_worker": {"status": "BLOCKED"},
        }
        return mapping[name]

    monkeypatch.setattr(runtime_module, "create_agent", lambda *, name, **kwargs: FakeRunnable(name, behavior))
    monkeypatch.setattr(runtime_module, "create_deep_agent", lambda *, name, **kwargs: FakeRunnable(name, behavior))

    graph = await build_reporter_supervisor_graph(
        model=object(),
        context=ReporterContext(
            model="gpt-4.1",
            mcps=[],
            use_generated_skills=True,
            generated_skill_ids=["sales_skill"],
            enable_interrupt_on=False,
        ),
        tool_map={},
        mcp_tools=[],
        skill_sources=["/skills/reporter/sales"],
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="分析近 12 个月销售额趋势")]})

    assert result["route_log"] == [
        "schema_worker",
        "clarification_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
        "analysis_worker",
    ]
    assert "sample_retrieval_worker" not in result["stage_outputs"]
    assert result["stage_outputs"]["analysis_worker"]["status"] == "ANALYSIS_READY"


@pytest.mark.asyncio
async def test_reporter_business_case_chart_skipped_still_finishes(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY"},
            "clarification_worker": {"status": "CLARIFY_CLEAR"},
            "sample_retrieval_worker": {"status": "SAMPLE_EMPTY"},
            "sql_generation_worker": {"status": "SQL_READY"},
            "sql_validation_worker": {"status": "PASS"},
            "sql_execution_worker": {"status": "EXEC_SUCCESS", "summary": "只返回单条 KPI"},
            "analysis_worker": {"status": "ANALYSIS_READY", "summary": "库存周转率稳定"},
            "chart_worker": {"status": "CHART_SKIPPED", "reason": "单指标不需要图表"},
            "error_recovery_worker": {"status": "BLOCKED"},
        }
        return mapping[name]

    monkeypatch.setattr(runtime_module, "create_agent", lambda *, name, **kwargs: FakeRunnable(name, behavior))
    monkeypatch.setattr(runtime_module, "create_deep_agent", lambda *, name, **kwargs: FakeRunnable(name, behavior))

    graph = await build_reporter_supervisor_graph(
        model=object(),
        context=ReporterContext(
            model="gpt-4.1",
            mcps=["mcp-server-chart"],
            use_generated_skills=False,
            enable_interrupt_on=False,
        ),
        tool_map={},
        mcp_tools=[],
        skill_sources=[],
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="给我库存周转率结论，不需要图表")]})

    assert result["route_log"] == [
        "schema_worker",
        "clarification_worker",
        "sample_retrieval_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
        "analysis_worker",
        "chart_worker",
    ]
    assert result["stage_outputs"]["chart_worker"]["status"] == "CHART_SKIPPED"
    assert result["active_worker"] == "chart_worker"


@pytest.mark.asyncio
async def test_reporter_business_case_recovery_retries_sql_generation(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    call_counts: dict[str, int] = {}

    def behavior(name: str, _state):
        call_counts[name] = call_counts.get(name, 0) + 1

        if name == "schema_worker":
            return {"status": "SCHEMA_READY"}
        if name == "clarification_worker":
            return {"status": "CLARIFY_CLEAR"}
        if name == "sample_retrieval_worker":
            return {"status": "SAMPLE_READY"}
        if name == "sql_generation_worker":
            if call_counts[name] == 1:
                return {"status": "SQL_READY", "generated_sql": "select * from broken_orders"}
            return {"status": "SQL_READY", "generated_sql": "select month, sum(amount) from orders"}
        if name == "sql_validation_worker":
            if call_counts[name] == 1:
                return {"status": "FAIL", "issues": ["字段不存在"]}
            return {"status": "PASS"}
        if name == "sql_execution_worker":
            return {"status": "EXEC_SUCCESS"}
        if name == "analysis_worker":
            return {"status": "ANALYSIS_READY", "summary": "修复后查询成功"}
        if name == "chart_worker":
            return {"status": "CHART_SKIPPED"}
        if name == "error_recovery_worker":
            return {
                "status": "RECOVERED",
                "next_stage": "sql_generation",
                "summary": "字段名错误，回退重新生成 SQL",
            }
        return {"status": "BLOCKED"}

    monkeypatch.setattr(runtime_module, "create_agent", lambda *, name, **kwargs: FakeRunnable(name, behavior))
    monkeypatch.setattr(runtime_module, "create_deep_agent", lambda *, name, **kwargs: FakeRunnable(name, behavior))

    graph = await build_reporter_supervisor_graph(
        model=object(),
        context=ReporterContext(
            model="gpt-4.1",
            mcps=[],
            use_generated_skills=False,
            enable_interrupt_on=False,
        ),
        tool_map={},
        mcp_tools=[],
        skill_sources=[],
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="按月统计订单销售额")]})

    assert result["route_log"] == [
        "schema_worker",
        "clarification_worker",
        "sample_retrieval_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "error_recovery_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
        "analysis_worker",
    ]
    assert call_counts["sql_generation_worker"] == 2
    assert call_counts["sql_validation_worker"] == 2
    assert result["stage_outputs"]["error_recovery_worker"]["status"] == "RECOVERED"
    assert result["stage_outputs"]["analysis_worker"]["status"] == "ANALYSIS_READY"
