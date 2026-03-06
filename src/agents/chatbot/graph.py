from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.middlewares import (
    RuntimeConfigMiddleware,
    save_attachments_to_fs,
)
from src.services.mcp_service import get_tools_from_all_servers


def _create_composite_backend(rt):
    return CompositeBackend(
        default=StateBackend(rt),
        routes={
            "/memories/": StoreBackend(rt),
            "/preferences/": StoreBackend(rt),
        },
    )


class ChatbotAgent(BaseAgent):
    name = "智能体助手"
    description = "基础的对话机器人，可以回答问题，可在配置中启用需要的工具。"
    capabilities = ["file_upload"]  # 支持文件上传功能

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def get_graph(self, **kwargs):
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)
        all_mcp_tools = await get_tools_from_all_servers()

        graph = create_deep_agent(
            model=load_chat_model(context.model),
            tools=[],
            system_prompt=context.system_prompt,
            backend=_create_composite_backend,
            middleware=[
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
                save_attachments_to_fs,
            ],
            checkpointer=await self._get_checkpointer(),
            store=await self._get_store(),
            name="chatbot_deep_agent",
        )

        return graph


def main():
    pass


if __name__ == "__main__":
    main()
    # asyncio.run(main())
