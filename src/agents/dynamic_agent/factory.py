"""DynamicAgentFactory — builds agent graphs from context configuration.

Dispatches to the appropriate builder based on the multi_agent_mode:
- "disabled" → single deep agent (no subagents)
- "supervisor" → LangGraph StateGraph with subgraph nodes
- "deep_agents" → create_deep_agent(subagents=[...]) with task() tool
- "swarm" → LangGraph Swarm with handoff-based collaboration
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any
from weakref import WeakValueDictionary

from deepagents import create_deep_agent
from langgraph.graph.state import CompiledStateGraph

from src.agents.common import load_chat_model
from src.agents.common.deepagent_runtime import (
    create_main_middlewares,
    create_state_store_backend,
    create_subagent_middlewares,
)
from src.agents.common.subagents.registry import ToolResolver
from src.services.mcp_service import get_enabled_mcp_tools
from src.services.skill_catalog_service import resolve_skill_sources
from src.services.team_orchestration_service import team_orchestration_service
from src.utils import logger

from .context import DynamicAgentContext
from .supervisor import build_supervisor_graph
from .swarm_builder import build_swarm_graph


class DynamicAgentFactory:
    """Factory that builds agent graphs from DynamicAgentContext.

    Features:
    - Graph caching based on configuration hash to avoid redundant builds
    - Support for multiple agent collaboration modes
    - Automatic tool/MCP/skill resolution

    Usage:
        factory = DynamicAgentFactory()
        graph = await factory.build_graph(context, checkpointer=cp, store=st)
    """

    # Class-level graph cache using WeakValueDictionary to allow GC
    _graph_cache: WeakValueDictionary[str, CompiledStateGraph] = WeakValueDictionary()
    # Strong reference cache for frequently used graphs (LRU-like)
    _strong_cache: dict[str, tuple[CompiledStateGraph, float]] = {}
    _CACHE_MAX_SIZE = 20
    _CACHE_TTL_SECONDS = 3600  # 1 hour

    def _compute_cache_key(self, context: DynamicAgentContext) -> str:
        """Compute a unique cache key based on context configuration.

        The key is a SHA256 hash of the serialized configuration to ensure
        that different configurations produce different graphs.
        """
        key_data = {
            "mode": context.multi_agent_mode,
            "model": context.model,
            "system_prompt": context.system_prompt,
            "supervisor_prompt": context.supervisor_system_prompt,
            "tools": sorted([str(t) for t in (context.tools or [])]),
            "knowledges": sorted(context.knowledges or []),
            "mcps": sorted(context.mcps or []),
            "skills": sorted(context.skills or []),
            "subagents": [
                {
                    "name": sa.get("name"),
                    "model": sa.get("model"),
                    "system_prompt": sa.get("system_prompt"),
                    "tools": sorted([str(t) for t in sa.get("tools", [])]),
                    "knowledges": sorted(sa.get("knowledges", [])),
                    "mcps": sorted(sa.get("mcps", [])),
                    "skills": sorted(sa.get("skills", [])),
                    "depends_on": sorted(sa.get("depends_on", [])),
                }
                for sa in (context.subagents or [])
            ],
        }
        serialized = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _get_cached_graph(self, cache_key: str) -> CompiledStateGraph | None:
        """Try to get a cached graph, checking TTL."""
        # Check strong cache first
        if cache_key in self._strong_cache:
            graph, created_at = self._strong_cache[cache_key]
            if time.time() - created_at < self._CACHE_TTL_SECONDS:
                logger.debug(f"Graph cache hit (strong): {cache_key}")
                return graph
            else:
                # Expired, remove from cache
                del self._strong_cache[cache_key]

        # Check weak cache
        if cache_key in self._graph_cache:
            graph = self._graph_cache.get(cache_key)
            if graph is not None:
                logger.debug(f"Graph cache hit (weak): {cache_key}")
                # Promote to strong cache
                self._cache_graph(cache_key, graph)
                return graph

        return None

    def _cache_graph(self, cache_key: str, graph: CompiledStateGraph) -> None:
        """Cache a graph with LRU eviction."""
        # Evict oldest entries if cache is full
        if len(self._strong_cache) >= self._CACHE_MAX_SIZE:
            oldest_key = min(self._strong_cache, key=lambda k: self._strong_cache[k][1])
            del self._strong_cache[oldest_key]
            logger.debug(f"Graph cache evicted: {oldest_key}")

        self._strong_cache[cache_key] = (graph, time.time())
        self._graph_cache[cache_key] = graph
        logger.debug(f"Graph cached: {cache_key}")

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached graphs."""
        cls._strong_cache.clear()
        cls._graph_cache.clear()
        logger.info("DynamicAgentFactory: graph cache cleared")

    async def _collect_mcp_tools(self, context: DynamicAgentContext) -> list[Any]:
        """Load only MCP tools required by current main agent + subagents."""
        started_at = time.perf_counter()
        server_names: list[str] = []

        if context.mcps:
            server_names.extend([name for name in context.mcps if isinstance(name, str) and name])

        for sa_config in context.subagents or []:
            if not isinstance(sa_config, dict):
                continue
            sa_mcps = sa_config.get("mcps") or []
            server_names.extend([name for name in sa_mcps if isinstance(name, str) and name])

        if not server_names:
            return []

        unique_server_names = list(dict.fromkeys(server_names))
        results = await asyncio.gather(
            *(get_enabled_mcp_tools(server_name) for server_name in unique_server_names),
            return_exceptions=True,
        )

        all_tools: list[Any] = []
        for server_name, result in zip(unique_server_names, results, strict=False):
            if isinstance(result, Exception):
                logger.warning(f"DynamicAgentFactory: failed to load MCP tools from '{server_name}': {result}")
                continue
            all_tools.extend(result)

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            f"DynamicAgentFactory: loaded {len(all_tools)} MCP tools from "
            f"{len(unique_server_names)} configured servers in {elapsed_ms:.1f}ms"
        )
        return all_tools

    async def build_graph(
        self,
        context: DynamicAgentContext,
        *,
        checkpointer: Any = None,
        store: Any = None,
    ) -> CompiledStateGraph:
        """Build a compiled graph based on the context configuration.

        Args:
            context: The DynamicAgentContext with all configuration.
            checkpointer: LangGraph checkpointer for state persistence.
            store: LangGraph store for persistent storage.

        Returns:
            A compiled LangGraph graph.
        """
        runtime_context = team_orchestration_service.build_runtime_context(
            {
                "team_goal": context.team_goal,
                "task_scope": context.task_scope,
                "multi_agent_mode": context.multi_agent_mode,
                "system_prompt": context.system_prompt,
                "supervisor_system_prompt": context.supervisor_system_prompt,
                "communication_protocol": context.communication_protocol,
                "max_parallel_tasks": context.max_parallel_tasks,
                "allow_cross_agent_comm": context.allow_cross_agent_comm,
                "tools": context.tools,
                "knowledges": context.knowledges,
                "mcps": context.mcps,
                "skills": context.skills,
                "subagents": context.subagents,
            },
            strict=True,
        )

        context.multi_agent_mode = runtime_context["multi_agent_mode"]
        context.system_prompt = runtime_context["system_prompt"]
        context.supervisor_system_prompt = runtime_context["supervisor_system_prompt"]
        context.subagents = runtime_context["subagents"]
        context.team_goal = runtime_context["team_goal"]
        context.task_scope = runtime_context["task_scope"]
        context.communication_protocol = runtime_context["communication_protocol"]
        context.max_parallel_tasks = runtime_context["max_parallel_tasks"]
        context.allow_cross_agent_comm = runtime_context["allow_cross_agent_comm"]
        context.tools = runtime_context["tools"]
        context.knowledges = runtime_context["knowledges"]
        context.mcps = runtime_context["mcps"]
        context.skills = runtime_context["skills"]

        mode = context.multi_agent_mode
        
        # Try to get cached graph (only for modes without external state dependencies)
        # Note: checkpointer and store are passed at compile time, so we can cache
        # the base graph structure and re-compile with new state backends
        cache_key = self._compute_cache_key(context)
        # For now, we don't use cache when checkpointer/store are provided
        # since they need to be bound at compile time
        use_cache = checkpointer is None and store is None
        
        if use_cache:
            cached = self._get_cached_graph(cache_key)
            if cached is not None:
                logger.info(f"DynamicAgentFactory: using cached graph (key={cache_key})")
                return cached

        if mode == "disabled" or not context.subagents:
            return await self._build_single_agent(context, checkpointer=checkpointer, store=store)
        elif mode == "supervisor":
            return await self._build_supervisor_mode(
                context,
                team_policy=runtime_context.get("team_policy") or {},
                checkpointer=checkpointer,
                store=store,
            )
        elif mode == "deep_agents":
            return await self._build_deep_agents_mode(
                context,
                team_policy=runtime_context.get("team_policy") or {},
                checkpointer=checkpointer,
                store=store,
            )
        elif mode == "swarm":
            return await self._build_swarm_mode(
                context,
                team_policy=runtime_context.get("team_policy") or {},
                checkpointer=checkpointer,
                store=store,
            )
        else:
            logger.warning(f"Unknown multi_agent_mode '{mode}', falling back to single agent")
            return await self._build_single_agent(context, checkpointer=checkpointer, store=store)

    async def _build_single_agent(
        self,
        context: DynamicAgentContext,
        *,
        checkpointer: Any = None,
        store: Any = None,
    ) -> CompiledStateGraph:
        """Build a single deep agent (no subagents)."""
        model = load_chat_model(context.model)
        tools = await ToolResolver.resolve(
            tool_ids=[t.get("name") if isinstance(t, dict) else t for t in (context.tools or [])],
            knowledges=context.knowledges,
            mcps=context.mcps,
        )
        mcp_tools = await self._collect_mcp_tools(context)
        skill_sources = resolve_skill_sources(context.skills)

        graph = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=context.system_prompt,
            skills=skill_sources or None,
            backend=create_state_store_backend,
            middleware=create_main_middlewares(model=model, mcp_tools=mcp_tools),
            checkpointer=checkpointer,
            store=store,
            name="dynamic_single_agent",
        )

        logger.info("DynamicAgentFactory: built single agent (disabled mode)")
        return graph

    async def _build_deep_agents_mode(
        self,
        context: DynamicAgentContext,
        *,
        team_policy: dict[str, Any] | None = None,
        checkpointer: Any = None,
        store: Any = None,
    ) -> CompiledStateGraph:
        """Build using Deep Agents task() mechanism (efficient, parallel)."""
        model = load_chat_model(context.model)
        main_tools = await ToolResolver.resolve(
            tool_ids=[t.get("name") if isinstance(t, dict) else t for t in (context.tools or [])],
            knowledges=context.knowledges,
            mcps=context.mcps,
        )
        mcp_tools = await self._collect_mcp_tools(context)
        main_skill_sources = resolve_skill_sources(context.skills)

        # Build compiled subagents so each subagent can own isolated tools + skills.
        subagent_runnables: list[dict[str, Any]] = []
        for sa_config in context.subagents:
            sa_tools = await ToolResolver.resolve(
                tool_ids=sa_config.get("tools", []),
                knowledges=sa_config.get("knowledges", []),
                mcps=sa_config.get("mcps", []),
            )
            sa_model = load_chat_model(sa_config["model"]) if sa_config.get("model") else model
            sa_skill_sources = resolve_skill_sources(sa_config.get("skills", []))
            depends_on = list(sa_config.get("depends_on") or [])
            allowed_targets = list(sa_config.get("allowed_targets") or [])
            communication_mode = sa_config.get("communication_mode") or "hybrid"
            subagent_contract = (
                "\n\n[Team Contract]\n"
                f"- 你的依赖: {', '.join(depends_on) if depends_on else '无'}\n"
                f"- 允许通信目标: {', '.join(allowed_targets) if allowed_targets else '无明确限制'}\n"
                f"- 通信模式: {communication_mode}\n"
                "- 禁止越权调用未授权的工具/知识库/MCP。\n"
                "- 结果必须给出可追踪证据，必要时写入文件。"
            )

            subagent_graph = create_deep_agent(
                model=sa_model,
                tools=sa_tools,
                system_prompt=f"{sa_config.get('system_prompt', '')}{subagent_contract}",
                skills=sa_skill_sources or None,
                backend=create_state_store_backend,
                middleware=create_subagent_middlewares(model=sa_model, mcp_tools=mcp_tools),
                name=f"dynamic_subagent_{sa_config['name']}",
            )

            subagent_runnables.append(
                {
                    "name": sa_config["name"],
                    "description": sa_config.get("description", ""),
                    "runnable": subagent_graph,
                }
            )

        execution_groups = (team_policy or {}).get("execution_groups") or []
        group_lines = [f"- 阶段 {idx + 1}: {', '.join(group)}" for idx, group in enumerate(execution_groups)]
        deep_mode_hint = (
            "\\n\\n[Deep Agents 执行约束]\\n"
            "1. 必须先做任务分解，再并行调度无依赖冲突的子任务。\\n"
            "2. 每轮结果聚合时若冲突，优先选择证据更完整的结论并记录冲突原因。\\n"
            "3. 严格遵守子Agent的 depends_on 与 allowed_targets 约束。\\n"
        )
        if group_lines:
            deep_mode_hint += "[并行阶段参考]\\n" + "\\n".join(group_lines)

        graph = create_deep_agent(
            model=model,
            tools=main_tools,
            system_prompt=f"{context.system_prompt}{deep_mode_hint}",
            subagents=subagent_runnables,
            skills=main_skill_sources or None,
            backend=create_state_store_backend,
            middleware=create_main_middlewares(model=model, mcp_tools=mcp_tools),
            checkpointer=checkpointer,
            store=store,
            name="dynamic_deep_agents",
        )

        logger.info(
            f"DynamicAgentFactory: built Deep Agents mode with "
            f"{len(subagent_runnables)} subagents: {[s['name'] for s in subagent_runnables]}"
        )
        return graph

    async def _build_supervisor_mode(
        self,
        context: DynamicAgentContext,
        *,
        team_policy: dict[str, Any] | None = None,
        checkpointer: Any = None,
        store: Any = None,
    ) -> CompiledStateGraph:
        """Build LangGraph Supervisor mode (fully observable subagents)."""
        model = load_chat_model(context.model)
        mcp_tools = await self._collect_mcp_tools(context)

        # Resolve tools for each subagent
        subagent_tools: dict[str, list] = {}
        subagent_configs_with_models: list[dict] = []

        for sa_config in context.subagents:
            name = sa_config["name"]
            sa_tools = await ToolResolver.resolve(
                tool_ids=sa_config.get("tools", []),
                knowledges=sa_config.get("knowledges", []),
                mcps=sa_config.get("mcps", []),
            )
            subagent_tools[name] = sa_tools

            # Resolve model for each subagent
            sa_model = load_chat_model(sa_config["model"]) if sa_config.get("model") else model
            config_with_model = {
                **sa_config,
                "model": sa_model,
                "skills": resolve_skill_sources(sa_config.get("skills", [])),
            }
            subagent_configs_with_models.append(config_with_model)

        graph = await build_supervisor_graph(
            model=model,
            subagent_configs=subagent_configs_with_models,
            subagent_tools=subagent_tools,
            supervisor_prompt=context.supervisor_system_prompt or None,
            team_policy=team_policy or {},
            mcp_tools=mcp_tools,
            checkpointer=checkpointer,
            store=store,
        )

        logger.info(
            f"DynamicAgentFactory: built Supervisor mode with "
            f"{len(context.subagents)} subagents: {[s['name'] for s in context.subagents]}"
        )
        return graph

    async def _build_swarm_mode(
        self,
        context: DynamicAgentContext,
        *,
        team_policy: dict[str, Any] | None = None,
        checkpointer: Any = None,
        store: Any = None,
    ) -> CompiledStateGraph:
        """Build Swarm mode with handoff-based agent collaboration.

        In Swarm mode, agents dynamically hand off control to one another
        based on their specializations. This is ideal for:
        - Customer support with specialist routing
        - Sales pipelines with different expert agents
        - Any workflow requiring dynamic agent-to-agent handoffs
        """
        model = load_chat_model(context.model)
        mcp_tools = await self._collect_mcp_tools(context)

        # Resolve tools for each subagent
        subagent_tools: dict[str, list] = {}
        subagent_configs_with_models: list[dict] = []

        for sa_config in context.subagents:
            name = sa_config["name"]
            sa_tools = await ToolResolver.resolve(
                tool_ids=sa_config.get("tools", []),
                knowledges=sa_config.get("knowledges", []),
                mcps=sa_config.get("mcps", []),
            )
            subagent_tools[name] = sa_tools

            # Resolve model for each subagent
            sa_model = load_chat_model(sa_config["model"]) if sa_config.get("model") else model
            config_with_model = {
                **sa_config,
                "model": sa_model,
                "skills": resolve_skill_sources(sa_config.get("skills", [])),
            }
            subagent_configs_with_models.append(config_with_model)

        # Determine default active agent (first agent or specified)
        default_active_agent = None
        if context.subagents:
            # Check if any agent is marked as default or use first one
            for sa_config in context.subagents:
                if sa_config.get("is_default") or sa_config.get("is_entry_point"):
                    default_active_agent = sa_config["name"]
                    break
            if not default_active_agent:
                default_active_agent = context.subagents[0]["name"]

        graph = await build_swarm_graph(
            model=model,
            subagent_configs=subagent_configs_with_models,
            subagent_tools=subagent_tools,
            default_active_agent=default_active_agent,
            mcp_tools=mcp_tools,
            checkpointer=checkpointer,
            store=store,
        )

        logger.info(
            f"DynamicAgentFactory: built Swarm mode with "
            f"{len(context.subagents)} agents: {[s['name'] for s in context.subagents]}, "
            f"default_active_agent='{default_active_agent}'"
        )
        return graph
