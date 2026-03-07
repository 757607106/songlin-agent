"""DynamicAgentFactory — builds agent graphs from context configuration.

Dispatches to the appropriate builder based on the multi_agent_mode:
- "disabled" → single deep agent (no subagents)
- "supervisor" → LangGraph StateGraph with subgraph nodes
- "deep_agents" → create_deep_agent(subagents=[...]) with task() tool
"""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.graph.state import CompiledStateGraph

from src.agents.common import load_chat_model
from src.agents.common.middlewares import RuntimeConfigMiddleware, save_attachments_to_fs
from src.agents.common.subagents.registry import ToolResolver
from src.services.mcp_service import get_tools_from_all_servers
from src.services.team_orchestration_service import team_orchestration_service
from src.utils import logger

from .context import DynamicAgentContext
from .supervisor import build_supervisor_graph


def _create_composite_backend(rt: Any) -> CompositeBackend:
    """Create a composite backend with state and store routes."""
    return CompositeBackend(
        default=StateBackend(rt),
        routes={
            "/memories/": StoreBackend(rt),
            "/preferences/": StoreBackend(rt),
        },
    )


class DynamicAgentFactory:
    """Factory that builds agent graphs from DynamicAgentContext.

    Usage:
        factory = DynamicAgentFactory()
        graph = await factory.build_graph(context, checkpointer=cp, store=st)
    """

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

        mode = context.multi_agent_mode

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
        all_mcp_tools = await get_tools_from_all_servers()

        graph = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=context.system_prompt,
            backend=_create_composite_backend,
            middleware=[
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
                save_attachments_to_fs,
            ],
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
        all_mcp_tools = await get_tools_from_all_servers()

        # Build subagent dicts for create_deep_agent
        subagent_dicts: list[dict] = []
        for sa_config in context.subagents:
            sa_tools = await ToolResolver.resolve(
                tool_ids=sa_config.get("tools", []),
                knowledges=sa_config.get("knowledges", []),
                mcps=sa_config.get("mcps", []),
            )
            sa_model = load_chat_model(sa_config["model"]) if sa_config.get("model") else model

            subagent_dict: dict[str, Any] = {
                "name": sa_config["name"],
                "description": sa_config.get("description", ""),
                "system_prompt": sa_config.get("system_prompt", ""),
                "tools": sa_tools,
                "model": sa_model,
                "middleware": [
                    RuntimeConfigMiddleware(
                        extra_tools=all_mcp_tools,
                        enable_model_override=False,
                        enable_system_prompt_override=False,
                        enable_tools_override=True,
                    ),
                ],
            }
            subagent_dicts.append(subagent_dict)

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
            subagents=subagent_dicts,
            backend=_create_composite_backend,
            middleware=[
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
                save_attachments_to_fs,
            ],
            checkpointer=checkpointer,
            store=store,
            name="dynamic_deep_agents",
        )

        logger.info(
            f"DynamicAgentFactory: built Deep Agents mode with "
            f"{len(subagent_dicts)} subagents: {[s['name'] for s in subagent_dicts]}"
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
        all_mcp_tools = await get_tools_from_all_servers()

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
            config_with_model = {**sa_config, "model": sa_model}
            subagent_configs_with_models.append(config_with_model)

        graph = await build_supervisor_graph(
            model=model,
            subagent_configs=subagent_configs_with_models,
            subagent_tools=subagent_tools,
            supervisor_prompt=context.supervisor_system_prompt or None,
            team_policy=team_policy or {},
            mcp_tools=all_mcp_tools,
            checkpointer=checkpointer,
            store=store,
        )

        logger.info(
            f"DynamicAgentFactory: built Supervisor mode with "
            f"{len(context.subagents)} subagents: {[s['name'] for s in context.subagents]}"
        )
        return graph
