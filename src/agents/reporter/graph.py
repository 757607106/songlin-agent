"""数据库报表助手 — 基于 deep agents + 子agent 的多代理架构

工作流：
  Schema → 样本检索 → SQL 生成 → SQL 验证 → SQL 执行 → 图表（可选）→ 错误恢复（按需）
"""

from __future__ import annotations

import os

from deepagents import CompiledSubAgent, create_deep_agent

from src.agents.common import BaseAgent, get_enabled_mcp_tools, load_chat_model
from src.agents.common.middlewares import save_attachments_to_fs
from src.services.skill_generation_service import skill_generation_service
from src.utils import logger

from .agents import (
    create_analysis_agent,
    create_chart_agent,
    create_clarification_agent,
    create_error_recovery_agent,
    create_sample_retrieval_agent,
    create_schema_agent,
    create_sql_executor_agent,
    create_sql_generator_agent,
    create_sql_validator_agent,
)
from .context import ROUTER_PROMPT, ReporterContext
from .tools import get_reporter_tools


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _tool_map(tools: list) -> dict[str, object]:
    return {tool.name: tool for tool in tools}


def _select_tools(tool_map: dict[str, object], names: list[str]) -> list:
    return [tool_map[name] for name in names if name in tool_map]


def _to_compiled_subagent(name: str, description: str, runnable) -> CompiledSubAgent:
    return {
        "name": name,
        "description": description,
        "runnable": runnable,
    }


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
            tuple[int | None, str, tuple[str, ...], bool, bool, tuple[str, ...], str],
            object,
        ] = {}
        self._last_db_connection_id: int | None = None

    def _build_context(self, input_context: dict | None = None) -> ReporterContext:
        """从 input_context 构建 ReporterContext"""
        context = self.context_schema()
        agent_config = (input_context or {}).get("agent_config")
        if isinstance(agent_config, dict):
            context.update(agent_config)
        context.update(input_context or {})
        return context

    async def stream_messages(self, messages: list[str], input_context=None, **kwargs):
        """重写 stream_messages，提前解析 db_connection_id 以构建绑定工具的 graph"""
        context = self._build_context(input_context)
        graph = await self.get_graph(
            db_connection_id=context.db_connection_id,
            department_id=context.department_id,
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
        cache_key = (
            db_connection_id,
            context.model,
            mcp_servers,
            schema_simplified_mode,
            bool(context.use_generated_skills),
            selected_skill_ids,
            context.system_prompt,
        )
        cached_graph = self._graph_cache.get(cache_key)
        if cached_graph is not None:
            return cached_graph

        # 1. Reporter 专用工具（绑定到数据库连接）
        reporter_tools = await get_reporter_tools(db_connection_id)
        tool_map = _tool_map(reporter_tools)

        # 2. MCP 工具（图表生成等）
        mcp_tools = []
        for server_name in mcp_servers:
            mcp_tools.extend(await get_enabled_mcp_tools(server_name))

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

        # 关键说明：这里使用 deepagents 官方 create_deep_agent + CompiledSubAgent。
        # 每个子agent保持单一职责，主agent只做流程编排，避免复杂嵌套逻辑。
        subagents: list[CompiledSubAgent] = [
            _to_compiled_subagent(
                "schema_agent",
                "分析用户问题并获取相关数据库 Schema 与值映射。",
                create_schema_agent(model, schema_tools),
            ),
            _to_compiled_subagent(
                "clarification_agent",
                "在 Schema 已就绪后进行业务澄清，确认口径与范围。",
                create_clarification_agent(model, []),
            ),
            _to_compiled_subagent(
                "sql_generator_agent",
                "基于 Schema 与样本结果生成 SQL。",
                create_sql_generator_agent(model, generator_tools),
            ),
            _to_compiled_subagent(
                "sql_validator_agent",
                "校验 SQL 的语法、安全和可执行性。",
                create_sql_validator_agent(model, validator_tools),
            ),
            _to_compiled_subagent(
                "sql_executor_agent",
                "执行 SQL 并在成功后保存查询历史。",
                create_sql_executor_agent(model, executor_tools),
            ),
            _to_compiled_subagent(
                "analysis_agent",
                "对 SQL 执行结果进行业务分析与洞察总结。",
                create_analysis_agent(model, analysis_tools, context.system_prompt),
            ),
            _to_compiled_subagent(
                "error_recovery_agent",
                "分析失败原因并输出恢复策略或自动修复建议。",
                create_error_recovery_agent(model, error_tools),
            ),
        ]
        # 已启用 skills 时优先走 skills 语义指导路径，样本检索作为兜底能力停用。
        if sample_tools and not skill_sources:
            subagents.insert(
                2,
                _to_compiled_subagent(
                    "sample_retrieval_agent",
                    "检索并筛选高质量历史 SQL 样本，为 SQL 生成提供参考。",
                    create_sample_retrieval_agent(model, sample_tools),
                ),
            )
        if chart_tools:
            subagents.append(
                _to_compiled_subagent(
                    "chart_generator_agent",
                    "在结果适合可视化时生成图表与简要解读。",
                    create_chart_agent(model, chart_tools),
                )
            )

        graph = create_deep_agent(
            model=model,
            tools=[],
            # 主调度器使用固定路由提示词，避免被业务分析提示词污染。
            system_prompt=ROUTER_PROMPT,
            subagents=subagents,
            skills=skill_sources or None,
            middleware=[save_attachments_to_fs],
            checkpointer=await self._get_checkpointer(),
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
