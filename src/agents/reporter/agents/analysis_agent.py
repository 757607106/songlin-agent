"""Result analysis agent for reporter workflow."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def build_analysis_system_prompt(system_prompt: str) -> str:
    base_prompt = """你是结果分析子agent，负责将查询结果转化为业务洞察。

输出要求：
- status: ANALYSIS_READY | ANALYSIS_SKIPPED | ANALYSIS_ERROR
- summary: 一句话结论
- insights: 关键洞察列表
- risks: 风险与不确定性
- next_actions: 下一步建议"""
    custom_prompt = (system_prompt or "").strip()
    if not custom_prompt:
        return base_prompt
    return f"{base_prompt}\n\n补充业务分析要求：\n{custom_prompt}"


def create_analysis_agent(model, tools: list, system_prompt: str) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=build_analysis_system_prompt(system_prompt),
        name="analysis_agent",
    )
