"""ArchitectAgent — AI-driven multi-agent team designer.

Uses create_deep_agent with three custom tools:
  get_available_resources, validate_team_config, deploy_team
"""

from deepagents import create_deep_agent

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.deepagent_runtime import (
    create_main_middlewares,
    create_state_store_backend,
)
from src.services.mcp_service import get_tools_from_all_servers
from src.utils.logging_config import logger

from .context import ArchitectContext
from .prompts import DEFAULT_ARCHITECT_PROMPT
from .tools import build_architect_tools


class ArchitectAgent(BaseAgent):
    name = "团队架构师"
    description = "通过对话帮助用户分析需求、设计团队拓扑、校验配置并一键部署多智能体协作团队"
    context_schema = ArchitectContext
    capabilities = ["todo", "files"]

    async def get_graph(self, **kwargs):
        context = self.context_schema.from_file(module_name=self.module_name)
        context.update(kwargs)

        user_id = getattr(context, "user_id", "")
        department_id = getattr(context, "department_id", None) or 0
        if not department_id:
            logger.warning("ArchitectAgent: department_id is missing, deploy_team will be unavailable")

        model = load_chat_model(context.model)
        architect_tools = build_architect_tools(user_id=user_id, department_id=int(department_id))

        all_mcp_tools = await get_tools_from_all_servers()

        system_prompt = context.system_prompt
        if not system_prompt or system_prompt == "You are a helpful assistant.":
            system_prompt = DEFAULT_ARCHITECT_PROMPT

        return create_deep_agent(
            model=model,
            tools=architect_tools,
            system_prompt=system_prompt,
            subagents=[],
            backend=create_state_store_backend,
            middleware=create_main_middlewares(model=model, mcp_tools=all_mcp_tools),
            checkpointer=await self._get_checkpointer(),
            store=await self._get_store(),
            name="architect_agent",
        )
