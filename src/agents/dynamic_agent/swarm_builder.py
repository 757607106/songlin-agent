"""Swarm mode builder — handoff-based multi-agent collaboration.

Constructs a multi-agent graph where:
- Agents dynamically hand off control to one another based on their specializations
- The system remembers which agent was last active
- Each agent can have its own tools, prompts, and specializations

Use cases:
- Customer support with specialist routing
- Sales pipelines with different expert agents
- Any workflow requiring dynamic agent-to-agent handoffs
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph_swarm import create_handoff_tool, create_swarm

from src.agents.common.deepagent_runtime import create_subagent_middlewares
from src.services.skill_catalog_service import resolve_skill_sources
from src.utils import logger


async def build_swarm_graph(
    *,
    model: BaseChatModel,
    subagent_configs: list[dict],
    subagent_tools: dict[str, list],
    default_active_agent: str | None = None,
    mcp_tools: list | None = None,
    checkpointer: Any = None,
    store: Any = None,
) -> CompiledStateGraph:
    """Build a Swarm mode graph with handoff-based agent collaboration.

    Args:
        model: The default LLM model for agents without a specific model.
        subagent_configs: List of subagent configuration dicts, each containing:
            - name: Agent name (required)
            - description: Agent description for handoff tool
            - system_prompt: Agent's system prompt
            - model: Optional model override
            - tools: Resolved tool list (passed via subagent_tools)
            - skills: Optional skill sources
        subagent_tools: Mapping of subagent name -> resolved tool list.
        default_active_agent: Name of the agent to start with. Defaults to first agent.
        mcp_tools: MCP tools to add via middleware.
        checkpointer: LangGraph checkpointer for state persistence.
        store: LangGraph store for persistent storage.

    Returns:
        A compiled LangGraph StateGraph with swarm routing.
    """
    if not subagent_configs:
        raise ValueError("Swarm mode requires at least one subagent configuration")

    agent_names = [sa["name"] for sa in subagent_configs]
    agents = []

    for config in subagent_configs:
        agent_name = config["name"]
        agent_model = config.get("model") or model
        agent_tools = list(subagent_tools.get(agent_name, []))

        # Create handoff tools for this agent to transfer to other agents
        handoff_tools = []
        for other_config in subagent_configs:
            other_name = other_config["name"]
            if other_name == agent_name:
                continue

            # Check allowed_targets constraint
            allowed_targets = config.get("allowed_targets") or []
            if allowed_targets and other_name not in allowed_targets:
                continue

            handoff_tool = create_handoff_tool(
                agent_name=other_name,
                description=f"Transfer conversation to {other_name}: {other_config.get('description', 'Specialist agent')}",
            )
            handoff_tools.append(handoff_tool)

        # Combine agent tools with handoff tools
        all_tools = agent_tools + handoff_tools

        # Build system prompt with team contract
        base_prompt = config.get("system_prompt", "")
        depends_on = list(config.get("depends_on") or [])
        allowed_targets_list = list(config.get("allowed_targets") or [])
        communication_mode = config.get("communication_mode") or "hybrid"

        team_contract = (
            "\n\n[Swarm Team Contract]\n"
            f"- Your role: {agent_name}\n"
            f"- Dependencies: {', '.join(depends_on) if depends_on else 'None'}\n"
            f"- Allowed handoff targets: {', '.join(allowed_targets_list) if allowed_targets_list else 'All other agents'}\n"
            f"- Communication mode: {communication_mode}\n"
            "- Use handoff tools to transfer conversations to specialists when needed.\n"
            "- Only handoff when the other agent is better suited to handle the request.\n"
            "- Provide context when handing off to ensure smooth transitions."
        )

        final_prompt = f"{base_prompt}{team_contract}"

        # Resolve skills if provided
        skill_sources = resolve_skill_sources(config.get("skills", []))

        # Create the agent using LangChain's create_agent
        # Note: create_agent returns a compiled graph
        agent = create_agent(
            model=agent_model,
            tools=all_tools,
            system_prompt=final_prompt,
            name=agent_name,
            skills=skill_sources or None,
            middleware=create_subagent_middlewares(model=agent_model, mcp_tools=mcp_tools or []),
        )
        agents.append(agent)

    # Determine default active agent
    if default_active_agent is None:
        default_active_agent = agent_names[0]
    elif default_active_agent not in agent_names:
        logger.warning(
            f"SwarmBuilder: default_active_agent '{default_active_agent}' not found, "
            f"falling back to '{agent_names[0]}'"
        )
        default_active_agent = agent_names[0]

    # Create the swarm workflow
    workflow = create_swarm(agents, default_active_agent=default_active_agent)

    # Compile with checkpointer and store
    graph = workflow.compile(
        checkpointer=checkpointer,
        store=store,
    )

    logger.info(
        f"SwarmBuilder: graph compiled with {len(agents)} agents: {agent_names}, "
        f"default_active_agent='{default_active_agent}'"
    )
    return graph
