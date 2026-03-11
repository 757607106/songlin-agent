from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.reporter.runtime import (
    _build_worker_input_messages,
    _enrich_stage_output,
    _build_worker_runnable,
    _parse_stage_output,
    _should_use_deep_agent_driver,
    build_reporter_supervisor_graph,
)
from src.agent_platform.reporter.spec import build_reporter_spec
from src.agents.reporter.context import ReporterContext
from src.services.interrupt_protocol import (
    ApprovalInterruptInfo,
    ApprovalResumePayload,
    approval_resume_is_approved,
)


class FakeRunnable:
    def __init__(self, name: str, behavior):
        self.name = name
        self._behavior = behavior

    async def ainvoke(self, state):
        payload = self._behavior(self.name, state)
        return {"messages": [AIMessage(content=json.dumps(payload, ensure_ascii=False))]}


class InterruptibleRunnable:
    def __init__(self):
        builder = StateGraph(dict)
        builder.add_node("approval", self._approval_node)
        builder.add_edge(START, "approval")
        builder.add_edge("approval", END)
        self._graph = builder.compile()

    @staticmethod
    def _approval_node(state):
        approval = interrupt(
            ApprovalInterruptInfo(
                question="是否批准执行 SQL？",
                operation="db_execute_query",
                allowed_decisions=["approve", "reject"],
            ).to_payload()
        )
        approved = approval_resume_is_approved(approval)
        status = "EXEC_SUCCESS" if approved else "EXEC_BLOCKED"
        summary = "查询已执行" if approved else "查询被拒绝"
        return {"messages": [AIMessage(content=json.dumps({"status": status, "summary": summary}, ensure_ascii=False))]}

    async def ainvoke(self, state):
        return await self._graph.ainvoke(state)


class SlowRunnable:
    async def ainvoke(self, state):
        await asyncio.sleep(0.05)
        return {"messages": [AIMessage(content=json.dumps({"status": "EXEC_SUCCESS"}, ensure_ascii=False))]}


def test_should_use_deep_agent_driver_only_for_skills_or_interrupts():
    plain_spec = build_reporter_spec(
        ReporterContext(model="gpt-4.1", mcps=[], use_generated_skills=False, enable_interrupt_on=False)
    )
    interrupt_spec = build_reporter_spec(
        ReporterContext(model="gpt-4.1", mcps=[], use_generated_skills=False, enable_interrupt_on=True)
    )
    plain_worker = next(worker for worker in plain_spec.workers if worker.key == "analysis_worker")
    interrupt_worker = next(worker for worker in interrupt_spec.workers if worker.key == "sql_execution_worker")

    assert _should_use_deep_agent_driver(plain_worker, spec=plain_spec, skill_sources=[]) is False
    assert _should_use_deep_agent_driver(interrupt_worker, spec=interrupt_spec, skill_sources=[]) is True
    assert _should_use_deep_agent_driver(plain_worker, spec=plain_spec, skill_sources=["/skills/reporter"]) is True


def test_build_worker_runnable_uses_light_and_deep_drivers(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []
    spec = build_reporter_spec(
        ReporterContext(model="gpt-4.1", mcps=[], use_generated_skills=False, enable_interrupt_on=True)
    )
    analysis_worker = next(worker for worker in spec.workers if worker.key == "analysis_worker")
    execution_worker = next(worker for worker in spec.workers if worker.key == "sql_execution_worker")

    def fake_create_agent(*, name: str, **kwargs):
        calls.append(("light", name))
        return FakeRunnable(name, lambda _name, _state: {"status": "ANALYSIS_READY"})

    def fake_create_deep_agent(*, name: str, **kwargs):
        calls.append(("deep", name))
        return FakeRunnable(name, lambda _name, _state: {"status": "EXEC_SUCCESS"})

    from src.agent_platform.reporter import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module, "create_deep_agent", fake_create_deep_agent)

    _build_worker_runnable(
        analysis_worker,
        worker_model=object(),
        tools=[],
        spec=spec,
        skill_sources=[],
    )
    _build_worker_runnable(
        execution_worker,
        worker_model=object(),
        tools=[],
        spec=spec,
        skill_sources=[],
    )

    assert calls == [("light", "analysis_worker"), ("deep", "sql_execution_worker")]


def test_parse_stage_output_accepts_plain_key_value_text():
    parsed = _parse_stage_output(
        AIMessage(
            content=(
                "status: SQL_READY\n"
                "summary: 已生成 SQL\n"
                "generated_sql: SELECT * FROM orders LIMIT 100"
            )
        )
    )

    assert parsed["status"] == "SQL_READY"
    assert parsed["summary"] == "已生成 SQL"
    assert parsed["generated_sql"] == "SELECT * FROM orders LIMIT 100"


def test_parse_stage_output_accepts_numbered_clarification_questions():
    parsed = _parse_stage_output(
        AIMessage(
            content=(
                "status: CLARIFY_REQUIRED\n"
                "summary: 当前缺少统计口径。\n"
                "clarification_questions:\n"
                "1. 统计时间范围是什么？\n"
                "2. 是否需要区分订单状态？"
            )
        )
    )

    assert parsed["status"] == "CLARIFY_REQUIRED"
    assert parsed["summary"] == "当前缺少统计口径。"
    assert parsed["clarification_questions"] == [
        "统计时间范围是什么？",
        "是否需要区分订单状态？",
    ]


def test_enrich_stage_output_merges_schema_tool_payload():
    parsed = _enrich_stage_output(
        "schema_worker",
        {"status": "SCHEMA_READY", "summary": "已完成 Schema 分析"},
        [
            ToolMessage(
                tool_call_id="call_1",
                name="retrieve_database_schema",
                content=json.dumps(
                    {
                        "stage": "schema_analysis",
                        "schema_text": "表 orders(id, order_date, amount, status)",
                        "query_analysis": {"tables": ["orders"], "columns": ["order_date", "amount"]},
                        "value_mappings": {"orders.status": {"已支付": "paid"}},
                    },
                    ensure_ascii=False,
                ),
            ),
            AIMessage(content="status: SCHEMA_READY\nsummary: 已完成 Schema 分析"),
        ],
    )

    assert parsed["schema_text"] == "表 orders(id, order_date, amount, status)"
    assert parsed["query_analysis"]["tables"] == ["orders"]
    assert parsed["value_mappings"]["orders.status"]["已支付"] == "paid"


def test_build_worker_input_messages_includes_upstream_context():
    messages = _build_worker_input_messages(
        "sql_generation_worker",
        {
            "messages": [HumanMessage(content="请统计 2025 年已支付订单的月销售额")],
            "stage_outputs": {
                "schema_worker": {
                    "status": "SCHEMA_READY",
                    "summary": "已定位订单表",
                    "schema_text": "表 orders(id, order_date, amount, status)",
                    "query_analysis": {"tables": ["orders"]},
                    "value_mappings": {"orders.status": {"已支付": "paid"}},
                },
                "clarification_worker": {
                    "status": "CLARIFY_CLEAR",
                    "clarified_scope": "统计 2025 年已支付订单的月销售额",
                },
            },
        },
    )

    assert len(messages) == 2
    assert messages[0].content == "请统计 2025 年已支付订单的月销售额"
    context_message = messages[-1].content
    assert "sql_generation_worker" in context_message
    assert "schema_worker" in context_message
    assert "orders.status" in context_message
    assert "clarified_scope" in context_message


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_runs_full_happy_path(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY"},
            "clarification_worker": {"status": "CLARIFY_CLEAR"},
            "sample_retrieval_worker": {"status": "SAMPLE_READY"},
            "sql_generation_worker": {"status": "SQL_READY"},
            "sql_validation_worker": {"status": "PASS"},
            "sql_execution_worker": {"status": "EXEC_SUCCESS"},
            "analysis_worker": {"status": "ANALYSIS_READY"},
            "chart_worker": {"status": "CHART_READY"},
            "error_recovery_worker": {"status": "BLOCKED"},
        }
        return mapping[name]

    monkeypatch.setattr(
        runtime_module,
        "create_agent",
        lambda *, name, **kwargs: FakeRunnable(name, behavior),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_deep_agent",
        lambda *, name, **kwargs: FakeRunnable(name, behavior),
    )

    graph = await build_reporter_supervisor_graph(
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

    result = await graph.ainvoke({"messages": [HumanMessage(content="show me sales trend")]})

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
    assert result["active_worker"] == "chart_worker"
    assert result["stage_outputs"]["sql_execution_worker"]["status"] == "EXEC_SUCCESS"


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_emits_single_user_visible_summary(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY", "summary": "已锁定 customers 和 sales_orders"},
            "clarification_worker": {"status": "CLARIFY_CLEAR", "clarified_scope": "按客户统计销售订单数量"},
            "sample_retrieval_worker": {"status": "SAMPLE_READY"},
            "sql_generation_worker": {"status": "SQL_READY"},
            "sql_validation_worker": {"status": "PASS", "summary": "SQL 校验通过"},
            "sql_execution_worker": {"status": "EXEC_SUCCESS", "summary": "已统计 128 个客户"},
            "analysis_worker": {
                "status": "ANALYSIS_READY",
                "summary": "订单数量前五的客户贡献了主要销量。",
                "insights": ["头部客户集中度较高", "尾部客户分布较分散"],
                "next_actions": ["建议继续按区域拆分客户订单量"],
            },
            "chart_worker": {"status": "CHART_SKIPPED", "reason": "当前问题只需要文字结论"},
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

    streamed_contents: list[str] = []
    async for msg, _metadata in graph.astream(
        {"messages": [HumanMessage(content="按客户统计销售订单数量")]},
        stream_mode="messages",
    ):
        content = getattr(msg, "content", "")
        if isinstance(content, str) and content.strip():
            streamed_contents.append(content)

    final_state = await graph.ainvoke({"messages": [HumanMessage(content="按客户统计销售订单数量")]})
    final_message = final_state["messages"][-1].content

    assert len(streamed_contents) == 1
    assert "SCHEMA_READY" not in streamed_contents[0]
    assert '"status"' not in streamed_contents[0]
    assert "订单数量前五的客户贡献了主要销量。" in streamed_contents[0]
    assert "关键洞察：头部客户集中度较高；尾部客户分布较分散" in streamed_contents[0]
    assert "建议下一步：建议继续按区域拆分客户订单量" in streamed_contents[0]
    assert "未生成图表：当前问题只需要文字结论" in streamed_contents[0]
    assert final_message == streamed_contents[0]


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_formats_clarification_question_for_user(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY", "summary": "已定位订单事实表"},
            "clarification_worker": {
                "status": "CLARIFY_REQUIRED",
                "summary": "当前还缺少统计口径，暂时不能继续生成 SQL。",
                "clarification_questions": ["统计时间范围是什么？", "是否需要区分订单状态？"],
            },
            "error_recovery_worker": {"status": "BLOCKED"},
        }
        return mapping.get(name, {"status": "BLOCKED"})

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

    result = await graph.ainvoke({"messages": [HumanMessage(content="统计订单数量")]})
    final_message = result["messages"][-1].content

    assert result["route_log"] == ["schema_worker", "clarification_worker"]
    assert "SCHEMA_READY" not in final_message
    assert "当前还缺少统计口径" in final_message
    assert "1. 统计时间范围是什么？" in final_message
    assert "2. 是否需要区分订单状态？" in final_message


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_stops_on_clarification_required(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY"},
            "clarification_worker": {"status": "CLARIFY_REQUIRED"},
        }
        return mapping.get(name, {"status": "BLOCKED"})

    monkeypatch.setattr(
        runtime_module,
        "create_agent",
        lambda *, name, **kwargs: FakeRunnable(name, behavior),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_deep_agent",
        lambda *, name, **kwargs: FakeRunnable(name, behavior),
    )

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

    result = await graph.ainvoke({"messages": [HumanMessage(content="need a metric")]})

    assert result["route_log"] == ["schema_worker", "clarification_worker"]
    assert "sql_generation_worker" not in result["stage_outputs"]
    assert result["stage_outputs"]["clarification_worker"]["status"] == "CLARIFY_REQUIRED"


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_interrupt_resume_keeps_worker_context(monkeypatch: pytest.MonkeyPatch):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY"},
            "clarification_worker": {"status": "CLARIFY_CLEAR"},
            "sample_retrieval_worker": {"status": "SAMPLE_READY"},
            "sql_generation_worker": {"status": "SQL_READY"},
            "sql_validation_worker": {"status": "PASS"},
            "analysis_worker": {"status": "ANALYSIS_READY"},
            "chart_worker": {"status": "CHART_READY"},
            "error_recovery_worker": {"status": "BLOCKED"},
        }
        return mapping[name]

    monkeypatch.setattr(
        runtime_module,
        "create_agent",
        lambda *, name, **kwargs: FakeRunnable(name, behavior),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_deep_agent",
        lambda *, name, **kwargs: (
            InterruptibleRunnable() if name == "sql_execution_worker" else FakeRunnable(name, behavior)
        ),
    )

    graph = await build_reporter_supervisor_graph(
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
        checkpointer=InMemorySaver(),
    )

    config = {"configurable": {"thread_id": "reporter-interrupt"}}

    first = await graph.ainvoke({"messages": [HumanMessage(content="run revenue report")]}, config=config)

    assert "__interrupt__" in first

    paused_state = await graph.aget_state(config)
    assert paused_state.values["active_worker"] == "sql_execution_worker"
    assert paused_state.values["route_log"] == [
        "schema_worker",
        "clarification_worker",
        "sample_retrieval_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
    ]
    assert "sql_execution_worker" not in paused_state.values.get("stage_outputs", {})

    resumed = await graph.ainvoke(
        Command(resume=ApprovalResumePayload(decision="approve").to_payload()),
        config=config,
    )

    assert resumed["route_log"] == [
        "schema_worker",
        "clarification_worker",
        "sample_retrieval_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
        "analysis_worker",
        "chart_worker",
    ]
    assert resumed["active_worker"] == "chart_worker"
    assert resumed["stage_outputs"]["sql_execution_worker"]["status"] == "EXEC_SUCCESS"


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_routes_rejected_execution_to_blocked_recovery(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY"},
            "clarification_worker": {"status": "CLARIFY_CLEAR"},
            "sample_retrieval_worker": {"status": "SAMPLE_READY"},
            "sql_generation_worker": {"status": "SQL_READY"},
            "sql_validation_worker": {"status": "PASS"},
            "analysis_worker": {"status": "ANALYSIS_READY"},
            "chart_worker": {"status": "CHART_READY"},
            "error_recovery_worker": {"status": "BLOCKED", "summary": "执行被人工拒绝"},
        }
        return mapping[name]

    monkeypatch.setattr(
        runtime_module,
        "create_agent",
        lambda *, name, **kwargs: FakeRunnable(name, behavior),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_deep_agent",
        lambda *, name, **kwargs: (
            InterruptibleRunnable() if name == "sql_execution_worker" else FakeRunnable(name, behavior)
        ),
    )

    graph = await build_reporter_supervisor_graph(
        model=object(),
        context=ReporterContext(
            model="gpt-4.1",
            mcps=[],
            use_generated_skills=False,
            enable_interrupt_on=True,
        ),
        tool_map={},
        mcp_tools=[],
        skill_sources=[],
        checkpointer=InMemorySaver(),
    )

    config = {"configurable": {"thread_id": "reporter-reject"}}
    first = await graph.ainvoke({"messages": [HumanMessage(content="run revenue report")]}, config=config)
    assert "__interrupt__" in first

    resumed = await graph.ainvoke(
        Command(resume=ApprovalResumePayload(decision="reject").to_payload()),
        config=config,
    )

    assert resumed["route_log"] == [
        "schema_worker",
        "clarification_worker",
        "sample_retrieval_worker",
        "sql_generation_worker",
        "sql_validation_worker",
        "sql_execution_worker",
        "error_recovery_worker",
    ]
    assert resumed["active_worker"] == "error_recovery_worker"
    assert resumed["stage_outputs"]["sql_execution_worker"]["status"] == "EXEC_BLOCKED"
    assert resumed["stage_outputs"]["error_recovery_worker"]["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_routes_worker_timeout_into_error_recovery(
    monkeypatch: pytest.MonkeyPatch,
):
    from src.agent_platform.reporter import runtime as runtime_module

    def behavior(name: str, _state):
        mapping = {
            "schema_worker": {"status": "SCHEMA_READY"},
            "clarification_worker": {"status": "CLARIFY_CLEAR"},
            "sample_retrieval_worker": {"status": "SAMPLE_READY"},
            "sql_validation_worker": {"status": "PASS"},
            "sql_execution_worker": {"status": "EXEC_SUCCESS"},
            "analysis_worker": {"status": "ANALYSIS_READY"},
            "chart_worker": {"status": "CHART_READY"},
            "error_recovery_worker": {"status": "BLOCKED", "summary": "sql generation timeout"},
        }
        return mapping[name]

    monkeypatch.setattr(
        runtime_module,
        "create_agent",
        lambda *, name, **kwargs: SlowRunnable() if name == "sql_generation_worker" else FakeRunnable(name, behavior),
    )
    monkeypatch.setattr(
        runtime_module,
        "create_deep_agent",
        lambda *, name, **kwargs: FakeRunnable(name, behavior),
    )

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
        per_worker_timeout=0.01,
    )

    result = await graph.ainvoke({"messages": [HumanMessage(content="run timeout report")]})

    assert result["route_log"] == [
        "schema_worker",
        "clarification_worker",
        "sample_retrieval_worker",
        "sql_generation_worker",
        "error_recovery_worker",
    ]
    assert result["active_worker"] == "error_recovery_worker"
    assert result["stage_outputs"]["sql_generation_worker"]["status"] == "ERROR"
    assert result["stage_outputs"]["sql_generation_worker"]["error_type"] == "timeout"
    assert result["stage_outputs"]["error_recovery_worker"]["status"] == "BLOCKED"
