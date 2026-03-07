from __future__ import annotations

import asyncio
import os

os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.team_orchestration_service import TeamOrchestrationService


def _sample_team(mode: str = "deep_agents") -> dict:
    return {
        "team_goal": "完成多渠道市场调研并输出结论",
        "task_scope": "仅覆盖公开信息，不涉及私有数据",
        "multi_agent_mode": mode,
        "communication_protocol": "hybrid",
        "max_parallel_tasks": 2,
        "subagents": [
            {
                "name": "planner",
                "description": "拆解任务并分配子问题",
                "system_prompt": "你负责拆解任务并定义执行顺序。",
                "tools": ["calculator"],
                "depends_on": [],
                "max_retries": 1,
            },
            {
                "name": "researcher",
                "description": "检索外部信息并汇总证据",
                "system_prompt": "你负责检索并输出证据。",
                "depends_on": ["planner"],
                "knowledges": ["kb_a"],
                "max_retries": 2,
            },
            {
                "name": "writer",
                "description": "汇总并撰写最终报告",
                "system_prompt": "你负责整合结论并输出报告。",
                "depends_on": ["researcher"],
                "max_retries": 1,
            },
        ],
    }


def test_wizard_step_with_json_payload_completes():
    service = TeamOrchestrationService()
    team = _sample_team("supervisor")
    message = f"```json\n{team}\n```".replace("'", '"')

    result = service.wizard_step(message)

    assert result["is_complete"] is True
    assert result["draft"]["multi_agent_mode"] == "supervisor"
    assert len(result["draft"]["subagents"]) == 3
    assert result["validation"]["valid"] is True


def test_wizard_step_reports_missing_required_fields():
    service = TeamOrchestrationService()
    result = service.wizard_step("目标: 做一个多agent团队")

    assert result["is_complete"] is False
    assert result["questions"]
    assert "任务范围" in result["questions"][0] or "子Agent" in "".join(result["questions"])


def test_wizard_step_with_ai_autofills_dev_team():
    service = TeamOrchestrationService()
    result = asyncio.run(service.wizard_step_with_ai("帮我组建一个 DeepAgents 需求开发团队"))

    assert result["is_complete"] is True
    draft = result["draft"]
    assert draft["multi_agent_mode"] == "deep_agents"
    names = {sa["name"] for sa in draft["subagents"]}
    assert {
        "product_manager",
        "project_manager",
        "frontend_engineer",
        "backend_engineer",
        "qa_engineer",
        "technical_writer",
    }.issubset(names)


def test_wizard_step_with_ai_uses_llm_patch(monkeypatch):
    service = TeamOrchestrationService()

    async def _fake_llm(message: str, current_team: dict):
        assert "法务" in message
        return {
            "team_goal": "完成合同合规审查",
            "task_scope": "仅覆盖合同条款审查",
            "multi_agent_mode": "deep_agents",
            "subagents": [
                {
                    "name": "legal_reviewer",
                    "description": "审查合同风险",
                    "system_prompt": "你负责合同条款审查。",
                    "depends_on": [],
                }
            ],
        }

    monkeypatch.setattr(service, "_build_builtin_team_patch", lambda *_: {})
    monkeypatch.setattr(service, "_generate_team_patch_with_llm", _fake_llm)

    result = asyncio.run(service.wizard_step_with_ai("帮我组建一个法务审查团队"))

    assert result["is_complete"] is True
    assert result["draft"]["subagents"][0]["name"] == "legal_reviewer"


def test_validate_team_detects_dependency_cycle():
    service = TeamOrchestrationService()
    team = _sample_team("supervisor")
    team["subagents"][0]["depends_on"] = ["writer"]

    check = service.validate_team(team)

    assert check["valid"] is False
    assert any("循环依赖" in err for err in check["errors"])


def test_validate_team_builds_topology_and_groups():
    service = TeamOrchestrationService()
    team = _sample_team("deep_agents")

    check = service.validate_team(team)

    assert check["valid"] is True
    assert check["dependency_order"] == ["planner", "researcher", "writer"]
    assert check["execution_groups"] == [["planner"], ["researcher"], ["writer"]]


def test_validate_team_detects_role_overlap():
    service = TeamOrchestrationService()
    team = _sample_team("supervisor")
    team["subagents"][2]["description"] = "检索外部信息并汇总证据"
    team["subagents"][2]["system_prompt"] = "你负责检索并输出证据。"

    check = service.validate_team(team, strict=False)

    assert check["warnings"] or check["errors"]


def test_build_runtime_context_contains_policy_and_prompts():
    service = TeamOrchestrationService()
    runtime = service.build_runtime_context(_sample_team("deep_agents"), strict=True)

    assert runtime["multi_agent_mode"] == "deep_agents"
    assert runtime["team_policy"]["execution_groups"]
    assert "OpenClaw" in runtime["system_prompt"]
    assert runtime["subagents"][1]["depends_on"] == ["planner"]


def test_benchmark_modes_returns_comparison_metrics():
    service = TeamOrchestrationService()
    benchmark = service.benchmark_modes(_sample_team("deep_agents"), iterations=3)

    assert benchmark["valid"] is True
    assert benchmark["timings"]["avg_validate_ms"] >= 0
    assert benchmark["mode_comparison"]["deep_vs_disabled_speedup"] > 0


def test_query_langchain_docs_uses_mcp_tools(monkeypatch):
    service = TeamOrchestrationService()

    class DummyTool:
        name = "search_docs"
        args_schema = {"properties": {"query": {"type": "string"}}}

        async def ainvoke(self, args):
            return {"ok": True, "args": args}

    async def _fake_get_enabled_mcp_tools(server_name: str):
        assert server_name == "langchain-docs"
        return [DummyTool()]

    monkeypatch.setattr(
        "src.services.team_orchestration_service.get_enabled_mcp_tools",
        _fake_get_enabled_mcp_tools,
    )

    result = asyncio.run(service.query_langchain_docs("langgraph multi-agent"))

    assert result["tool"] == "search_docs"
    assert result["result"]["ok"] is True
    assert result["result"]["args"]["query"] == "langgraph multi-agent"
