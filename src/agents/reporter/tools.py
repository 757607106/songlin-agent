"""Reporter Agent 专用工具集 — 通过工厂函数动态创建绑定到特定数据库连接的工具

工具列表:
1. db_list_tables / db_describe_table / db_execute_query — 数据库操作（来自通用 toolkit）
2. load_database_schema — 加载持久化 Schema + 值映射
3. search_similar_queries — 检索相似历史查询
4. validate_sql — 验证 SQL 语法、安全性、性能
5. save_query_history — 保存成功的查询记录
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import time

import sqlparse
from langchain.tools import tool
from pydantic import BaseModel, Field

from src.agents.common import load_chat_model
from src.agents.common.toolkits.database.security import SQLSecurityChecker
from src.utils import logger

SCHEMA_TRIM_THRESHOLD = 30

# 模块级缓存：存储每个 connection_id 对应的 Schema 和值映射
_schema_cache: dict[int, tuple[list, dict]] = {}
_STAGE_CACHE_MAX = 128


def _hash_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _cache_put(cache: dict[str, dict], key: str, value: dict) -> None:
    cache[key] = value
    while len(cache) > _STAGE_CACHE_MAX:
        cache.pop(next(iter(cache)))


def _is_simple_query(question: str) -> bool:
    text = (question or "").strip().lower()
    if not text:
        return False
    complex_markers = ["join", "子查询", "union", "窗口", "over(", "同比", "环比", "排名前", "rank"]
    if any(marker in text for marker in complex_markers):
        return False
    simple_markers = ["统计", "数量", "总数", "count", "sum", "avg", "按", "group by", "汇总"]
    return any(marker in text for marker in simple_markers) and len(text) <= 60


# ---------- Pydantic 参数模型 ----------


class SchemaInput(BaseModel):
    question: str = Field(description="用户的查询问题，用于智能筛选相关表")


class AnalyzeQueryInput(BaseModel):
    question: str = Field(description="用户的查询问题，用于分析意图与相关实体")


class SimilarQueryInput(BaseModel):
    question: str = Field(description="当前用户问题，用于语义检索相似的历史查询")


class SampleRelevanceInput(BaseModel):
    question: str = Field(description="当前用户问题")
    qa_pairs: list[dict] = Field(default_factory=list, description="候选样本列表")


class ValidateSqlInput(BaseModel):
    sql: str = Field(description="需要验证的 SQL 语句")


class SaveQueryInput(BaseModel):
    question: str = Field(description="用户的原始问题")
    sql: str = Field(description="成功执行的 SQL 语句")


class SchemaCompletenessInput(BaseModel):
    schema_info: dict = Field(description="Schema 信息")
    query_analysis: dict = Field(description="查询分析结果")


class ErrorPatternInput(BaseModel):
    error_history: list[dict] = Field(description="错误历史记录")


class RecoveryStrategyInput(BaseModel):
    error_analysis: dict = Field(description="错误分析结果")
    current_state: dict = Field(description="当前状态信息")


class AutoFixInput(BaseModel):
    sql: str = Field(description="原始 SQL")
    error_message: str = Field(description="错误信息")
    schema_info: dict | None = Field(default=None, description="Schema 信息")


class GenerateSqlInput(BaseModel):
    user_query: str = Field(description="用户的自然语言问题")
    schema_info: dict = Field(description="Schema 信息")
    value_mappings: dict | None = Field(default=None, description="值映射信息")
    sample_qa_pairs: list[dict] | None = Field(default=None, description="相似样本")
    db_type: str | None = Field(default=None, description="数据库类型")


# ---------- 值映射后处理（复用老项目正则逻辑） ----------


def process_sql_with_value_mappings(sql: str, value_mappings: dict[str, dict[str, str]]) -> str:
    """处理 SQL 查询，将自然语言术语替换为数据库值

    复用老项目的 4 种正则模式：
    1. table.column = 'nl_term' → 'db_value'
    2. column = 'nl_term' → 'db_value'
    3. table.column LIKE '%nl_term%' → '%db_value%'
    4. column LIKE '%nl_term%' → '%db_value%'
    """
    if not value_mappings:
        return sql

    for column_key, mappings in value_mappings.items():
        if "." in column_key:
            table, col = column_key.split(".", 1)
        else:
            table, col = "", column_key

        for nl_term, db_value in mappings.items():
            # 模式 1: table.column = 'nl_term'
            if table:
                pattern1 = rf"({re.escape(table)}\.{re.escape(col)}\s*=\s*['\"])({re.escape(nl_term)})(['\"])"
                sql = re.sub(pattern1, rf"\g<1>{db_value}\g<3>", sql, flags=re.IGNORECASE)

            # 模式 2: column = 'nl_term'
            pattern2 = rf"({re.escape(col)}\s*=\s*['\"])({re.escape(nl_term)})(['\"])"
            sql = re.sub(pattern2, rf"\g<1>{db_value}\g<3>", sql, flags=re.IGNORECASE)

            # 模式 3: table.column LIKE '%nl_term%'
            if table:
                pattern3 = rf"({re.escape(table)}\.{re.escape(col)}\s+LIKE\s+['\"])%?({re.escape(nl_term)})%?(['\"])"
                sql = re.sub(pattern3, rf"\g<1>%{db_value}%\g<3>", sql, flags=re.IGNORECASE)

            # 模式 4: column LIKE '%nl_term%'
            pattern4 = rf"({re.escape(col)}\s+LIKE\s+['\"])%?({re.escape(nl_term)})%?(['\"])"
            sql = re.sub(pattern4, rf"\g<1>%{db_value}%\g<3>", sql, flags=re.IGNORECASE)

    return sql


# ---------- SQL 验证（复用老项目 sql_validator_agent 逻辑） ----------


def validate_sql_syntax(sql: str) -> dict:
    """验证 SQL 语法正确性"""
    errors = []
    warnings = []

    # 使用 sqlparse 进行基础语法检查
    try:
        parsed = sqlparse.parse(sql)
        if not parsed:
            errors.append("SQL 语句无法解析")
    except Exception as e:
        errors.append(f"SQL 语法错误: {e}")

    sql_upper = sql.upper()

    # 检查是否包含危险操作
    dangerous_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]
    for keyword in dangerous_keywords:
        if re.search(rf"\b{keyword}\b", sql_upper):
            errors.append(f"包含危险操作: {keyword}")

    # 检查是否有 SELECT 语句
    if not re.search(r"\bSELECT\b", sql_upper):
        errors.append("缺少 SELECT 语句")

    # 检查括号匹配
    if sql.count("(") != sql.count(")"):
        errors.append("括号不匹配")

    # 检查引号匹配
    if sql.count("'") % 2 != 0:
        warnings.append("单引号可能不匹配")

    # 检查是否有 LIMIT 子句（推荐）
    if "LIMIT" not in sql_upper and "TOP" not in sql_upper:
        warnings.append("建议添加 LIMIT 子句以限制结果集大小")

    return {"is_valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_sql_performance(sql: str) -> dict:
    """验证 SQL 性能，识别潜在问题"""
    issues = []
    suggestions = []

    sql_upper = sql.upper()

    # 检查是否使用 SELECT *
    if re.search(r"SELECT\s+\*", sql_upper):
        issues.append("使用 SELECT * 可能影响性能，建议明确指定需要的列")

    # 检查是否有 WHERE 子句
    if "WHERE" not in sql_upper and "LIMIT" not in sql_upper:
        issues.append("缺少 WHERE 子句可能导致全表扫描")

    # 检查 JOIN 类型
    if "CROSS JOIN" in sql_upper:
        issues.append("CROSS JOIN 可能产生笛卡尔积，影响性能")

    # 检查子查询数量
    subquery_count = sql_upper.count("(SELECT")
    if subquery_count > 2:
        suggestions.append(f"检测到 {subquery_count} 个子查询，考虑使用 JOIN 优化")

    # 检查 ORDER BY
    if "ORDER BY" in sql_upper and "LIMIT" not in sql_upper:
        suggestions.append("ORDER BY 无 LIMIT 可能影响性能")

    # 检查 LIKE 模式
    like_patterns = re.findall(r"LIKE\s+['\"]([^'\"]*)['\"]", sql_upper)
    for pattern in like_patterns:
        if pattern.startswith("%"):
            issues.append(f"LIKE 模式 '{pattern}' 以通配符开头，无法使用索引")

    return {"issues": issues, "suggestions": suggestions}


def validate_sql_against_schema(sql: str, schema_tables: list[dict]) -> dict:
    """验证 SQL 中的表名和列名是否存在于 Schema 中"""
    errors = []
    warnings = []

    if not schema_tables:
        return {"errors": errors, "warnings": ["无法获取 Schema 信息，跳过表/列验证"]}

    # 提取 Schema 中的表名和列名
    table_names = {t.get("table_name", "").lower() for t in schema_tables}
    column_map = {}  # table_name -> set of column_names
    for t in schema_tables:
        tname = t.get("table_name", "").lower()
        cols = {c.get("column_name", "").lower() for c in t.get("columns", [])}
        column_map[tname] = cols

    # 提取 SQL 中的表名（FROM / JOIN 后面）
    sql_tables = set(re.findall(r"(?:FROM|JOIN)\s+[`\"]?(\w+)[`\"]?", sql, re.IGNORECASE))
    sql_tables = {t.lower() for t in sql_tables}

    # 检查表名是否存在
    for tbl in sql_tables:
        if tbl not in table_names:
            errors.append(f"表 '{tbl}' 在 Schema 中不存在")

    # 提取 SQL 中的 table.column 或可能的列引用（简化检查）
    # 完整实现需要 SQL 解析器，这里仅做基础警告
    for tbl in sql_tables:
        if tbl in column_map:
            # 检查常见的列引用模式: table.column
            table_col_refs = re.findall(rf"{re.escape(tbl)}\.(\w+)", sql, re.IGNORECASE)
            for col in table_col_refs:
                if col.lower() not in column_map[tbl]:
                    errors.append(f"列 '{tbl}.{col}' 在 Schema 中不存在")

    return {"errors": errors, "warnings": warnings}


# ---------- 工具工厂 ----------


async def get_reporter_tools(db_connection_id: int | None) -> list:
    """根据数据库连接 ID 创建 Reporter 专用工具列表

    包含: 数据库操作工具 + Schema 加载 + 相似查询检索 + SQL 验证 + 查询历史保存
    """
    if not db_connection_id:
        return []

    # 加载连接配置
    db_type, db_config = await _load_connection_config(db_connection_id)
    connection_db_type = db_type

    # 获取值映射（用于后处理）
    from src.services.text2sql_service import text2sql_service

    value_mappings = await text2sql_service.get_value_mappings_for_sql(db_connection_id)

    from src.services.query_history_service import query_history_service

    query_history_service.start_warmup()

    # 预加载 Schema（用于验证）
    schema_data = await text2sql_service.get_schema(db_connection_id)
    schema_tables = schema_data.get("tables", [])

    # 缓存 Schema 和值映射
    _schema_cache[db_connection_id] = (schema_tables, value_mappings)

    # 1. 数据库操作工具（重新定义 db_execute_query 以集成值映射后处理）
    from src.agents.common.toolkits.database.connection import DatabaseConnectionManager

    conn_manager = DatabaseConnectionManager.get_instance(db_type, db_config)
    stage_cache: dict[str, dict[str, dict]] = {
        "analyze_user_query": {},
        "retrieve_database_schema": {},
        "search_similar_queries": {},
        "generate_sql_query": {},
        "validate_sql": {},
    }

    class EmptyModel(BaseModel):
        pass

    class TableDescribeModel(BaseModel):
        table_name: str = Field(description="要查询结构的表名")

    class QueryModel(BaseModel):
        sql: str = Field(description="要执行的 SQL 查询语句（只允许 SELECT / SHOW / DESCRIBE / EXPLAIN）")
        timeout: int | None = Field(default=60, description="查询超时时间（秒），默认 60 秒，最大 600 秒", ge=1, le=600)

    @tool(name_or_callable="db_list_tables", args_schema=EmptyModel)
    def db_list_tables() -> str:
        """【查询表名】获取数据库中的所有表名。"""
        try:
            table_names = conn_manager.get_usable_table_names()
            if not table_names:
                return "数据库中没有找到任何表"
            result = f"数据库中的表（共 {len(table_names)} 个）:\n"
            result += "\n".join(f"- {name}" for name in sorted(table_names))
            return result
        except Exception as e:
            return f"获取表名失败: {e}"

    @tool(name_or_callable="db_describe_table", args_schema=TableDescribeModel)
    def db_describe_table(table_name: str) -> str:
        """【描述表结构】获取指定表的详细结构信息。"""
        try:
            if not SQLSecurityChecker.validate_table_name(table_name):
                return "表名包含非法字符"
            db = conn_manager.get_db()
            info = db.get_table_info(table_names=[table_name])
            if not info or not info.strip():
                return f"表 {table_name} 不存在或没有字段"
            return f"表 `{table_name}` 的结构:\n\n{info}"
        except Exception as e:
            return f"获取表 {table_name} 结构失败: {e}"

    @tool(name_or_callable="db_execute_query", args_schema=QueryModel)
    def db_execute_query(sql: str, timeout: int | None = 60) -> dict:
        """【执行 SQL 查询】执行只读的 SQL 查询语句并返回结果。

        会自动应用值映射后处理，将自然语言值替换为数据库实际值。
        支持 SELECT、SHOW、DESCRIBE、EXPLAIN 等只读操作。
        """
        try:
            if timeout is not None and not SQLSecurityChecker.validate_timeout(timeout):
                return {
                    "success": False,
                    "stage": "sql_execution",
                    "error": "timeout 参数必须在 1-600 之间",
                }

            check_result = SQLSecurityChecker.check_sql(sql)
            if not check_result["safe"]:
                return {
                    "success": False,
                    "stage": "sql_execution",
                    "error": f"SQL 安全检查失败: {check_result['reason']}",
                }

            original_sql = sql
            processed_sql = process_sql_with_value_mappings(sql, value_mappings)
            if processed_sql != original_sql:
                logger.info(f"值映射后处理: {original_sql} -> {processed_sql}")

            # 使用线程超时守卫，避免长查询阻塞 agent 编排。
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(conn_manager.run_query, processed_sql)
                result = future.result(timeout=timeout or 60)

            if not result or result.strip() == "":
                return {
                    "success": True,
                    "stage": "sql_execution",
                    "summary": "查询执行成功，但没有返回任何结果。",
                    "hint": "检查筛选条件是否过于严格，尝试放宽条件或使用 LIKE 模糊匹配。",
                    "executed_sql": processed_sql,
                }

            max_chars = 10000
            truncated = False
            if len(result) > max_chars:
                result = result[:max_chars] + "\n\n⚠️ 结果过长，已截断。请使用 LIMIT 子句减少返回数据量。"
                truncated = True

            payload = {
                "success": True,
                "stage": "sql_execution",
                "summary": "查询执行成功",
                "result": result,
                "truncated": truncated,
                "executed_sql": processed_sql,
            }
            if processed_sql != original_sql:
                payload["note"] = "已自动应用值映射后处理"
            return payload

        except concurrent.futures.TimeoutError:
            return {
                "success": False,
                "stage": "sql_execution",
                "error": f"SQL 查询超时（>{timeout or 60}s）",
                "hint": "建议添加 LIMIT、增加筛选条件或拆分查询。",
            }
        except Exception as e:
            error_msg = f"SQL 查询执行失败: {e}"
            err_str = str(e).lower()
            hint = ""

            if "timeout" in err_str:
                hint = "添加 LIMIT 子句、补充 WHERE 条件，或提高 timeout 参数。"
            elif "table" in err_str and ("doesn't exist" in err_str or "does not exist" in err_str):
                table_match = re.search(r"table\s*['\"]?(\w+)['\"]?", err_str)
                if table_match:
                    wrong_table = table_match.group(1)
                    similar = [
                        t.get("table_name", "")
                        for t in schema_tables
                        if wrong_table.lower() in t.get("table_name", "").lower()
                    ]
                    if similar:
                        hint = f"表 '{wrong_table}' 不存在，可能是: {similar}"
                    else:
                        hint = "请使用 db_list_tables 查看可用表名。"
            elif "column" in err_str and (
                "doesn't exist" in err_str or "does not exist" in err_str or "unknown" in err_str
            ):
                hint = "列不存在，请使用 db_describe_table 查看表结构。"
            elif "syntax" in err_str:
                hint = "SQL 语法错误，请检查括号、引号和关键字。"

            logger.error(error_msg)
            return {
                "success": False,
                "stage": "sql_execution",
                "error": error_msg,
                "hint": hint,
            }

    # 2. Schema 加载工具
    @tool(name_or_callable="load_database_schema", args_schema=SchemaInput)
    async def load_database_schema(question: str) -> str:
        """【加载数据库结构】从持久化存储中加载数据库 Schema（表结构、关系、值映射）。

        在生成 SQL 之前必须先调用此工具了解数据库结构。
        当表数量较多时，传入用户问题可自动筛选相关表。
        """
        schema_info, vm = await _load_persisted_schema(db_connection_id, user_question=question)
        if not schema_info:
            return "数据源的 Schema 信息为空，请先在数据源管理中同步 Schema。"

        result = schema_info
        if vm:
            result += _format_value_mappings(vm)
        return result

    @tool(name_or_callable="analyze_user_query", args_schema=AnalyzeQueryInput)
    async def analyze_user_query(question: str) -> dict:
        """【分析用户查询】提取查询意图、相关表/列等结构化信息。"""
        from src.config import config
        from src.services.text2sql_service import text2sql_service

        cache_key = _hash_payload({"question": question})
        cached = stage_cache["analyze_user_query"].get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}

        preferred_model = os.getenv("REPORTER_SCHEMA_MODEL", "").strip() or config.fast_model or config.default_model
        result = await text2sql_service.analyze_query(question, model_name=preferred_model)
        if isinstance(result, dict):
            result.setdefault("stage", "schema_analysis")
            _cache_put(stage_cache["analyze_user_query"], cache_key, result)
        return result

    @tool(name_or_callable="retrieve_database_schema", args_schema=SchemaInput)
    async def retrieve_database_schema(question: str) -> dict:
        """【检索数据库 Schema】返回结构化 Schema 与值映射。"""
        started = time.perf_counter()
        cache_key = _hash_payload({"question": question})
        cached = stage_cache["retrieve_database_schema"].get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}
        schema_data = await text2sql_service.get_schema(db_connection_id)
        tables = schema_data.get("tables", [])
        relationships = schema_data.get("relationships", [])

        analysis_payload = {"success": False, "analysis": {}}
        if question:
            analysis_payload = await text2sql_service.analyze_query(question)

        analysis = analysis_payload.get("analysis", {}) if isinstance(analysis_payload, dict) else {}
        selected_tables, selected_relationships = _select_relevant_schema(
            tables=tables,
            relationships=relationships,
            question=question,
            query_analysis=analysis if isinstance(analysis, dict) else {},
            max_tables=SCHEMA_TRIM_THRESHOLD,
        )

        schema_text = _build_schema_text(selected_tables, selected_relationships)
        vm = await text2sql_service.get_value_mappings_for_sql(db_connection_id)

        response = {
            "success": True,
            "stage": "schema_analysis",
            "schema_text": schema_text,
            "tables": selected_tables,
            "relationships": selected_relationships,
            "value_mappings": vm,
            "query_analysis": analysis if isinstance(analysis, dict) else {},
            "schema_selection": {
                "original_tables": len(tables),
                "selected_tables": len(selected_tables),
            },
        }
        logger.info(
            "retrieve_database_schema done "
            f"(connection_id={db_connection_id}, selected={len(selected_tables)}/{len(tables)}, "
            f"cost={time.perf_counter() - started:.2f}s)"
        )
        _cache_put(stage_cache["retrieve_database_schema"], cache_key, response)
        return response

    @tool(name_or_callable="validate_schema_completeness", args_schema=SchemaCompletenessInput)
    def validate_schema_completeness(schema_info: dict, query_analysis: dict) -> dict:
        """【校验 Schema 完整性】检查是否覆盖查询涉及的实体。"""
        required_entities = set()
        analysis = query_analysis or {}
        for key in ("tables", "columns", "entities"):
            values = analysis.get(key, []) or []
            required_entities.update(str(v).lower() for v in values)

        tables = schema_info.get("tables", []) if isinstance(schema_info, dict) else []
        available_tables = {t.get("table_name", "").lower() for t in tables}

        missing = []
        for entity in required_entities:
            if entity and entity not in available_tables:
                missing.append(entity)

        return {
            "success": True,
            "is_complete": len(missing) == 0,
            "missing_entities": missing,
            "suggestions": [f"可能缺少与 {m} 相关的表信息" for m in missing],
        }

    # 3. 相似查询检索工具
    @tool(name_or_callable="search_similar_queries", args_schema=SimilarQueryInput)
    async def search_similar_queries(question: str) -> dict:
        """【检索相似查询】从历史记录中检索与当前问题相似的 SQL 查询。

        返回相似的历史查询及其 SQL，可作为 SQL 生成的参考。
        """
        started = time.perf_counter()
        from src.services.query_history_service import query_history_service

        schema_table_names = [t.get("table_name", "") for t in schema_tables if t.get("table_name")]
        if _is_simple_query(question) and len(schema_table_names) <= 12:
            response = {
                "success": True,
                "stage": "sample_retrieval",
                "qa_pairs": [],
                "summary": "简单聚合查询，跳过相似样本检索以加速。",
                "retrieval_mode": "skip_simple",
            }
            logger.info(
                "search_similar_queries skipped "
                f"(connection_id={db_connection_id}, reason=simple_query, cost={time.perf_counter() - started:.2f}s)"
            )
            return response
        cache_key = _hash_payload({"question": question})
        cached = stage_cache["search_similar_queries"].get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}
        results = await query_history_service.search(
            db_connection_id,
            question,
            top_k=5,
            schema_tables=schema_table_names or None,
        )
        scored = _score_similar_queries(question, results) if results else []
        if not scored:
            response = {
                "success": True,
                "stage": "sample_retrieval",
                "qa_pairs": [],
                "summary": "未找到相似的历史查询。",
                "retrieval_mode": "hybrid",
            }
            logger.info(
                "search_similar_queries done "
                f"(connection_id={db_connection_id}, total_found=0, cost={time.perf_counter() - started:.2f}s)"
            )
            _cache_put(stage_cache["search_similar_queries"], cache_key, response)
            return response
        response = {
            "success": True,
            "stage": "sample_retrieval",
            "qa_pairs": scored,
            "summary": _format_similar_queries(scored),
            "retrieval_mode": "hybrid",
        }
        logger.info(
            "search_similar_queries done "
            f"(connection_id={db_connection_id}, total_found={len(scored)}, "
            f"cost={time.perf_counter() - started:.2f}s)"
        )
        _cache_put(stage_cache["search_similar_queries"], cache_key, response)
        return response

    @tool(name_or_callable="analyze_sample_relevance", args_schema=SampleRelevanceInput)
    def analyze_sample_relevance(question: str, qa_pairs: list[dict]) -> dict:
        """【样本相关性分析】对候选样本进行二次筛选并给出推荐样本。"""
        scored = _score_similar_queries(question, qa_pairs or []) if qa_pairs else []
        top_samples = scored[:3]
        return {
            "success": True,
            "stage": "sample_retrieval",
            "recommended_samples": top_samples,
            "summary": _format_similar_queries(top_samples) if top_samples else "无可用高相关样本",
        }

    @tool(name_or_callable="generate_sql_query", args_schema=GenerateSqlInput)
    async def generate_sql_query(
        user_query: str,
        schema_info: dict,
        value_mappings: dict | None = None,
        sample_qa_pairs: list[dict] | None = None,
        db_type: str | None = None,
    ) -> dict:
        """【生成 SQL】基于 Schema 与样本生成 SQL，并融合样本置信度。"""
        started = time.perf_counter()
        if not user_query:
            return {"success": False, "stage": "sql_generation", "error": "user_query is empty"}

        from langchain_core.messages import HumanMessage

        from src.config import config

        cache_key = _hash_payload(
            {
                "user_query": user_query,
                "schema_info": schema_info,
                "value_mappings": value_mappings,
                "sample_qa_pairs": sample_qa_pairs,
                "db_type": db_type or connection_db_type,
            }
        )
        cached = stage_cache["generate_sql_query"].get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}
        model_spec = os.getenv("REPORTER_SQL_GEN_MODEL", "").strip() or config.fast_model or config.default_model
        model = load_chat_model(model_spec)
        schema_text = schema_info.get("schema_text") if isinstance(schema_info, dict) else None
        schema_text = schema_text or ""

        sample_lines = []
        if sample_qa_pairs:
            for idx, sample in enumerate(sample_qa_pairs[:3], 1):
                score = sample.get("final_score") or sample.get("similarity") or 0
                sample_lines.append(
                    f"样本{idx} (score={score}):\n问题: {sample.get('question', '')}\nSQL: {sample.get('sql', '')}"
                )
        sample_text = "\n\n".join(sample_lines) if sample_lines else "无"

        mappings_text = _format_value_mappings(value_mappings or {})
        effective_db_type = (db_type or connection_db_type or "unknown").lower()
        dialect_hint = ""
        if effective_db_type in {"postgres", "postgresql"}:
            dialect_hint = "请使用 PostgreSQL 语法（如 ILIKE、::type、LIMIT）。"
        elif effective_db_type in {"oracle", "oracledb"}:
            dialect_hint = "请使用 Oracle 语法（如 FETCH FIRST N ROWS ONLY 或 ROWNUM）。"
        elif effective_db_type in {"mssql", "sqlserver"}:
            dialect_hint = "请使用 SQL Server 语法（如 TOP / OFFSET FETCH）。"
        elif effective_db_type == "sqlite":
            dialect_hint = "请使用 SQLite 语法。"
        else:
            dialect_hint = "请使用 MySQL 语法。"

        prompt = (
            "你是 SQL 生成专家。\n"
            f"数据库类型: {effective_db_type}\n"
            f"{dialect_hint}\n\n"
            f"Schema:\n{schema_text}\n\n"
            f"值映射:\n{mappings_text or '无'}\n\n"
            f"相似样本(注意样本分数越高越可信，优先参考高分样本的结构与字段):\n{sample_text}\n\n"
            f"用户问题: {user_query}\n\n"
            "要求：只返回最终 SQL，不要解释。默认加 LIMIT 100。"
        )

        resp = await model.ainvoke([HumanMessage(content=prompt)])
        sql_query = resp.content.strip()
        if sql_query.startswith("```sql"):
            sql_query = sql_query[6:]
        if sql_query.endswith("```"):
            sql_query = sql_query[:-3]
        sql_query = sql_query.strip()

        response = {
            "success": True,
            "stage": "sql_generation",
            "sql": sql_query,
            "samples_used": len(sample_qa_pairs or []),
            "db_type": effective_db_type,
        }
        logger.info(
            "generate_sql_query done "
            f"(connection_id={db_connection_id}, db_type={effective_db_type}, "
            f"samples={len(sample_qa_pairs or [])}, cost={time.perf_counter() - started:.2f}s)"
        )
        _cache_put(stage_cache["generate_sql_query"], cache_key, response)
        return response

    # 4. SQL 验证工具
    @tool(name_or_callable="validate_sql", args_schema=ValidateSqlInput)
    def validate_sql(sql: str) -> dict:
        """【验证 SQL】验证 SQL 语句的语法、安全性、性能，并检查表/列是否存在。

        在执行 SQL 之前调用此工具进行预检查，可以提前发现问题。
        """
        cache_key = _hash_payload({"sql": sql})
        cached = stage_cache["validate_sql"].get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}
        results = []

        # 1. 语法验证
        syntax_result = validate_sql_syntax(sql)
        if not syntax_result["is_valid"]:
            results.append("❌ **语法检查失败**:")
            for err in syntax_result["errors"]:
                results.append(f"  - {err}")
        else:
            results.append("✅ **语法检查通过**")

        if syntax_result["warnings"]:
            results.append("⚠️ **语法警告**:")
            for warn in syntax_result["warnings"]:
                results.append(f"  - {warn}")

        # 2. 安全验证
        security_result = SQLSecurityChecker.check_sql(sql)
        if not security_result["safe"]:
            results.append(f"❌ **安全检查失败**: {security_result['reason']}")
        else:
            results.append("✅ **安全检查通过**")

        # 3. 性能验证
        perf_result = validate_sql_performance(sql)
        if perf_result["issues"]:
            results.append("⚠️ **性能问题**:")
            for issue in perf_result["issues"]:
                results.append(f"  - {issue}")
        if perf_result["suggestions"]:
            results.append("💡 **性能建议**:")
            for sug in perf_result["suggestions"]:
                results.append(f"  - {sug}")

        # 4. Schema 验证
        schema_result = validate_sql_against_schema(sql, schema_tables)
        if schema_result["errors"]:
            results.append("❌ **Schema 检查失败**:")
            for err in schema_result["errors"]:
                results.append(f"  - {err}")
        elif not schema_result["warnings"]:
            results.append("✅ **Schema 检查通过**")

        if schema_result["warnings"]:
            for warn in schema_result["warnings"]:
                results.append(f"⚠️ {warn}")

        # 5. 值映射提示
        if value_mappings:
            processed = process_sql_with_value_mappings(sql, value_mappings)
            if processed != sql:
                results.append(f"\n📝 **值映射转换**: 执行时将自动应用以下转换:\n```sql\n{processed}\n```")

        # 总结
        is_valid = syntax_result["is_valid"] and security_result["safe"] and not schema_result["errors"]
        if is_valid:
            results.insert(0, "## SQL 验证结果: ✅ 通过\n")
        else:
            results.insert(0, "## SQL 验证结果: ❌ 存在问题，请修复后再执行\n")

        response = {
            "success": is_valid,
            "stage": "sql_validation",
            "is_valid": is_valid,
            "summary": "\n".join(results),
            "details": {
                "syntax": syntax_result,
                "security": security_result,
                "performance": perf_result,
                "schema": schema_result,
            },
        }
        _cache_put(stage_cache["validate_sql"], cache_key, response)
        return response

    # 5. 查询历史保存工具
    @tool(name_or_callable="save_query_history", args_schema=SaveQueryInput)
    async def save_query_history_tool(question: str, sql: str) -> dict:
        """【保存查询记录】将成功执行的查询保存到历史记录中，供后续检索参考。

        在 SQL 执行成功并完成分析后调用此工具。
        """
        from src.services.query_history_service import query_history_service

        await query_history_service.save(db_connection_id, question, sql, success=True)
        return {"success": True, "stage": "sql_execution", "summary": "查询记录已保存。"}

    @tool(name_or_callable="analyze_error_pattern", args_schema=ErrorPatternInput)
    def analyze_error_pattern(error_history: list[dict]) -> dict:
        """【错误模式分析】识别重复错误与常见阶段。"""
        if not error_history:
            return {"success": True, "pattern_found": False, "message": "没有错误历史记录"}

        error_types = {}
        error_stages = {}
        for error in error_history:
            msg = str(error.get("error", "")).lower()
            stage = error.get("stage", "unknown")
            if "syntax" in msg or "语法" in msg:
                error_types["syntax_error"] = error_types.get("syntax_error", 0) + 1
            elif "connection" in msg or "连接" in msg:
                error_types["connection_error"] = error_types.get("connection_error", 0) + 1
            elif "permission" in msg or "权限" in msg:
                error_types["permission_error"] = error_types.get("permission_error", 0) + 1
            elif "timeout" in msg or "超时" in msg:
                error_types["timeout_error"] = error_types.get("timeout_error", 0) + 1
            else:
                error_types["unknown_error"] = error_types.get("unknown_error", 0) + 1
            error_stages[stage] = error_stages.get(stage, 0) + 1

        most_common_type = max(error_types.items(), key=lambda x: x[1]) if error_types else ("none", 0)
        most_common_stage = max(error_stages.items(), key=lambda x: x[1]) if error_stages else ("none", 0)
        pattern_found = most_common_type[1] > 1 or most_common_stage[1] > 1

        return {
            "success": True,
            "pattern_found": pattern_found,
            "error_types": error_types,
            "error_stages": error_stages,
            "most_common_type": most_common_type[0],
            "most_common_stage": most_common_stage[0],
            "total_errors": len(error_history),
        }

    @tool(name_or_callable="generate_recovery_strategy", args_schema=RecoveryStrategyInput)
    def generate_recovery_strategy(error_analysis: dict, current_state: dict) -> dict:
        """【恢复策略生成】根据错误分析给出修复建议。"""
        most_common_type = error_analysis.get("most_common_type", "unknown")
        retry_count = current_state.get("retry_count", 0)

        strategies = {
            "syntax_error": {
                "primary_action": "regenerate_sql",
                "secondary_action": "simplify_query",
                "description": "SQL语法错误，建议重新生成或简化查询",
                "auto_fixable": True,
                "confidence": 0.8,
            },
            "timeout_error": {
                "primary_action": "optimize_query",
                "secondary_action": "add_limit",
                "description": "查询超时，建议优化或限制结果集",
                "auto_fixable": True,
                "confidence": 0.7,
            },
            "connection_error": {
                "primary_action": "check_connection",
                "secondary_action": "use_alternative_connection",
                "description": "连接异常，请检查连接配置",
                "auto_fixable": False,
                "confidence": 0.6,
            },
        }

        strategy = strategies.get(
            most_common_type,
            {
                "primary_action": "restart",
                "secondary_action": "manual_review",
                "description": "未知错误，建议重新开始或人工介入",
                "auto_fixable": False,
                "confidence": 0.3,
            },
        )

        if retry_count >= 2:
            strategy["primary_action"] = strategy["secondary_action"]
            strategy["confidence"] *= 0.7

        action_to_stage = {
            "regenerate_sql": "sql_generation",
            "simplify_query": "sql_generation",
            "optimize_query": "sql_validation",
            "add_limit": "sql_validation",
            "check_connection": "schema_analysis",
            "use_alternative_connection": "schema_analysis",
            "restart": "schema_analysis",
            "manual_review": "error_recovery",
        }

        return {
            "success": True,
            "stage": "error_recovery",
            "strategy": strategy,
            "suggested_next_stage": action_to_stage.get(strategy.get("primary_action", ""), "sql_generation"),
        }

    @tool(name_or_callable="auto_fix_sql_error", args_schema=AutoFixInput)
    def auto_fix_sql_error(sql: str, error_message: str, schema_info: dict | None = None) -> dict:
        """【SQL 自动修复】基于错误信息尝试修复 SQL。"""
        fixes_applied = []
        fixed_sql = sql
        msg = error_message.lower()

        if "syntax" in msg or "语法" in msg:
            if not fixed_sql.strip().endswith(";"):
                fixed_sql += ";"
                fixes_applied.append("添加分号")
            if fixed_sql.count("'") % 2 != 0:
                fixed_sql += "'"
                fixes_applied.append("补全单引号")

        if ("doesn't exist" in msg or "does not exist" in msg) and schema_info:
            tables = [t.get("table_name", "") for t in schema_info.get("tables", [])]
            for table in tables:
                if table and table.lower() in fixed_sql.lower():
                    fixed_sql = fixed_sql.replace(table.lower(), table)
                    fixes_applied.append(f"修正表名为 {table}")

        if ("timeout" in msg or "超时" in msg) and "LIMIT" not in fixed_sql.upper():
            fixed_sql += " LIMIT 100"
            fixes_applied.append("添加 LIMIT")

        return {
            "success": True,
            "stage": "error_recovery",
            "auto_fix_successful": len(fixes_applied) > 0,
            "original_sql": sql,
            "fixed_sql": fixed_sql,
            "fixes_applied": fixes_applied,
        }

    return [
        db_list_tables,
        db_describe_table,
        db_execute_query,
        load_database_schema,
        analyze_user_query,
        retrieve_database_schema,
        validate_schema_completeness,
        search_similar_queries,
        analyze_sample_relevance,
        generate_sql_query,
        validate_sql,
        save_query_history_tool,
        analyze_error_pattern,
        generate_recovery_strategy,
        auto_fix_sql_error,
    ]


# ---------- 内部辅助函数（从原 nodes 提取） ----------


async def _load_connection_config(connection_id: int) -> tuple[str, dict]:
    """从数据库连接 ID 加载连接配置，返回 (db_type, db_config)"""
    from src.repositories.text2sql_repository import db_connection_repo
    from src.services.text2sql_service import decrypt_password, text2sql_service

    conn = await text2sql_service.get_connection(connection_id)
    if not conn:
        raise ValueError(f"数据库连接 {connection_id} 不存在")

    conn_model = await db_connection_repo.get_by_id(connection_id)
    password = ""
    if conn_model and conn_model.password_encrypted:
        password = decrypt_password(conn_model.password_encrypted)

    db_type = conn.get("db_type", "mysql")
    db_config = {
        "host": conn.get("host", ""),
        "port": conn.get("port", 3306),
        "user": conn.get("username", ""),
        "password": password,
        "database": conn.get("database", ""),
        "description": "",
    }
    return db_type, db_config


def _tokenize_text(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff_]+", (text or "").lower())
    return {t for t in tokens if len(t) > 1}


def _analysis_keywords(query_analysis: dict, question: str) -> set[str]:
    keywords: set[str] = set()
    for key in ("tables", "columns", "filters", "aggregations", "group_by", "order_by"):
        values = query_analysis.get(key, []) if isinstance(query_analysis, dict) else []
        if isinstance(values, list):
            for item in values:
                keywords.update(_tokenize_text(str(item)))
    keywords.update(_tokenize_text(question))
    return keywords


def _score_table_relevance(table: dict, keywords: set[str], query_analysis: dict) -> float:
    table_name = str(table.get("table_name", ""))
    table_comment = str(table.get("table_comment", ""))
    columns = table.get("columns", []) or []

    score = 0.0
    haystack = _tokenize_text(f"{table_name} {table_comment}")

    explicit_tables = {str(v).lower() for v in (query_analysis.get("tables", []) or [])}
    if table_name.lower() in explicit_tables:
        score += 5.0

    overlap = keywords & haystack
    score += float(len(overlap)) * 1.5

    for col in columns:
        col_text = f"{col.get('column_name', '')} {col.get('column_comment', '')}"
        col_overlap = keywords & _tokenize_text(col_text)
        score += float(len(col_overlap)) * 0.7

    return score


def _expand_with_relationships(selected_table_names: set[str], relationships: list[dict]) -> set[str]:
    expanded = set(selected_table_names)
    for rel in relationships:
        src = str(rel.get("source_table", "")).lower()
        tgt = str(rel.get("target_table", "")).lower()
        if src in expanded:
            expanded.add(tgt)
        if tgt in expanded:
            expanded.add(src)
    return expanded


def _build_schema_text(tables: list[dict], relationships: list[dict]) -> str:
    if not tables:
        return ""

    lines = ["## 数据库 Schema\n"]
    for table in tables:
        table_name = table.get("table_name", "")
        table_comment = table.get("table_comment", "")
        columns = table.get("columns", [])

        lines.append(f"### 表: {table_name}")
        if table_comment:
            lines.append(f"说明: {table_comment}")
        lines.append("")
        lines.append("| 列名 | 类型 | 主键 | 可空 | 注释 |")
        lines.append("|------|------|------|------|------|")
        for col in columns:
            pk = "Y" if col.get("is_primary_key") else ""
            nullable = "Y" if col.get("is_nullable") else "N"
            lines.append(
                f"| {col.get('column_name', '')} | {col.get('column_type', '')} | "
                f"{pk} | {nullable} | {col.get('column_comment', '') or ''} |"
            )
        lines.append("")

    if relationships:
        lines.append("### 表关系")
        lines.append("| 源表 | 源列 | 目标表 | 目标列 | 关系类型 |")
        lines.append("|------|------|--------|--------|----------|")
        for rel in relationships:
            lines.append(
                f"| {rel.get('source_table', '')} | {rel.get('source_column', '')} | "
                f"{rel.get('target_table', '')} | {rel.get('target_column', '')} | "
                f"{rel.get('relationship_type', '')} |"
            )
        lines.append("")

    return "\n".join(lines)


def _select_relevant_schema(
    tables: list[dict],
    relationships: list[dict],
    question: str,
    query_analysis: dict,
    max_tables: int,
) -> tuple[list[dict], list[dict]]:
    if not tables:
        return [], []

    if not question and len(tables) <= max_tables:
        return tables, relationships

    keywords = _analysis_keywords(query_analysis, question)
    scored = [(table, _score_table_relevance(table, keywords, query_analysis)) for table in tables]
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = [item[0] for item in scored if item[1] > 0][:max_tables]
    if not selected:
        selected = [item[0] for item in scored[: min(max_tables, len(scored))]]

    selected_names = {str(t.get("table_name", "")).lower() for t in selected}
    expanded_names = _expand_with_relationships(selected_names, relationships)

    final_tables = [t for t in tables if str(t.get("table_name", "")).lower() in expanded_names]
    final_relationships = [
        r
        for r in relationships
        if str(r.get("source_table", "")).lower() in expanded_names
        and str(r.get("target_table", "")).lower() in expanded_names
    ]
    return final_tables, final_relationships


async def _load_persisted_schema(
    connection_id: int,
    user_question: str = "",
    model_name: str = "",
) -> tuple[str, dict]:
    """从数据库加载持久化 Schema，大表时自动裁剪

    Returns:
        (schema_info_text, value_mappings_dict)
    """
    from src.services.text2sql_service import text2sql_service

    schema_data = await text2sql_service.get_schema(connection_id)
    tables = schema_data.get("tables", [])
    relationships = schema_data.get("relationships", [])

    if not tables:
        return "", {}

    # 优先使用查询分析驱动的相关 schema 选择；失败时回退到旧裁剪策略。
    if user_question and len(tables) > SCHEMA_TRIM_THRESHOLD:
        try:
            analysis_payload = await text2sql_service.analyze_query(user_question, model_name=model_name or None)
            analysis = analysis_payload.get("analysis", {}) if isinstance(analysis_payload, dict) else {}
            tables, relationships = _select_relevant_schema(
                tables=tables,
                relationships=relationships,
                question=user_question,
                query_analysis=analysis if isinstance(analysis, dict) else {},
                max_tables=SCHEMA_TRIM_THRESHOLD,
            )
        except Exception as e:
            logger.warning(f"Schema 相关性选择失败，回退旧裁剪策略: {e}")
            try:
                tables, relationships = await _trim_schema_for_question(
                    tables, relationships, user_question, model_name
                )
            except Exception as trim_error:
                logger.warning(f"Schema 裁剪失败，使用全量: {trim_error}")

    schema_info = _build_schema_text(tables, relationships)

    value_mappings = await text2sql_service.get_value_mappings_for_sql(connection_id)
    return schema_info, value_mappings


async def _trim_schema_for_question(
    tables: list[dict],
    relationships: list[dict],
    user_question: str,
    model_name: str,
) -> tuple[list[dict], list[dict]]:
    """大 Schema 智能裁剪：LLM 选择相关表 + 外键扩展一层。"""
    if len(tables) <= SCHEMA_TRIM_THRESHOLD:
        return tables, relationships

    table_summary = "\n".join(f"- {t.get('table_name', '')}: {t.get('table_comment', '') or '无注释'}" for t in tables)

    if model_name:
        model = load_chat_model(model_name)
    else:
        from src.config import config

        model = load_chat_model(config.default_model)

    from langchain_core.messages import HumanMessage

    prompt = (
        f"用户问题: {user_question}\n\n"
        f"以下是数据库中的所有表:\n{table_summary}\n\n"
        "请返回可能需要用到的表名列表（JSON 数组，只包含表名字符串）。"
    )
    resp = await model.ainvoke([HumanMessage(content=prompt)])
    content = (resp.content or "").strip()

    try:
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        selected_names = json.loads(content.strip())
        if not isinstance(selected_names, list):
            return tables, relationships
    except Exception:
        return tables, relationships

    selected_set = {str(n).lower() for n in selected_names}
    selected_set = _expand_with_relationships(selected_set, relationships)

    trimmed_tables = [t for t in tables if str(t.get("table_name", "")).lower() in selected_set]
    trimmed_rels = [
        r
        for r in relationships
        if str(r.get("source_table", "")).lower() in selected_set
        and str(r.get("target_table", "")).lower() in selected_set
    ]
    return trimmed_tables, trimmed_rels


def _format_value_mappings(value_mappings: dict) -> str:
    if not value_mappings:
        return ""

    lines = ["\n## 值映射（自然语言 -> 数据库值）\n"]
    for table_column, mappings in value_mappings.items():
        table, column = table_column.split(".", 1) if "." in table_column else ("", table_column)
        lines.append(f"**{table}.{column}**:")
        for natural_val, db_val in mappings.items():
            lines.append(f"  - \"{natural_val}\" -> '{db_val}'")
        lines.append("")
    return "\n".join(lines)


def _score_similar_queries(question: str, results: list[dict]) -> list[dict]:
    q_tokens = _tokenize_text(question)
    scored = []

    for item in results:
        item_tokens = _tokenize_text(str(item.get("question", "")))
        semantic = _jaccard(q_tokens, item_tokens)

        tables = _extract_table_names(item)
        table_tokens: set[str] = set()
        for table in tables:
            table_tokens.update(_tokenize_text(table.replace("_", " ")))
        structural = _jaccard(q_tokens, table_tokens) if table_tokens else 0.0

        pattern = _pattern_score(question, item.get("sql", ""), item.get("query_pattern", ""))
        success_rate = float(item.get("success_rate", 0) or 0)
        verified = 1.0 if item.get("verified") else 0.0
        quality = min(1.0, success_rate) * 0.7 + verified * 0.3

        final_score = semantic * 0.6 + structural * 0.2 + pattern * 0.1 + quality * 0.1
        row = dict(item)
        row.update(
            {
                "semantic_score": semantic,
                "structural_score": structural,
                "pattern_score": pattern,
                "quality_score": quality,
                "final_score": final_score,
            }
        )
        scored.append(row)

    scored.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return scored[:5]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_table_names(item: dict) -> list[str]:
    tables = item.get("used_tables") or item.get("tables") or []
    if isinstance(tables, str):
        tables = [t.strip() for t in tables.split(",") if t.strip()]
    return [str(t) for t in tables]


def _pattern_score(question: str, sql: str, query_pattern: str) -> float:
    q_lower = question.lower()
    sql_upper = str(sql).upper()
    pattern = str(query_pattern).lower()

    flags = [
        ("group by" in sql_upper or "分组" in q_lower or "group" in pattern),
        ("order by" in sql_upper or "排序" in q_lower or "order" in pattern),
        ("count" in sql_upper or "数量" in q_lower or "计数" in q_lower),
        ("sum" in sql_upper or "总和" in q_lower or "合计" in q_lower),
    ]
    return sum(1.0 for f in flags if f) / len(flags)


def _format_similar_queries(similar_queries: list) -> str:
    if not similar_queries:
        return ""

    lines = ["## 相似历史查询（参考）\n"]
    for i, query in enumerate(similar_queries[:5], 1):
        similarity = query.get("final_score", query.get("similarity", 0))
        title = f"**示例 {i}** (相似度: {similarity:.2f})"
        lines.append(title)
        lines.append(f"问题: {query.get('question', '')}")
        lines.append(f"SQL: ```sql\n{query.get('sql', '')}\n```")
        lines.append("")

    return "\n".join(lines)
