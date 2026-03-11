"""数据库报表助手 — 基于 Supervisor + Worker 的受控多阶段架构

工作流：
  Schema → 样本检索 → SQL 生成 → SQL 验证 → SQL 执行 → 图表（可选）→ 错误恢复（按需）
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable

from src.agents.common import BaseAgent, get_enabled_mcp_tools, load_chat_model
from src.agent_platform.reporter.runtime import build_reporter_supervisor_graph
from src.services.skill_generation_service import skill_generation_service
from src.utils import logger

from .context import ReporterContext
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
        skill_sources: list[str] = []
        if context.use_generated_skills and db_connection_id:
            # 技能目录只加载已发布技能；若配置了 skill_id 列表，仅加载指定技能。
            skill_sources = await skill_generation_service.resolve_reporter_skill_sources(
                department_id=context.department_id,
                connection_id=db_connection_id,
                skill_ids=list(selected_skill_ids),
            )

        graph = await build_reporter_supervisor_graph(
            model=model,
            context=context,
            tool_map=tool_map,
            mcp_tools=mcp_tools,
            skill_sources=skill_sources,
            checkpointer=await self._get_checkpointer(),
            store=await self._get_store(),
        )
        self._graph_cache[cache_key] = graph

        logger.info(
            "SqlReporterAgent Supervisor graph 构建成功 "
            f"(connection_id={db_connection_id}, workers=deterministic, "
            f"schema_mode={'simplified' if schema_simplified_mode else 'full'}, "
            f"skills={len(skill_sources)}, interrupt_tools={len(interrupt_on or {})})"
        )
        return graph
