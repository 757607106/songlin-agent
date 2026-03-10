"""DynamicAgent — a configurable multi-mode agent.

Supports three collaboration modes via frontend configuration:
- disabled: Single deep agent
- supervisor: LangGraph Supervisor with observable subgraph nodes
- deep_agents: Deep Agents task() mechanism (efficient, parallel)
"""

from __future__ import annotations

import asyncio
import time

from src.agents.common import BaseAgent
from src.utils import logger

from .context import DynamicAgentContext
from .factory import DynamicAgentFactory


class DynamicAgent(BaseAgent):
    """Configurable multi-mode agent supporting single and multi-agent collaboration.

    Users configure the agent through the frontend:
    - Choose collaboration mode (disabled / supervisor / deep_agents)
    - Define subagents with their own tools, prompts, and models
    - Supervisor mode provides full streaming observability of subagent steps

    This agent is automatically discovered by AgentManager.auto_discover_agents().
    """

    name = "动态多智能体"
    description = (
        "支持多种协作模式的灵活智能体。"
        "可配置为单智能体模式，或多智能体协作模式（Supervisor 可观测模式 / Deep Agents 高效模式）。"
    )
    context_schema = DynamicAgentContext
    capabilities = [
        "file_upload",
        "todo",
        "files",
        "multi_agent",
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._graph_cache: dict[str, object] = {}
        self._graph_build_locks: dict[str, asyncio.Lock] = {}
        self._factory = DynamicAgentFactory()

    def _build_context(self, input_context: dict | None = None) -> DynamicAgentContext:
        """Build runtime context from input, needed to pass user-specific config to get_graph."""
        context = self._build_runtime_context(input_context)
        return context  # type: ignore[return-value]

    async def stream_messages(self, messages: list[str], input_context=None, **kwargs):
        """Override to pass runtime context (mode, subagents) into get_graph().

        Uses stream_mode="messages" which directly yields (msg, metadata) tuples,
        matching what chat_stream_service expects.

        Adapts the astream call based on graph type:
        - Deep agent graphs (disabled/deep_agents mode) accept `context` param
        - Vanilla StateGraph (supervisor mode) does not accept `context` param
        """
        context = self._build_context(input_context)
        graph = await self.get_graph(
            model=context.model,
            system_prompt=context.system_prompt,
            multi_agent_mode=context.multi_agent_mode,
            team_goal=context.team_goal,
            task_scope=context.task_scope,
            communication_protocol=context.communication_protocol,
            max_parallel_tasks=context.max_parallel_tasks,
            allow_cross_agent_comm=context.allow_cross_agent_comm,
            subagents=context.subagents,
            supervisor_system_prompt=context.supervisor_system_prompt,
            tools=context.tools,
            knowledges=context.knowledges,
            mcps=context.mcps,
            skills=context.skills,
        )

        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 300,
        }

        is_supervisor = context.multi_agent_mode == "supervisor" and context.subagents

        if is_supervisor:
            # Supervisor mode:使用多模式流式 + subgraphs=True，保留完整子 Agent 可观测性
            async for item in graph.astream(
                {"messages": messages},
                stream_mode=["messages", "updates"],
                config=input_config,
                subgraphs=True,
            ):
                namespace, mode, data = item[0], item[1], item[2]
                is_subagent = any(s.startswith("tools:") for s in namespace) if namespace else False
                subagent_name = None
                if is_subagent and namespace:
                    for ns in namespace:
                        if ns.startswith("tools:"):
                            subagent_name = ns.split(":")[0] if ":" in ns else ns
                            break

                if mode == "messages":
                    msg, metadata = data
                    enriched_metadata = dict(metadata) if metadata else {}
                    enriched_metadata["is_subagent"] = is_subagent
                    enriched_metadata["subagent_name"] = subagent_name
                    enriched_metadata["namespace"] = list(namespace) if namespace else []
                    # Supervisor 内部路由 token（如 {"next": "...", "reason": "..."}）不应直接透传给用户
                    if enriched_metadata.get("langgraph_node") == "supervisor":
                        continue
                    yield msg, enriched_metadata
                elif mode == "updates":
                    update_event = {
                        "type": "state_update",
                        "is_subagent": is_subagent,
                        "subagent_name": subagent_name,
                        "namespace": list(namespace) if namespace else [],
                        "nodes": list(data.keys()) if isinstance(data, dict) else [],
                        "data": data,
                    }
                    yield update_event, {"mode": "updates"}
        else:
            # Deep agent modes: support `context` param
            async for msg, metadata in graph.astream(
                {"messages": messages},
                stream_mode="messages",
                context=context,
                config=input_config,
            ):
                yield msg, metadata

    async def invoke_messages(self, messages: list[str], input_context=None, **kwargs):
        """Override to pass runtime context into get_graph()."""
        context = self._build_context(input_context)
        graph = await self.get_graph(
            model=context.model,
            system_prompt=context.system_prompt,
            multi_agent_mode=context.multi_agent_mode,
            team_goal=context.team_goal,
            task_scope=context.task_scope,
            communication_protocol=context.communication_protocol,
            max_parallel_tasks=context.max_parallel_tasks,
            allow_cross_agent_comm=context.allow_cross_agent_comm,
            subagents=context.subagents,
            supervisor_system_prompt=context.supervisor_system_prompt,
            tools=context.tools,
            knowledges=context.knowledges,
            mcps=context.mcps,
            skills=context.skills,
        )

        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 100,
        }

        is_supervisor = context.multi_agent_mode == "supervisor" and context.subagents

        if is_supervisor:
            result = await graph.ainvoke(
                {"messages": messages},
                config=input_config,
            )
        else:
            result = await graph.ainvoke(
                {"messages": messages},
                context=context,
                config=input_config,
            )
        return result

    async def get_graph(self, **kwargs):
        """Build the agent graph based on context configuration.

        The graph type depends on context.multi_agent_mode:
        - "disabled" → single create_deep_agent()
        - "supervisor" → LangGraph StateGraph with subgraph nodes
        - "deep_agents" → create_deep_agent(subagents=[...])

        Caching is based on model, mode, system prompt, and subagent config.
        """
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)

        # Build a cache key from relevant configuration
        import hashlib
        import json

        cache_data = json.dumps(
            {
                "model": context.model,
                "mode": context.multi_agent_mode,
                "system_prompt": context.system_prompt,
                "team_goal": context.team_goal,
                "task_scope": context.task_scope,
                "communication_protocol": context.communication_protocol,
                "max_parallel_tasks": context.max_parallel_tasks,
                "allow_cross_agent_comm": context.allow_cross_agent_comm,
                "subagents": context.subagents,
                "tools": [t.get("name") if isinstance(t, dict) else t for t in (context.tools or [])],
                "knowledges": context.knowledges or [],
                "mcps": context.mcps or [],
                "skills": context.skills or [],
                "supervisor_prompt": context.supervisor_system_prompt,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        cache_key = hashlib.md5(cache_data.encode()).hexdigest()

        cached = self._graph_cache.get(cache_key)
        if cached is not None:
            return cached

        lock = self._graph_build_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = self._graph_cache.get(cache_key)
            if cached is not None:
                return cached

            # Build the graph via factory
            started_at = time.perf_counter()
            graph = await self._factory.build_graph(
                context,
                checkpointer=await self._get_checkpointer(),
                store=await self._get_store(),
            )
            build_ms = (time.perf_counter() - started_at) * 1000

            self._graph_cache[cache_key] = graph
            logger.info(
                f"DynamicAgent graph built: mode={context.multi_agent_mode}, "
                f"subagents={len(context.subagents)}, cache_key={cache_key[:8]}..., build_ms={build_ms:.1f}"
            )
            return graph
