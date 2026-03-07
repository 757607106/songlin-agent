"""Subagent registry and tool resolver for dynamic agent creation.

Provides:
- ToolResolver: resolves tool ID strings to actual tool objects
- SubAgentRegistry: manages pre-compiled LangGraph subgraphs for CompiledSubAgent usage
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from src.agents.common.tools import get_buildin_tools, get_kb_based_tools, get_tavily_search
from src.services.mcp_service import get_enabled_mcp_tools
from src.utils import logger


class ToolResolver:
    """Resolve tool IDs to actual tool objects.

    Supports three categories:
    - Built-in tools (e.g., "calculator", "query_knowledge_graph")
    - Knowledge base tools (dynamically created from configured KBs)
    - MCP server tools (loaded from external MCP servers)
    - Tavily search tool (if API key is configured)
    """

    @staticmethod
    async def resolve(
        tool_ids: list[str] | None = None,
        *,
        knowledges: list[str] | None = None,
        mcps: list[str] | None = None,
    ) -> list[BaseTool]:
        """Resolve a list of tool IDs to actual tool objects.

        Args:
            tool_ids: Built-in tool names to include (e.g., ["calculator"]).
            knowledges: Knowledge base names to create retriever tools for.
            mcps: MCP server names to load tools from.

        Returns:
            List of resolved tool objects.
        """
        resolved: list[BaseTool] = []

        # 1. Built-in tools
        if tool_ids:
            builtin_map = {t.name: t for t in get_buildin_tools()}
            for tid in tool_ids:
                if tid in builtin_map:
                    resolved.append(builtin_map[tid])
                else:
                    logger.warning(f"ToolResolver: unknown built-in tool '{tid}', skipped")

        # 2. Knowledge base tools
        if knowledges:
            try:
                kb_tools = await get_kb_based_tools(db_names=knowledges)
                resolved.extend(kb_tools)
            except Exception as e:
                logger.warning(f"ToolResolver: failed to load KB tools, skipped: {e}")

        # 3. Tavily search
        tavily = get_tavily_search()
        if tavily:
            resolved.append(tavily)

        # 4. MCP tools
        if mcps:
            for server_name in mcps:
                try:
                    mcp_tools = await get_enabled_mcp_tools(server_name)
                    resolved.extend(mcp_tools)
                except Exception as e:
                    logger.warning(f"ToolResolver: failed to load MCP tools from `{server_name}`, skipped: {e}")

        return resolved


class SubAgentRegistry:
    """Registry for pre-compiled LangGraph subgraphs.

    Pre-registered subgraphs can be referenced by name from the frontend
    to be included as CompiledSubAgent instances in a dynamic agent.

    Usage:
        registry = SubAgentRegistry()
        registry.register("sql-reporter", SqlReporterAgent)
        graph = await registry.get_compiled("sql-reporter")
    """

    _instance: SubAgentRegistry | None = None

    def __new__(cls) -> SubAgentRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._registry: dict[str, dict[str, Any]] = {}
        return cls._instance

    def register(self, name: str, agent_class: type, *, description: str = "") -> None:
        """Register a BaseAgent subclass as a reusable compiled subagent.

        Args:
            name: Unique reference name for frontend usage.
            agent_class: A BaseAgent subclass that implements get_graph().
            description: Human-readable description of the subagent's purpose.
        """
        self._registry[name] = {
            "agent_class": agent_class,
            "description": description,
        }
        logger.info(f"SubAgentRegistry: registered '{name}' -> {agent_class.__name__}")

    async def get_compiled(self, name: str, **kwargs) -> Any:
        """Get a compiled graph from a registered agent class.

        Args:
            name: The registered reference name.
            **kwargs: Additional arguments passed to get_graph().

        Returns:
            A compiled LangGraph StateGraph.

        Raises:
            KeyError: If no agent is registered under the given name.
        """
        if name not in self._registry:
            raise KeyError(f"SubAgentRegistry: '{name}' not found. Available: {list(self._registry.keys())}")
        entry = self._registry[name]
        agent_instance = entry["agent_class"]()
        return await agent_instance.get_graph(**kwargs)

    def list_available(self) -> list[dict[str, str]]:
        """List all registered subagents with their descriptions."""
        return [{"name": name, "description": entry["description"]} for name, entry in self._registry.items()]


# Module-level singleton
subagent_registry = SubAgentRegistry()
