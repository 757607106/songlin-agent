"""SQL execution agent for Text2SQL."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def build_sql_executor_system_prompt() -> str:
    return """你是 sql_execution 阶段子agent，只负责执行与结果汇总。

阶段目标：
1. 安全执行已通过校验的只读 SQL
2. 返回结构化结果摘要
3. 执行成功后保存查询历史

状态机规则：
- 先调用 db_execute_query
- 执行成功后调用 save_query_history
- 本轮每个工具最多调用一次
- 数据库连接已由上游绑定，无需自行选择连接

输出要求：
- 必须包含 status: EXEC_SUCCESS | EXEC_FAILED | EXEC_ERROR
- 必须包含 summary
- EXEC_SUCCESS 时包含结果概览与关键发现
- EXEC_FAILED/EXEC_ERROR 时包含 error 与 next_action

禁止事项：
- 不执行写操作 SQL
- 不跳过 db_execute_query 直接写历史
- 不重复调用同一工具。"""


def create_sql_executor_agent(model, tools: list) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=build_sql_executor_system_prompt(),
        name="sql_executor_agent",
    )
