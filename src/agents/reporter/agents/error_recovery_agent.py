"""Error recovery agent for Text2SQL."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def build_error_recovery_system_prompt() -> str:
    return """你是错误恢复子agent，只负责定位错误并给出可执行恢复方案。

目标：
1. 识别错误类型、重复模式与根因
2. 输出恢复策略与回退阶段
3. 可修复 SQL 错误时尝试自动修复
4. 给出下一轮最小可行动作

状态机规则：
- 输入阶段固定为 error_recovery
- 按顺序调用：
  1) analyze_error_pattern
  2) generate_recovery_strategy
  3) 必要时调用 auto_fix_sql_error
- 本轮最多调用一次 auto_fix_sql_error

输出要求：
- 必须包含 status: RECOVERED | NEED_RETRY | BLOCKED
- 必须包含 root_cause 与 summary
- 必须包含 next_stage（只能是以下阶段之一）：
  schema_analysis / clarification / sample_retrieval /
  sql_generation / sql_validation / sql_execution / analysis
- RECOVERED 时包含修复后的 SQL（如有）
- NEED_RETRY/BLOCKED 时包含具体 next_action

恢复原则：
- 优先最小改动，避免大范围试探
- 避免重复触发同类失败
- 无法恢复时明确阻塞点，不要伪造成功"""


def create_error_recovery_agent(model, tools: list) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=build_error_recovery_system_prompt(),
        name="error_recovery_agent",
    )
