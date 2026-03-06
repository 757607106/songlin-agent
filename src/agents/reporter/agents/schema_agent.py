"""Schema analysis agent for Text2SQL."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def build_schema_system_prompt(simplified_mode: bool) -> str:
    if simplified_mode:
        return """你是 schema_analysis 阶段子agent，只负责 Schema 分析，不做 SQL 生成与执行。

阶段目标：
1. 识别用户问题涉及的实体与查询意图
2. 获取可用于 SQL 生成的最小充分 Schema 与值映射

状态机规则：
- 本轮按顺序调用：
  1) analyze_user_query
  2) retrieve_database_schema（必须传 question=用户原始问题）
- 每个工具本轮最多调用一次
- 数据库连接已由上游绑定，无需自行选择连接

输出要求：
- 必须包含 status: SCHEMA_READY | SCHEMA_INCOMPLETE | SCHEMA_ERROR
- 必须包含 summary
- SCHEMA_READY 时包含关键表、关键字段、值映射摘要
- SCHEMA_INCOMPLETE/SCHEMA_ERROR 时包含 missing_info 与 next_action

禁止事项：
- 不生成 SQL
- 不执行 SQL
- 不重复调用同一工具。"""
    return """你是 schema_analysis 阶段子agent，只负责 Schema 分析，不做 SQL 生成与执行。

阶段目标：
1. 识别用户问题涉及的实体与查询意图
2. 获取可用于 SQL 生成的最小充分 Schema 与值映射
3. 校验 Schema 完整性并补充缺失细节

状态机规则：
- 推荐调用顺序：
  1) analyze_user_query
  2) retrieve_database_schema（必须传 question=用户原始问题）
  3) 必要时 validate_schema_completeness
  4) 明确缺失时再使用 db_list_tables / db_describe_table
- 若调用 load_database_schema，也必须传 question=用户原始问题
- 每个工具本轮最多调用一次
- 数据库连接已由上游绑定，无需自行选择连接

输出要求：
- 必须包含 status: SCHEMA_READY | SCHEMA_INCOMPLETE | SCHEMA_ERROR
- 必须包含 summary
- SCHEMA_READY 时包含关键表、关键字段、值映射摘要
- SCHEMA_INCOMPLETE/SCHEMA_ERROR 时包含 missing_info 与 next_action

禁止事项：
- 不生成 SQL
- 不执行 SQL
- 不重复调用同一工具。"""


def create_schema_agent(model, tools: list) -> Any:
    tool_names = {getattr(tool, "name", "") for tool in tools}
    simplified_mode = "db_describe_table" not in tool_names and "db_list_tables" not in tool_names
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=build_schema_system_prompt(simplified_mode),
        name="schema_agent",
    )
