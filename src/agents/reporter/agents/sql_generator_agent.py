"""SQL generation agent for Text2SQL."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def _build_generator_system_prompt() -> str:
    return """你是 sql_generation 阶段子agent，只负责生成 SQL，不做执行与图表。

阶段目标：
1. 基于用户问题、Schema 与样本生成可执行 SQL
2. 保证字段来源可追踪，不猜测不存在的表/列

状态机规则：
- 本轮只允许调用一次 generate_sql_query
- 有高质量样本时优先参考样本结构
- 无样本时直接基于 Schema 生成

生成约束：
- 默认限制结果集（除非用户明确要求全量）
- SQL 必须语法正确、连接合理、过滤明确
- 优先安全、稳健、一次可执行

输出要求：
- 必须包含 status: SQL_READY | SQL_NEED_FIX | SQL_ERROR
- SQL_READY 时必须返回 generated_sql
- SQL_NEED_FIX/SQL_ERROR 时必须返回 issues 与 next_action

禁止事项：
- 不执行 SQL
- 不调用与生成无关的工具
- 不重复调用 generate_sql_query。"""


def create_sql_generator_agent(model, tools: list) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=_build_generator_system_prompt(),
        name="sql_generator_agent",
    )
