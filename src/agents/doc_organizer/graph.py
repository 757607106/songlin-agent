from deepagents import create_deep_agent
from deepagents.backends import StateBackend

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.middlewares import RuntimeConfigMiddleware, save_attachments_to_fs
from src.services.mcp_service import get_tools_from_all_servers

from .context import DocOrganizerContext


def _create_fs_backend(rt):
    return StateBackend(rt)


def _get_document_recognizer() -> dict:
    return {
        "name": "document-recognizer",
        "description": "识别附件文档结构、主题、关键信息并形成逐文档分析结果。",
        "system_prompt": (
            "你是文档识别专家。"
            "每次只处理一个附件文件。"
            "读取附件后输出结构化分析，写入 /analysis/<文件名>_analysis.md。"
            "分析必须包含主题、核心观点、术语、可复用知识点。"
        ),
        "tools": [],
    }


def _get_commonality_miner() -> dict:
    return {
        "name": "commonality-miner",
        "description": "从多个附件分析结果中提炼共性与通识知识。",
        "system_prompt": (
            "你是知识归纳专家。"
            "基于多个文档分析结果提炼通识知识与共性结构。"
            "输出内容写入 /organized/common_knowledge.md。"
            "要求去重、抽象、可复用，并保留对应来源文件路径。"
        ),
        "tools": [],
    }


def _get_organization_planner() -> dict:
    return {
        "name": "organization-planner",
        "description": "生成文档整理方案，等待用户确认后再执行。",
        "system_prompt": (
            "你是文档整理方案设计专家。"
            "根据共性知识和附件清单，生成可执行整理方案。"
            "写入 /organized/organize_plan.md。"
            "必须包含目录结构、内容合并规则、逐文件输出映射、格式回写策略与回退策略。"
            "完成后提醒主agent等待用户确认。"
        ),
        "tools": [],
    }


def _get_renderer() -> dict:
    return {
        "name": "renderer-agent",
        "description": "根据已确认方案产出最终标准文档。",
        "system_prompt": (
            "你是文档编排与成稿专家。"
            "仅在用户确认方案后执行。"
            "生成 /organized/merged_standard.md。"
            "按原后缀优先生成 /organized/by_file/<名称>_standard.<原后缀>。"
            "若无法稳定回写原后缀，使用 .md 并更新 /organized/format_mapping.md。"
        ),
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
        self.graph = None
        self.checkpointer = None

    async def get_graph(self, **kwargs):
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)

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
            backend=_create_fs_backend,
            middleware=[
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
                save_attachments_to_fs,
            ],
            checkpointer=await self._get_checkpointer(),
            name="document_organizer_agent",
        )
        return graph
