"""模拟用户截图中的实际场景"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.team_orchestration_service import TeamOrchestrationService


def test_user_screenshot_scenario():
    """模拟用户截图中的场景"""
    service = TeamOrchestrationService()
    
    print("=" * 70)
    print("模拟用户截图场景")
    print("=" * 70)
    
    # 场景: 用户从空草稿开始，逐步回答
    draft = {}
    
    # Step 1: 系统先问 team_goal
    print("\n[初始状态] 空草稿")
    result = service.wizard_step("", draft)
    print(f"系统: {result['assistant_message']}")
    print(f"questions: {result['questions']}")
    draft = result["draft"]
    print(f"draft: {draft}")
    
    # Step 2: 用户点"确认"（空草稿时）
    print("\n[用户] 确认")
    result = asyncio.run(service.wizard_step_with_ai("确认", draft))
    print(f"系统: {result['assistant_message']}")
    print(f"questions: {result['questions']}")
    draft = result["draft"]
    print(f"draft.team_goal: {draft.get('team_goal')}")
    print(f"draft.task_scope: {draft.get('task_scope')}")
    
    # Step 3: 用户回答"智能客服"
    print("\n[用户] 智能客服")
    result = asyncio.run(service.wizard_step_with_ai("智能客服", draft))
    print(f"系统: {result['assistant_message']}")
    print(f"questions: {result['questions']}")
    draft = result["draft"]
    print(f"draft.team_goal: {draft.get('team_goal')}")
    print(f"draft.task_scope: {draft.get('task_scope')}")
    
    # Step 4: 用户回答更详细的描述
    print("\n[用户] 物流查询，根据知识库内容进行回复用户的问题")
    result = asyncio.run(service.wizard_step_with_ai("物流查询，根据知识库内容进行回复用户的问题", draft))
    print(f"系统: {result['assistant_message']}")
    print(f"questions: {result['questions']}")
    draft = result["draft"]
    print(f"draft.team_goal: {draft.get('team_goal')}")
    print(f"draft.task_scope: {draft.get('task_scope')}")
    
    # Step 5: 用户回答"售前"
    print("\n[用户] 售前")
    result = asyncio.run(service.wizard_step_with_ai("售前", draft))
    print(f"系统: {result['assistant_message']}")
    print(f"questions: {result['questions']}")
    draft = result["draft"]
    print(f"draft.team_goal: {draft.get('team_goal')}")
    print(f"draft.task_scope: {draft.get('task_scope')}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_user_screenshot_scenario()
