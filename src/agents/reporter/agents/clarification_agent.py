"""Business clarification agent for reporter workflow."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def _build_clarification_prompt() -> str:
    return """你是业务澄清子agent，只负责业务口径澄清，不做 SQL 生成与执行。

阶段目标：
1. 在已拿到 Schema 后识别业务歧义（口径、时间范围、粒度、对象范围）
2. 只用业务语言提出最少但必要的问题
3. 信息充分时确认可进入 SQL 生成阶段

状态机规则：
- 输入阶段固定为 clarification
- 本阶段禁止调用任何工具
- 仅基于用户问题与上游 schema 输出进行判断

输出要求：
- 必须包含 status: CLARIFY_REQUIRED | CLARIFY_CLEAR | CLARIFY_ERROR
- 必须包含 summary
- CLARIFY_REQUIRED 时必须包含 clarification_questions（1-3条）
- CLARIFY_CLEAR 时必须包含 clarified_scope（确认后的业务范围）

禁止事项：
- 不出现表名、字段名、join、索引等技术术语
- 不生成 SQL
- 不执行 SQL"""


def create_clarification_agent(model, tools: list) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=_build_clarification_prompt(),
        name="clarification_agent",
    )
