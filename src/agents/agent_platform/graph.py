from __future__ import annotations

import asyncio
import time

from src.agents.common import BaseAgent
from src.utils import logger

from .context import AgentPlatformContext
from .factory import AgentPlatformFactory


class AgentPlatformAgent(BaseAgent):
    name = "Agent Platform Runtime"
    description = "新平台生成 Agent 的统一运行时入口。"
    context_schema = AgentPlatformContext
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
        self._factory = AgentPlatformFactory()

    def _build_context(self, input_context: dict | None = None) -> AgentPlatformContext:
        context = self._build_runtime_context(input_context)
        return context  # type: ignore[return-value]

    async def stream_messages(self, messages: list[str], input_context=None, **kwargs):
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
                    if enriched_metadata.get("langgraph_node") == "supervisor":
                        continue
                    yield msg, enriched_metadata
                elif mode == "updates":
                    yield {
                        "type": "state_update",
                        "is_subagent": is_subagent,
                        "subagent_name": subagent_name,
                        "namespace": list(namespace) if namespace else [],
                        "nodes": list(data.keys()) if isinstance(data, dict) else [],
                        "data": data,
                    }, {"mode": "updates"}
            return

        async for msg, metadata in graph.astream(
            {"messages": messages},
            stream_mode="messages",
            context=context,
            config=input_config,
        ):
            yield msg, metadata

    async def invoke_messages(self, messages: list[str], input_context=None, **kwargs):
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
            return await graph.ainvoke({"messages": messages}, config=input_config)
        return await graph.ainvoke({"messages": messages}, context=context, config=input_config)

    async def get_graph(self, **kwargs):
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)

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

            started_at = time.perf_counter()
            graph = await self._factory.build_graph(
                context,
                checkpointer=await self._get_checkpointer(),
                store=await self._get_store(),
            )
            build_ms = (time.perf_counter() - started_at) * 1000

            self._graph_cache[cache_key] = graph
            logger.info(
                f"AgentPlatformAgent graph built: mode={context.multi_agent_mode}, "
                f"subagents={len(context.subagents)}, cache_key={cache_key[:8]}..., build_ms={build_ms:.1f}"
            )
            return graph
