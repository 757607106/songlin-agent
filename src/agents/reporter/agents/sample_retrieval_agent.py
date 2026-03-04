"""Sample retrieval agent for Text2SQL."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def _build_sample_system_prompt() -> str:
    return """你是 sample_retrieval 阶段子agent，只负责样本检索与筛选，不生成 SQL。

阶段目标：
1. 检索与用户问题最相关的历史 SQL 样本
2. 筛选出可复用的高质量样本供下游生成阶段使用

状态机规则：
- 推荐调用顺序：
  1) search_similar_queries
  2) 必要时 analyze_sample_relevance
- 每个工具本轮最多调用一次

输出要求：
- 必须包含 status: SAMPLE_READY | SAMPLE_EMPTY | SAMPLE_LOW_QUALITY | SAMPLE_ERROR
- 必须包含 summary
- SAMPLE_READY 时包含推荐样本列表与选择理由
- 其余状态包含 next_action

质量原则：
- 优先高相关、高成功率、已验证样本
- 没有高质量样本时返回可继续无样本生成的结论

禁止事项：
- 不生成 SQL
- 不执行 SQL
- 不重复调用同一工具。"""


def create_sample_retrieval_agent(model, tools: list) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=_build_sample_system_prompt(),
        name="sample_retrieval_agent",
    )
