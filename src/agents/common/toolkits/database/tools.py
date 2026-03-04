"""通用数据库工具 — 支持多数据库类型 (MySQL / PostgreSQL / Oracle / MSSQL / SQLite)

使用 langchain_community.utilities.SQLDatabase 实现，
工具在构建时绑定到特定的 DatabaseConnectionManager 实例。
"""

from __future__ import annotations

from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field

from src.utils import logger

from .connection import DatabaseConnectionManager
from .security import SQLSecurityChecker

# ---------- Pydantic 参数模型 ----------


class EmptyModel(BaseModel):
    """无参数模型"""

    pass


class TableDescribeModel(BaseModel):
    """描述表结构的参数模型"""

    table_name: str = Field(description="要查询结构的表名")


class QueryModel(BaseModel):
    """执行 SQL 查询的参数模型"""

    sql: str = Field(description="要执行的 SQL 查询语句（只允许 SELECT / SHOW / DESCRIBE / EXPLAIN）")
    timeout: int | None = Field(default=60, description="查询超时时间（秒），默认 60 秒，最大 600 秒", ge=1, le=600)


# ---------- 工具工厂函数 ----------


def get_database_tools(db_type: str, config: dict[str, Any]) -> list:
    """根据数据库类型和配置，返回绑定到特定连接的数据库工具列表

    Args:
        db_type: 数据库类型 (mysql / postgresql / oracle / mssql / sqlite)
        config: 数据库连接配置 dict

    Returns:
        list: 绑定到该数据库连接的工具列表
    """
    conn_manager = DatabaseConnectionManager.get_instance(db_type, config)

    @tool(name_or_callable="db_list_tables", args_schema=EmptyModel)
    def db_list_tables() -> str:
        """【查询表名】获取数据库中的所有表名。

        列出当前连接的数据库中所有可用的表名，帮助了解数据库结构。
        """
        try:
            table_names = conn_manager.get_usable_table_names()
            if not table_names:
                return "数据库中没有找到任何表"

            result = f"数据库中的表（共 {len(table_names)} 个）:\n"
            result += "\n".join(f"- {name}" for name in sorted(table_names))

            description = config.get("description")
            if description:
                result = f"数据库说明: {description}\n\n{result}"

            logger.info(f"Retrieved {len(table_names)} tables from {db_type} database")
            return result
        except Exception as e:
            error_msg = f"获取表名失败: {e}"
            logger.error(error_msg)
            return error_msg

    @tool(name_or_callable="db_describe_table", args_schema=TableDescribeModel)
    def db_describe_table(table_name: str) -> str:
        """【描述表结构】获取指定表的详细结构信息（字段、类型、索引等）。

        查看表的字段信息、数据类型等，以便编写正确的 SQL 查询。
        """
        try:
            if not SQLSecurityChecker.validate_table_name(table_name):
                return "表名包含非法字符，请检查表名"

            db = conn_manager.get_db()
            # 利用 SQLDatabase 获取指定表的 schema 信息
            info = db.get_table_info(table_names=[table_name])
            if not info or not info.strip():
                return f"表 {table_name} 不存在或没有字段"

            logger.info(f"Retrieved structure for table {table_name}")
            return f"表 `{table_name}` 的结构:\n\n{info}"
        except Exception as e:
            error_msg = f"获取表 {table_name} 结构失败: {e}"
            logger.error(error_msg)
            return error_msg

    @tool(name_or_callable="db_execute_query", args_schema=QueryModel)
    def db_execute_query(sql: str, timeout: int | None = 60) -> str:
        """【执行 SQL 查询】执行只读的 SQL 查询语句并返回结果。

        支持 SELECT、SHOW、DESCRIBE、EXPLAIN 等只读操作。
        不能执行修改数据的操作。
        """
        try:
            if timeout is not None and not SQLSecurityChecker.validate_timeout(timeout):
                return "timeout 参数必须在 1-600 之间"

            # 执行查询
            result = conn_manager.run_query(sql)

            if not result or result.strip() == "":
                return "查询执行成功，但没有返回任何结果"

            # 限制结果长度
            max_chars = 10000
            if len(result) > max_chars:
                result = result[:max_chars]
                result += "\n\n⚠️ 结果过长，已截断。请使用 LIMIT 子句或更精确的条件减少返回数据量。"

            logger.info(f"Query executed successfully on {db_type} database")
            return f"查询结果:\n\n{result}"

        except Exception as e:
            error_msg = f"SQL 查询执行失败: {e}\n\nSQL: {sql}"

            # 提供有用的错误提示
            err_str = str(e).lower()
            if "timeout" in err_str:
                error_msg += "\n\n💡 建议: 查询超时，请减少数据量或增加超时时间"
            elif "table" in err_str and ("doesn't exist" in err_str or "does not exist" in err_str):
                error_msg += "\n\n💡 建议: 表不存在，请使用 db_list_tables 查看可用表名"
            elif "column" in err_str and ("doesn't exist" in err_str or "does not exist" in err_str):
                error_msg += "\n\n💡 建议: 列不存在，请使用 db_describe_table 查看表结构"

            logger.error(error_msg)
            return error_msg

    return [db_list_tables, db_describe_table, db_execute_query]
