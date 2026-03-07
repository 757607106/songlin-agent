"""Deep Agent - 基于create_deep_agent的深度分析智能体"""

from deepagents import create_deep_agent

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.deepagent_runtime import (
    create_main_middlewares,
    create_state_store_backend,
    create_subagent_middlewares,
)
from src.agents.common.tools import get_tavily_search
from src.services.mcp_service import get_tools_from_all_servers

from .context import DeepContext


def _get_research_sub_agent(search_tools: list) -> dict:
    """Get research sub-agent config with search tools.

    子 Agent 不预设 system_prompt，由主 Agent 在调用 task() 时通过
    description 参数动态指定具体任务要求。
    """
    return {
        "name": "research-agent",
        "description": "利用搜索工具进行深度调研，返回详细的研究报告。",
        "system_prompt": "",  # 空字符串，由主 Agent task description 指定
        "tools": search_tools,
    }


def _get_critique_sub_agent(search_tools: list) -> dict:
    """Get critique sub-agent config.

    子 Agent 不预设 system_prompt，由主 Agent 在调用 task() 时通过
    description 参数动态指定评论要求和检查清单。
    """
    return {
        "name": "critique-agent",
        "description": "评论和审核报告内容，指出可改进之处。",
        "system_prompt": "",  # 空字符串，由主 Agent task description 指定
        "tools": search_tools,
    }


class DeepAgent(BaseAgent):
    name = "深度分析智能体"
    description = "具备规划、深度分析和子智能体协作能力的智能体，可以处理复杂的多步骤任务"
    context_schema = DeepContext
    capabilities = [
        "file_upload",
        "todo",
        "files",
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._graph_cache: dict[tuple[str, str, tuple[str, ...]], object] = {}

    async def get_tools(self):
        """返回 Deep Agent 的专用工具"""
        tools = []
        tavily_search = get_tavily_search()
        if tavily_search:
            tools.append(tavily_search)

        # Assert that search tool is available for DeepAgent
        assert tools, "DeepAgent 需要至少一个搜索工具。请配置 TAVILY_API_KEY 环境变量以启用网络搜索。"
        return tools

    async def get_graph(self, **kwargs):
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)
        mcp_servers = tuple(context.mcps or [])
        cache_key = (context.model, context.system_prompt, mcp_servers)
        cached_graph = self._graph_cache.get(cache_key)
        if cached_graph is not None:
            return cached_graph

        model = load_chat_model(context.model)
        search_tools = await self.get_tools()
        all_mcp_tools = await get_tools_from_all_servers()

        research_sub_agent = _get_research_sub_agent(search_tools)
        research_sub_agent["model"] = model
        research_sub_agent["middleware"] = create_subagent_middlewares(model=model, mcp_tools=all_mcp_tools)
        critique_sub_agent = _get_critique_sub_agent(search_tools)
        critique_sub_agent["model"] = model
        critique_sub_agent["middleware"] = create_subagent_middlewares(model=model, mcp_tools=all_mcp_tools)

        # 关键说明：这里改为官方 create_deep_agent 入口，子agent通过 subagents 参数注册。
        # 这样与 reporter 的 deep-agent 化方案一致，维护成本更低。
        graph = create_deep_agent(
            model=model,
            tools=search_tools,
            system_prompt=context.system_prompt,
            subagents=[critique_sub_agent, research_sub_agent],
            backend=create_state_store_backend,
            middleware=create_main_middlewares(model=model, mcp_tools=all_mcp_tools),
            checkpointer=await self._get_checkpointer(),
            store=await self._get_store(),
            name="deep_research_agent",
        )
        self._graph_cache[cache_key] = graph
        return graph
