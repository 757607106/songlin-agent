from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.middlewares import RuntimeConfigMiddleware, save_attachments_to_fs
from src.services.mcp_service import get_tools_from_all_servers

from .context import DocOrganizerContext


def _create_composite_backend(rt):
    return CompositeBackend(
        default=StateBackend(rt),
        routes={
            "/memories/": StoreBackend(rt),
            "/preferences/": StoreBackend(rt),
        },
    )


def _get_document_recognizer() -> dict:
    """Get document recognizer sub-agent config.

    子 Agent 不预设 system_prompt，文件路径规范由主 Agent 提示词定义，
    通过 task description 动态传递给子 Agent。
    """
    return {
        "name": "document-recognizer",
        "description": "识别附件文档结构、主题、关键信息并形成逐文档分析结果。",
        "system_prompt": "",  # 空字符串，由主 Agent task description 指定
        "tools": [],
    }


def _get_commonality_miner() -> dict:
    """Get commonality miner sub-agent config.

    子 Agent 不预设 system_prompt，文件路径规范由主 Agent 提示词定义，
    通过 task description 动态传递给子 Agent。
    """
    return {
        "name": "commonality-miner",
        "description": "从多个附件分析结果中提炼共性与通识知识。",
        "system_prompt": "",  # 空字符串，由主 Agent task description 指定
        "tools": [],
    }


def _get_organization_planner() -> dict:
    """Get organization planner sub-agent config.

    子 Agent 不预设 system_prompt，文件路径规范由主 Agent 提示词定义，
    通过 task description 动态传递给子 Agent。
    """
    return {
        "name": "organization-planner",
        "description": "生成文档整理方案，等待用户确认后再执行。",
        "system_prompt": "",  # 空字符串，由主 Agent task description 指定
        "tools": [],
    }


def _get_renderer() -> dict:
    """Get renderer sub-agent config.

    子 Agent 不预设 system_prompt，文件路径规范由主 Agent 提示词定义，
    通过 task description 动态传递给子 Agent。
    """
    return {
        "name": "renderer-agent",
        "description": "根据已确认方案产出最终标准文档。",
        "system_prompt": "",  # 空字符串，由主 Agent task description 指定
        "tools": [],
    }


class DocOrganizerAgent(BaseAgent):
    name = "文档整理智能体"
    description = "基于Deep Agents的会话附件文档整理智能体，支持方案确认后再生成标准文档。"
    context_schema = DocOrganizerContext
    capabilities = [
        "file_upload",
        "todo",
        "files",
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._graph_cache: dict[tuple[str, str, tuple[str, ...]], object] = {}

    async def get_graph(self, **kwargs):
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)
        mcp_servers = tuple(context.mcps or [])
        cache_key = (context.model, context.system_prompt, mcp_servers)
        cached_graph = self._graph_cache.get(cache_key)
        if cached_graph is not None:
            return cached_graph

        model = load_chat_model(context.model)
        all_mcp_tools = await get_tools_from_all_servers()
        subagents = [
            _get_document_recognizer(),
            _get_commonality_miner(),
            _get_organization_planner(),
            _get_renderer(),
        ]
        for subagent in subagents:
            subagent["model"] = model
            subagent["middleware"] = [
                RuntimeConfigMiddleware(
                    extra_tools=all_mcp_tools,
                    enable_model_override=False,
                    enable_system_prompt_override=False,
                    enable_tools_override=True,
                )
            ]

        graph = create_deep_agent(
            model=model,
            tools=[],
            system_prompt=context.system_prompt,
            subagents=subagents,
            backend=_create_composite_backend,
            middleware=[
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
                save_attachments_to_fs,
            ],
            checkpointer=await self._get_checkpointer(),
            store=await self._get_store(),
            name="document_organizer_agent",
        )
        self._graph_cache[cache_key] = graph
        return graph
