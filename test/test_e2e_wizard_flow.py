"""端到端契约测试 wizard_step_with_ai（不依赖真实模型调用）"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.team_orchestration_service import TeamOrchestrationService


def _build_team_patch_for_message(message: str) -> dict:
    text = (message or "").lower()

    if "客服" in text or "support" in text:
        return {
            "team_goal": "提供客户支持",
            "task_scope": "仅覆盖售前咨询与售后答疑",
            "multi_agent_mode": "swarm",
            "subagents": [
                {
                    "name": "general_support",
                    "description": "处理通用咨询并转派",
                    "system_prompt": "负责一线客服响应。",
                    "depends_on": [],
                    "communication_mode": "sync",
                },
                {
                    "name": "tech_support",
                    "description": "处理技术问题",
                    "system_prompt": "负责技术排查与答复。",
                    "depends_on": [],
                    "communication_mode": "sync",
                },
            ],
        }

    if "开发" in text or "deepagents" in text or "deep_agents" in text:
        return {
            "team_goal": "完成软件需求开发",
            "task_scope": "覆盖需求澄清、开发、测试",
            "multi_agent_mode": "deep_agents",
            "subagents": [
                {
                    "name": "planner",
                    "description": "任务拆解",
                    "system_prompt": "负责计划制定。",
                    "depends_on": [],
                    "communication_mode": "sync",
                },
                {
                    "name": "engineer",
                    "description": "实现与联调",
                    "system_prompt": "负责编码实现。",
                    "depends_on": ["planner"],
                    "communication_mode": "hybrid",
                },
            ],
        }

    if "数据分析" in text:
        return {
            "team_goal": "完成数据分析与洞察输出",
            "task_scope": "覆盖清洗、分析、报告",
            "multi_agent_mode": "supervisor",
            "subagents": [
                {
                    "name": "data_engineer",
                    "description": "数据清洗",
                    "system_prompt": "负责数据预处理。",
                    "depends_on": [],
                    "communication_mode": "sync",
                },
                {
                    "name": "analyst",
                    "description": "分析与报告",
                    "system_prompt": "负责分析结论输出。",
                    "depends_on": ["data_engineer"],
                    "communication_mode": "sync",
                },
            ],
        }

    if "内容创作" in text:
        return {
            "team_goal": "完成内容创作",
            "task_scope": "覆盖策划、写作、编辑",
            "multi_agent_mode": "deep_agents",
            "subagents": [
                {
                    "name": "strategist",
                    "description": "选题策划",
                    "system_prompt": "负责内容规划。",
                    "depends_on": [],
                    "communication_mode": "sync",
                },
                {
                    "name": "writer",
                    "description": "写作输出",
                    "system_prompt": "负责正文创作。",
                    "depends_on": ["strategist"],
                    "communication_mode": "hybrid",
                },
            ],
        }

    # 模糊请求只返回部分字段，验证系统会继续追问而不是误判完整
    return {"team_goal": "待明确的团队目标"}


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> TeamOrchestrationService:
    svc = TeamOrchestrationService()

    async def _fake_llm(message: str, current_team: dict) -> dict:
        _ = current_team
        return _build_team_patch_for_message(message)

    monkeypatch.setattr(svc, "_generate_team_patch_with_llm", _fake_llm)
    return svc


@pytest.mark.asyncio
async def test_full_interaction_flow(service: TeamOrchestrationService):
    # 场景 1: 一句话创建团队
    result1 = await service.wizard_step_with_ai("我需要一个客服支持团队", {})
    assert result1["is_complete"] is True
    assert result1["draft"]["multi_agent_mode"] == "swarm"
    assert len(result1["draft"]["subagents"]) >= 2

    # 场景 2: 确认消息应保持完整草稿
    result2 = await service.wizard_step_with_ai("确认", result1["draft"])
    assert result2["is_complete"] is True
    assert result2["draft"]["multi_agent_mode"] == "swarm"

    # 场景 3: 模糊需求应继续追问
    result3 = await service.wizard_step_with_ai("帮我组建一个团队", {})
    assert result3["is_complete"] is False
    assert result3["questions"]

    # 场景 4: 不同类型团队（契约断言，不依赖真实模型随机性）
    team_types = [
        ("客服团队", "swarm"),
        ("开发团队", "deep_agents"),
        ("数据分析团队", "supervisor"),
        ("内容创作团队", "deep_agents"),
    ]
    for keyword, expected_mode in team_types:
        r = await service.wizard_step_with_ai(f"我需要一个{keyword}", {})
        assert r["is_complete"] is True
        assert r["draft"]["multi_agent_mode"] == expected_mode
