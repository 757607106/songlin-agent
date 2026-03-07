from deepagents import create_deep_agent

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.deepagent_runtime import (
    create_main_middlewares,
    create_state_store_backend,
)
from src.services.mcp_service import get_tools_from_all_servers


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
        model = load_chat_model(context.model)

        graph = create_deep_agent(
            model=model,
            tools=[],
            system_prompt=context.system_prompt,
            backend=create_state_store_backend,
            middleware=create_main_middlewares(model=model, mcp_tools=all_mcp_tools),
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
