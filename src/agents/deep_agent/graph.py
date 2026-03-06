"""Deep Agent - 基于create_deep_agent的深度分析智能体"""

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.middlewares import RuntimeConfigMiddleware, save_attachments_to_fs
from src.agents.common.tools import get_tavily_search
from src.services.mcp_service import get_tools_from_all_servers

from .context import DeepContext


def _create_composite_backend(rt):
    return CompositeBackend(
        default=StateBackend(rt),
        routes={
            "/memories/": StoreBackend(rt),
            "/preferences/": StoreBackend(rt),
        },
    )


def _get_research_sub_agent(search_tools: list) -> dict:
    """Get research sub-agent config with search tools."""
    return {
        "name": "research-agent",
        "description": ("利用搜索工具，用于研究更深入的问题。将调研结果写入到主题研究文件中。"),
        "system_prompt": (
            "你是一位专注的研究员。你的工作是根据用户的问题进行研究。"
            "进行彻底的研究，然后用详细的答案回复用户的问题，只有你的最终答案会被传递给用户。"
            "除了你的最终信息，他们不会知道任何其他事情，所以你的最终报告应该就是你的最终信息！"
            "将调研结果保存到主题研究文件中 /sub_research/xxx.md 中。"
        ),
        "tools": search_tools,
    }


def _get_critique_sub_agent(search_tools: list) -> dict:
    return {
        "name": "critique-agent",
        "description": "用于评论最终报告。给这个代理一些关于你希望它如何评论报告的信息。",
        "system_prompt": (
            "你是一位专注的编辑。你的任务是评论一份报告。\n\n"
            "你可以在 `final_report.md` 找到这份报告。\n\n"
            "你可以在 `question.txt` 找到这份报告的问题/主题。\n\n"
            "用户可能会要求评论报告的特定方面。请用详细的评论回复用户，指出报告中可以改进的地方。\n\n"
            "如果有助于你评论报告，你可以使用搜索工具来搜索信息\n\n"
            "不要自己写入 `final_report.md`。\n\n"
            "需要检查的事项：\n"
            "- 检查每个部分的标题是否恰当\n"
            "- 检查报告的写法是否像论文或教科书——它应该是以文本为主，不要只是一个项目符号列表！\n"
            "- 检查报告是否全面。如果任何段落或部分过短，或缺少重要细节，请指出来。\n"
            "- 检查文章是否涵盖了行业的关键领域，确保了整体理解，并且没有遗漏重要部分。\n"
            "- 检查文章是否深入分析了原因、影响和趋势，提供了有价值的见解\n"
            "- 检查文章是否紧扣研究主题并直接回答问题\n"
            "- 检查文章是否结构清晰、语言流畅、易于理解。"
        ),
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
        research_sub_agent["middleware"] = [
            RuntimeConfigMiddleware(
                extra_tools=all_mcp_tools,
                enable_model_override=False,
                enable_system_prompt_override=False,
                enable_tools_override=True,
            )
        ]
        critique_sub_agent = _get_critique_sub_agent(search_tools)
        critique_sub_agent["model"] = model
        critique_sub_agent["middleware"] = [
            RuntimeConfigMiddleware(
                extra_tools=all_mcp_tools,
                enable_model_override=False,
                enable_system_prompt_override=False,
                enable_tools_override=True,
            )
        ]

        # 关键说明：这里改为官方 create_deep_agent 入口，子agent通过 subagents 参数注册。
        # 这样与 reporter 的 deep-agent 化方案一致，维护成本更低。
        graph = create_deep_agent(
            model=model,
            tools=search_tools,
            system_prompt=context.system_prompt,
            subagents=[critique_sub_agent, research_sub_agent],
            backend=_create_composite_backend,
            middleware=[
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
                save_attachments_to_fs,
            ],
            checkpointer=await self._get_checkpointer(),
            store=await self._get_store(),
            name="deep_research_agent",
        )
        self._graph_cache[cache_key] = graph
        return graph
