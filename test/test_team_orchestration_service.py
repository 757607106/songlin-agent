from __future__ import annotations

import asyncio
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
                "skills": ["planner-skill"],
                "depends_on": [],
                "max_retries": 1,
            },
            {
                "name": "researcher",
                "description": "检索外部信息并汇总证据",
                "system_prompt": "你负责检索并输出证据。",
                "depends_on": ["planner"],
                "knowledges": ["kb_a"],
                "skills": ["research-skill"],
                "max_retries": 2,
            },
            {
                "name": "writer",
                "description": "汇总并撰写最终报告",
                "system_prompt": "你负责整合结论并输出报告。",
                "depends_on": ["researcher"],
                "skills": ["writer-skill"],
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
    assert result["assembly_meta"]["pipeline"] == "manual_parse"


def test_wizard_step_reports_missing_required_fields():
    service = TeamOrchestrationService()
    result = service.wizard_step("目标: 做一个多agent团队")

    assert result["is_complete"] is False
    assert result["questions"]
    assert "任务范围" in result["questions"][0] or "子Agent" in "".join(result["questions"])


def test_wizard_step_with_ai_autofills_dev_team():
    """Test that AI generates a development team with deep_agents mode.

    Note: AI-generated agent names may vary, so we only check:
    - Team is complete
    - Mode is deep_agents
    - Has at least 3 subagents
    """
    service = TeamOrchestrationService()
    result = asyncio.run(service.wizard_step_with_ai("帮我组建一个 DeepAgents 需求开发团队"))

    assert result["is_complete"] is True
    draft = result["draft"]
    assert draft["multi_agent_mode"] == "deep_agents"
    # AI should generate at least 3 subagents for a dev team
    assert len(draft["subagents"]) >= 3, f"Expected at least 3 subagents, got {len(draft['subagents'])}"
    # Each subagent should have required fields
    for sa in draft["subagents"]:
        assert sa.get("name"), "Each subagent should have a name"
        assert sa.get("description") or sa.get("system_prompt"), (
            "Each subagent should have description or system_prompt"
        )


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

    monkeypatch.setattr(service, "_generate_team_patch_with_llm", _fake_llm)

    result = asyncio.run(service.wizard_step_with_ai("帮我组建一个法务审查团队"))

    assert result["is_complete"] is True
    assert result["draft"]["subagents"][0]["name"] == "legal_reviewer"


def test_wizard_step_with_ai_uses_blueprint_pipeline(monkeypatch):
    service = TeamOrchestrationService()

    async def _fake_blueprint(message: str, current_team: dict):
        assert "采购" in message
        _ = current_team
        return {
            "team_goal": "完成采购合规审查",
            "task_scope": "覆盖供应商准入与合同条款审核",
            "complexity_level": "high",
            "workstreams": [
                {
                    "id": "ws_requirements",
                    "objective": "明确采购需求",
                    "depends_on": [],
                    "required_capabilities": ["需求分析"],
                    "deliverables": ["requirements.md"],
                },
                {
                    "id": "ws_compliance",
                    "objective": "执行合规审查",
                    "depends_on": ["ws_requirements"],
                    "required_capabilities": ["合规审查"],
                    "deliverables": ["compliance_report.md"],
                },
            ],
        }

    async def _fake_from_blueprint(
        message: str,
        current_team: dict,
        *,
        blueprint: dict,
        available_resources: dict | None = None,
    ):
        assert "采购" in message
        _ = current_team
        assert blueprint.get("workstreams")
        assert available_resources is not None
        return {
            "team_goal": "完成采购合规审查",
            "task_scope": "覆盖供应商准入与合同条款审核",
            "multi_agent_mode": "supervisor",
            "subagents": [
                {
                    "name": "procurement_analyst",
                    "description": "负责采购需求分析",
                    "system_prompt": "负责需求澄清与供应商信息收集。",
                    "depends_on": [],
                    "communication_mode": "sync",
                    "tools": ["calculator"],
                    "skills": ["analysis_skill"],
                },
                {
                    "name": "compliance_reviewer",
                    "description": "负责合规审查",
                    "system_prompt": "负责合同与流程合规检查。",
                    "depends_on": ["procurement_analyst"],
                    "communication_mode": "sync",
                    "skills": ["compliance_skill"],
                },
            ],
        }

    async def _should_not_call(*_args, **_kwargs):
        raise AssertionError("fallback llm patch should not be called")

    monkeypatch.setattr(service, "_build_task_blueprint_with_llm", _fake_blueprint)
    monkeypatch.setattr(service, "_generate_team_patch_from_blueprint_with_llm", _fake_from_blueprint)
    monkeypatch.setattr(service, "_generate_team_patch_with_llm", _should_not_call)

    result = asyncio.run(
        service.wizard_step_with_ai(
            "帮我组建一个采购合规团队",
            {},
            available_resources={
                "tools": ["calculator", "search_docs"],
                "skills": ["analysis_skill", "compliance_skill"],
            },
        )
    )

    assert result["is_complete"] is True
    assert result["draft"]["multi_agent_mode"] == "supervisor"
    assert len(result["draft"]["subagents"]) == 2
    assert result["assembly_meta"]["pipeline"] == "ai_blueprint_pipeline"
    assert result["assembly_meta"]["status"] == "completed"
    assert result["assembly_meta"]["attempts"]


def test_wizard_step_with_ai_has_no_builtin_template_fallback(monkeypatch):
    service = TeamOrchestrationService()

    async def _empty_llm(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(service, "_generate_team_patch_with_llm", _empty_llm)

    result = asyncio.run(service.wizard_step_with_ai("我需要一个开发团队"))

    assert not hasattr(service, "_build_builtin_team_patch")
    assert result["is_complete"] is False
    assert result["questions"]
    assert result["assembly_meta"]["pipeline"] == "ai_blueprint_pipeline"


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
    runtime = service.build_runtime_context(
        _sample_team("deep_agents"),
        strict=True,
        assembly_meta={
            "pipeline": "ai_blueprint_pipeline",
            "status": "completed",
            "attempts": [{"attempt": 1, "patch_source": "blueprint"}],
            "mode_alignment_events": [],
            "latest_blueprint": {"workstream_count": 3, "complexity_level": "high"},
        },
        mode_recommendation={
            "recommended_mode": "deep_agents",
            "is_selected_mode_recommended": True,
        },
    )

    assert runtime["multi_agent_mode"] == "deep_agents"
    assert runtime["team_policy"]["execution_groups"]
    assert "OpenClaw" in runtime["system_prompt"]
    assert runtime["subagents"][1]["depends_on"] == ["planner"]
    assert runtime["subagents"][0]["skills"] == ["planner-skill"]
    assert runtime["team_policy"]["mode_recommendation"]["recommended_mode"] == "deep_agents"
    assert runtime["team_policy"]["runtime_audit"]["build_source"] == "ai_blueprint_pipeline"
    assert runtime["team_policy"]["runtime_audit"]["blueprint_summary"]["workstream_count"] == 3


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


def test_validate_team_blocks_unknown_resources():
    service = TeamOrchestrationService()
    team = _sample_team("deep_agents")
    team["subagents"][0]["tools"] = ["calculator", "unknown_tool"]
    team["subagents"][1]["knowledges"] = ["kb_a", "kb_unknown"]
    team["subagents"][2]["mcps"] = ["mcp-known", "mcp-unknown"]
    team["skills"] = ["team-skill", "unknown-skill"]

    check = service.validate_team(
        team,
        strict=True,
        available_resources={
            "tools": ["calculator"],
            "knowledges": ["kb_a"],
            "mcps": ["mcp-known"],
            "skills": ["team-skill", "planner-skill", "research-skill", "writer-skill"],
        },
    )

    assert check["valid"] is False
    assert "unknown_tool" in " ".join(check["errors"])
    assert check["resource_validation"]["valid"] is False
    assert "kb_unknown" in check["resource_validation"]["invalid"]["knowledges"]
    assert "unknown-skill" in check["resource_validation"]["invalid"]["skills"]


def test_wizard_mode_recommendation_prefers_supervisor_for_observability():
    service = TeamOrchestrationService()
    result = service.wizard_step("我需要一个可观测且可审计的多智能体团队")
    recommendation = result["mode_recommendation"]
    assert recommendation["recommended_mode"] == "supervisor"


def test_wizard_mode_recommendation_prefers_deep_agents_for_parallel():
    service = TeamOrchestrationService()
    result = service.wizard_step("请帮我搭建并行高吞吐的多智能体团队")
    recommendation = result["mode_recommendation"]
    assert recommendation["recommended_mode"] == "deep_agents"
