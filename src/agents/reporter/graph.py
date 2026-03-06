"""数据库报表助手 — 基于 deep agents + 子agent 的多代理架构

工作流：
  Schema → 样本检索 → SQL 生成 → SQL 验证 → SQL 执行 → 图表（可选）→ 错误恢复（按需）
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from src.agents.common import BaseAgent, get_enabled_mcp_tools, load_chat_model
from src.agents.common.middlewares import save_attachments_to_fs
from src.services.skill_generation_service import skill_generation_service
from src.utils import logger

from .agents import (
    build_analysis_system_prompt,
    build_chart_system_prompt,
    build_clarification_system_prompt,
    build_error_recovery_system_prompt,
    build_sample_retrieval_system_prompt,
    build_schema_system_prompt,
    build_sql_executor_system_prompt,
    build_sql_generator_system_prompt,
    build_sql_validator_system_prompt,
)
from .context import ROUTER_PROMPT, ReporterContext
from .tools import get_reporter_tools


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _safe_int(value, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed >= 1 else default
    except Exception:
        return default


def _safe_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    if value is None:
        return default
    return bool(value)


def _tool_map(tools: list) -> dict[str, object]:
    return {tool.name: tool for tool in tools}


def _select_tools(tool_map: dict[str, object], names: list[str]) -> list:
    return [tool_map[name] for name in names if name in tool_map]


def _create_composite_backend(rt):
    return CompositeBackend(
        default=StateBackend(rt),
        routes={
            "/memories/": StoreBackend(rt),
            "/preferences/": StoreBackend(rt),
        },
    )


async def _retry_async(
    operation: Callable[[], Awaitable],
    *,
    retries: int = 2,
    delay_seconds: float = 0.4,
):
    attempts = max(1, retries)
    last_error = None
    for i in range(attempts):
        try:
            return await operation()
        except Exception as e:
            last_error = e
            if i >= attempts - 1:
                raise
            await asyncio.sleep(delay_seconds * (2**i))
    if last_error:
        raise last_error
    raise RuntimeError("retry operation failed")


def _build_reporter_interrupt_on(
    *,
    enabled: bool = False,
    on_db_execute_query: bool = True,
    on_save_query_history: bool = False,
    on_auto_fix_sql_error: bool = False,
) -> dict[str, bool] | None:
    enabled = _safe_bool(enabled, False)
    if not enabled:
        return None
    interrupt_on: dict[str, bool] = {}
    if _safe_bool(on_db_execute_query, True):
        interrupt_on["db_execute_query"] = True
    if _safe_bool(on_save_query_history, False):
        interrupt_on["save_query_history"] = True
    if _safe_bool(on_auto_fix_sql_error, False):
        interrupt_on["auto_fix_sql_error"] = True
    return interrupt_on or None


class SqlReporterAgent(BaseAgent):
    name = "数据库报表助手"
    description = (
        "一个支持多数据库类型（MySQL / PostgreSQL / Oracle / MSSQL / SQLite）的智能数据报表助手。"
        "能够分析数据库结构、生成 SQL 查询、执行查询并以图表形式展示分析结果。"
    )
    context_schema = ReporterContext
    capabilities = [
        "file_upload",
        "files",
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._graph_cache: dict[
            tuple[int | None, str, tuple[str, ...], bool, bool, tuple[str, ...], str, str, int],
            object,
        ] = {}
        self._last_db_connection_id: int | None = None

    def _build_context(self, input_context: dict | None = None) -> ReporterContext:
        context = self._build_runtime_context(input_context)
        return context  # type: ignore[return-value]

    async def stream_messages(self, messages: list[str], input_context=None, **kwargs):
        """重写 stream_messages，提前解析 db_connection_id 以构建绑定工具的 graph"""
        context = self._build_context(input_context)
        graph = await self.get_graph(
            db_connection_id=context.db_connection_id,
            department_id=context.department_id,
            model=context.model,
            system_prompt=context.system_prompt,
            mcps=context.mcps,
            use_generated_skills=context.use_generated_skills,
            generated_skill_ids=context.generated_skill_ids,
        )

        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 300,
        }

        async for msg, metadata in graph.astream(
            {"messages": messages},
            stream_mode="messages",
            context=context,  # type: ignore[arg-type]
            config=input_config,
        ):
            yield msg, metadata

    async def invoke_messages(self, messages: list[str], input_context=None, **kwargs):
        """重写 invoke_messages，提前解析 db_connection_id"""
        context = self._build_context(input_context)
        graph = await self.get_graph(
            db_connection_id=context.db_connection_id,
            department_id=context.department_id,
            model=context.model,
            system_prompt=context.system_prompt,
            mcps=context.mcps,
            use_generated_skills=context.use_generated_skills,
            generated_skill_ids=context.generated_skill_ids,
        )

        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 100,
        }

        result = await graph.ainvoke(
            {"messages": messages},
            context=context,  # type: ignore[arg-type]
            config=input_config,
        )

        return result

    async def get_graph(self, **kwargs):
        """构建基于 Deep Agents 的多代理图

        工具来源：
        1. Reporter 工具（数据库操作 + Schema + 检索 + 保存）— 绑定到 db_connection_id
        2. MCP 工具（图表生成等）— 从 context.mcps 配置的服务器加载
        """
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)
        requested_connection_id = kwargs.get("db_connection_id")
        db_connection_id = requested_connection_id or context.db_connection_id or self._last_db_connection_id
        if db_connection_id is not None:
            self._last_db_connection_id = db_connection_id

        mcp_servers = tuple(context.mcps or [])
        schema_simplified_mode = _env_flag("SCHEMA_SIMPLIFIED_MODE", True)
        selected_skill_ids = tuple(context.generated_skill_ids or [])
        interrupt_on = _build_reporter_interrupt_on(
            enabled=context.enable_interrupt_on,
            on_db_execute_query=context.interrupt_on_db_execute_query,
            on_save_query_history=context.interrupt_on_save_query_history,
            on_auto_fix_sql_error=context.interrupt_on_auto_fix_sql_error,
        )
        retry_attempts = _safe_int(context.graph_retry_attempts, 2)
        cache_key = (
            db_connection_id,
            context.model,
            mcp_servers,
            schema_simplified_mode,
            bool(context.use_generated_skills),
            selected_skill_ids,
            context.system_prompt,
            json.dumps(interrupt_on or {}, sort_keys=True, ensure_ascii=False),
            retry_attempts,
        )
        cached_graph = self._graph_cache.get(cache_key)
        if cached_graph is not None:
            return cached_graph

        # 1. Reporter 专用工具（绑定到数据库连接）
        reporter_tools = await _retry_async(
            lambda: get_reporter_tools(db_connection_id),
            retries=retry_attempts,
        )
        tool_map = _tool_map(reporter_tools)

        # 2. MCP 工具（图表生成等）
        mcp_tools = []
        for server_name in mcp_servers:
            tools_from_server = await _retry_async(
                lambda s=server_name: get_enabled_mcp_tools(s),
                retries=retry_attempts,
            )
            mcp_tools.extend(tools_from_server)

        model = load_chat_model(context.model)
        schema_tool_names = ["analyze_user_query", "retrieve_database_schema"]
        if not schema_simplified_mode:
            schema_tool_names.extend(
                [
                    "validate_schema_completeness",
                    "load_database_schema",
                    "db_list_tables",
                    "db_describe_table",
                ]
            )
        schema_tools = _select_tools(tool_map, schema_tool_names)
        sample_tools = _select_tools(tool_map, ["search_similar_queries", "analyze_sample_relevance"])
        generator_tools = _select_tools(tool_map, ["generate_sql_query"])
        validator_tools = _select_tools(tool_map, ["validate_sql"])
        executor_tools = _select_tools(tool_map, ["db_execute_query", "save_query_history"])
        analysis_tools: list = []
        error_tool_names = ["analyze_error_pattern", "generate_recovery_strategy", "auto_fix_sql_error"]
        if schema_simplified_mode:
            error_tool_names.extend(["db_list_tables", "db_describe_table"])
        error_tools = _select_tools(tool_map, error_tool_names)
        chart_tools = mcp_tools
        skill_sources: list[str] = []
        if context.use_generated_skills and db_connection_id:
            # 技能目录只加载已发布技能；若配置了 skill_id 列表，仅加载指定技能。
            skill_sources = await skill_generation_service.resolve_reporter_skill_sources(
                department_id=context.department_id,
                connection_id=db_connection_id,
                skill_ids=list(selected_skill_ids),
            )

        subagents: list[dict[str, object]] = [
            {
                "name": "schema_agent",
                "description": "分析用户问题并获取相关数据库 Schema 与值映射。",
                "system_prompt": build_schema_system_prompt(schema_simplified_mode),
                "tools": schema_tools,
                "model": model,
            },
            {
                "name": "clarification_agent",
                "description": "在 Schema 已就绪后进行业务澄清，确认口径与范围。",
                "system_prompt": build_clarification_system_prompt(),
                "tools": [],
                "model": model,
            },
            {
                "name": "sql_generator_agent",
                "description": "基于 Schema 与样本结果生成 SQL。",
                "system_prompt": build_sql_generator_system_prompt(),
                "tools": generator_tools,
                "model": model,
            },
            {
                "name": "sql_validator_agent",
                "description": "校验 SQL 的语法、安全和可执行性。",
                "system_prompt": build_sql_validator_system_prompt(),
                "tools": validator_tools,
                "model": model,
            },
            {
                "name": "sql_executor_agent",
                "description": "执行 SQL 并在成功后保存查询历史。",
                "system_prompt": build_sql_executor_system_prompt(),
                "tools": executor_tools,
                "model": model,
            },
            {
                "name": "analysis_agent",
                "description": "对 SQL 执行结果进行业务分析与洞察总结。",
                "system_prompt": build_analysis_system_prompt(context.system_prompt),
                "tools": analysis_tools,
                "model": model,
            },
            {
                "name": "error_recovery_agent",
                "description": "分析失败原因并输出恢复策略或自动修复建议。",
                "system_prompt": build_error_recovery_system_prompt(),
                "tools": error_tools,
                "model": model,
            },
        ]
        # 已启用 skills 时优先走 skills 语义指导路径，样本检索作为兜底能力停用。
        if sample_tools and not skill_sources:
            subagents.insert(
                2,
                {
                    "name": "sample_retrieval_agent",
                    "description": "检索并筛选高质量历史 SQL 样本，为 SQL 生成提供参考。",
                    "system_prompt": build_sample_retrieval_system_prompt(),
                    "tools": sample_tools,
                    "model": model,
                },
            )
        if chart_tools:
            subagents.append(
                {
                    "name": "chart_generator_agent",
                    "description": "在结果适合可视化时生成图表与简要解读。",
                    "system_prompt": build_chart_system_prompt(),
                    "tools": chart_tools,
                    "model": model,
                }
            )

        graph = create_deep_agent(
            model=model,
            tools=[],
            # 主调度器使用固定路由提示词，避免被业务分析提示词污染。
            system_prompt=ROUTER_PROMPT,
            subagents=subagents,
            skills=skill_sources or None,
            backend=_create_composite_backend,
            middleware=[save_attachments_to_fs],
            checkpointer=await self._get_checkpointer(),
            store=await self._get_store(),
            interrupt_on=interrupt_on,
            name="sql_reporter_deep_agent",
        )
        self._graph_cache[cache_key] = graph

        logger.info(
            "SqlReporterAgent Deep Agent 构建成功 "
            f"(connection_id={db_connection_id}, subagents={len(subagents)}, "
            f"schema_mode={'simplified' if schema_simplified_mode else 'full'}, "
            f"skills={len(skill_sources)})"
        )
        return graph
