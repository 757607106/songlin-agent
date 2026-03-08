"""测试 wizard_step_with_ai 流程"""

from __future__ import annotations

import asyncio
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.team_orchestration_service import TeamOrchestrationService


def test_customer_support_team_request():
    """测试：用户说 '我需要一个客服支持团队'"""
    service = TeamOrchestrationService()

    # 模拟用户第一次消息
    message = "我需要一个客服支持团队"

    result = asyncio.run(service.wizard_step_with_ai(message, {}))

    print("=" * 60)
    print(f"用户消息: {message}")
    print(f"is_complete: {result['is_complete']}")
    print(f"assistant_message: {result['assistant_message']}")
    print(f"questions: {result['questions']}")
    print(f"draft team_goal: {result['draft'].get('team_goal')}")
    print(f"draft multi_agent_mode: {result['draft'].get('multi_agent_mode')}")
    print(f"draft subagents count: {len(result['draft'].get('subagents', []))}")
    print("=" * 60)

    assert result["draft"].get("team_goal"), "team_goal should be set"
    assert result["draft"].get("multi_agent_mode") == "swarm", "should use swarm mode for customer support"
    assert result["draft"].get("subagents"), "subagents should be set"


def test_confirm_message():
    """测试：用户点击确认（用完整草稿）"""
    service = TeamOrchestrationService()

    # Step 1: 先获取完整草稿
    step1 = asyncio.run(service.wizard_step_with_ai("我需要一个客服支持团队", {}))
    print("=" * 60)
    print(f"Step 1 - 获取完整草稿: is_complete={step1['is_complete']}")

    # Step 2: 用户点击确认
    message = "确认"
    result = asyncio.run(service.wizard_step_with_ai(message, step1["draft"]))

    print(f"\nStep 2 - 用户消息: {message}")
    print(f"is_complete: {result['is_complete']}")
    print(f"assistant_message: {result['assistant_message']}")
    print(f"questions: {result['questions']}")
    print("=" * 60)

    # 确认消息应该保持草稿完整
    assert result["is_complete"] is True, f"Expected is_complete=True but got {result['is_complete']}"
    assert result["draft"].get("team_goal"), "team_goal should be preserved"


def test_natural_language_goal():
    """测试：用户用自然语言描述目标"""
    service = TeamOrchestrationService()

    # 当系统问 "请先告诉我团队整体目标" 时，用户回答的自然语言
    existing_draft = {"multi_agent_mode": "swarm"}  # 没有 team_goal
    message = "为客户提供7x24小时的技术支持服务"

    result = asyncio.run(service.wizard_step_with_ai(message, existing_draft))

    print("=" * 60)
    print(f"用户消息: {message}")
    print(f"is_complete: {result['is_complete']}")
    print(f"assistant_message: {result['assistant_message']}")
    print(f"draft team_goal: {result['draft'].get('team_goal')}")
    print("=" * 60)

    # 自然语言目标应该被解析
    assert result["draft"].get("team_goal"), "team_goal should be parsed from natural language"


def test_step_by_step_flow():
    """测试：模拟完整的对话流程"""
    service = TeamOrchestrationService()

    print("\n" + "=" * 60)
    print("模拟完整对话流程")
    print("=" * 60)

    # Step 1: 用户发起请求
    step1_result = asyncio.run(service.wizard_step_with_ai("我需要一个客服支持团队", {}))
    print("\nStep 1 - 用户: '我需要一个客服支持团队'")
    print(f"  is_complete: {step1_result['is_complete']}")
    print(f"  assistant: {step1_result['assistant_message'][:100]}...")

    if step1_result["is_complete"]:
        print("  ✓ 团队创建已完成！")
        return

    # Step 2: 如果有问题，用户回答
    if step1_result["questions"]:
        print(f"  questions: {step1_result['questions']}")

        # 模拟用户确认
        step2_result = asyncio.run(service.wizard_step_with_ai("确认", step1_result["draft"]))
        print("\nStep 2 - 用户: '确认'")
        print(f"  is_complete: {step2_result['is_complete']}")
        print(f"  assistant: {step2_result['assistant_message'][:100]}...")


if __name__ == "__main__":
    print("Testing customer support team request...")
    test_customer_support_team_request()

    print("\nTesting confirm message...")
    test_confirm_message()

    print("\nTesting natural language goal...")
    test_natural_language_goal()

    print("\nTesting step by step flow...")
    test_step_by_step_flow()

    print("\n✓ All tests passed!")
