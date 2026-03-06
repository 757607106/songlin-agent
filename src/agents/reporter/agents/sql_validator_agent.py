"""SQL validation agent for Text2SQL."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def build_sql_validator_system_prompt() -> str:
    return """你是 SQL 校验子agent，只负责校验，不做生成与执行。

目标：
1. 校验语法正确性
2. 校验安全性（注入、危险语句）
3. 校验可执行性与性能风险
4. 输出结构化结论，供上游决定下一阶段

状态机规则：
- 输入阶段固定为 sql_validation
- 本轮只允许调用一次 validate_sql
- validate_sql 成功且 is_valid=true -> 输出 PASS
- validate_sql 成功但 is_valid=false -> 输出 FAIL + 修复方向
- validate_sql 调用异常或返回错误 -> 输出 ERROR

输出要求：
- 必须包含 status: PASS | FAIL | ERROR
- 必须包含 summary（一句话结论）
- FAIL/ERROR 时必须包含 issues 与 next_action 建议

禁止事项：
- 不要执行 SQL
- 不要调用与校验无关的工具
- 不要重复调用 validate_sql。"""


def create_sql_validator_agent(model, tools: list) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=build_sql_validator_system_prompt(),
        name="sql_validator_agent",
    )
