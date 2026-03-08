"""ArchitectAgent tools — resource query, config validation, team deployment.

Each public factory accepts user context and returns a list of LangChain tools
bound to that context via closures.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool
from langgraph.types import interrupt

from src.agents.common.tools import gen_tool_info, get_buildin_tools, get_kb_based_tools
from src.services.mcp_service import get_mcp_server_names
from src.services.skill_catalog_service import list_skill_catalog
from src.services.team_orchestration_service import team_orchestration_service
from src.utils import logger


def build_architect_tools(*, user_id: str, department_id: int) -> list:
    """Build the three ArchitectAgent tools with user context bound via closures."""

    @tool(name_or_callable="get_available_resources")
    def get_available_resources(category: str | None = None) -> str:
        """查询当前可用的资源（工具、知识库、MCP 服务器、技能）。

        Args:
            category: 可选，筛选某一类资源。可选值: tools / knowledges / mcps / skills。
                      留空返回所有类别。
        """
        result: dict[str, Any] = {}

        categories = (
            [category]
            if category in ("tools", "knowledges", "mcps", "skills")
            else ["tools", "knowledges", "mcps", "skills"]
        )

        if "tools" in categories:
            builtin = get_buildin_tools()
            result["tools"] = [
                {"id": t["id"], "name": t["name"], "description": t["description"]} for t in gen_tool_info(builtin)
            ]

        if "knowledges" in categories:
            kb_tools = get_kb_based_tools()
            result["knowledges"] = [{"name": t.name, "description": t.description} for t in kb_tools]

        if "mcps" in categories:
            names = get_mcp_server_names()
            result["mcps"] = [{"name": n} for n in names]

        if "skills" in categories:
            catalog = list_skill_catalog()
            result["skills"] = [
                {"id": s["id"], "name": s["name"], "description": s.get("description", "")} for s in catalog
            ]

        return json.dumps(result, ensure_ascii=False, indent=2)

    @tool(name_or_callable="validate_team_config")
    def validate_team_config(team_config: str) -> str:
        """校验团队配置是否合法（依赖关系、命名、职责重叠、资源引用等）。

        Args:
            team_config: JSON 格式的团队配置字符串。
        """
        try:
            payload = json.loads(team_config)
        except json.JSONDecodeError as exc:
            return json.dumps(
                {"valid": False, "errors": [f"JSON 解析失败: {exc}"]},
                ensure_ascii=False,
            )

        result = team_orchestration_service.validate_team(payload, strict=False)
        # Only return fields useful for the LLM
        return json.dumps(
            {
                "valid": result["valid"],
                "errors": result["errors"],
                "warnings": result["warnings"],
                "dependency_order": result["dependency_order"],
                "responsibility_overlap": result["responsibility_overlap"],
            },
            ensure_ascii=False,
            indent=2,
        )

    @tool(name_or_callable="deploy_team")
    async def deploy_team(team_config: str, name: str, description: str = "") -> str:
        """部署团队配置——严格校验后请求用户确认，确认后写入数据库。

        Args:
            team_config: JSON 格式的团队配置字符串。
            name: 团队配置的显示名称。
            description: 可选的配置描述。
        """
        # 1. Parse
        try:
            payload = json.loads(team_config)
        except json.JSONDecodeError as exc:
            return json.dumps({"success": False, "error": f"JSON 解析失败: {exc}"}, ensure_ascii=False)

        if not department_id:
            return json.dumps({"success": False, "error": "当前用户未绑定部门，无法部署团队"}, ensure_ascii=False)

        # 2. Strict validation
        validation = team_orchestration_service.validate_team(payload, strict=True)
        if not validation["valid"]:
            return json.dumps(
                {"success": False, "errors": validation["errors"]},
                ensure_ascii=False,
            )

        # 3. Build runtime context
        try:
            runtime_context = team_orchestration_service.build_runtime_context(payload, strict=True)
        except ValueError as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

        # 4. HITL — ask user to approve
        team_preview = {
            "team_goal": runtime_context.get("team_goal", ""),
            "multi_agent_mode": runtime_context.get("multi_agent_mode", ""),
            "subagents": [
                {"name": sa["name"], "description": sa["description"]} for sa in runtime_context.get("subagents", [])
            ],
        }

        approved = interrupt(
            {
                "question": f"即将部署团队配置「{name}」，是否确认？",
                "operation": "deploy_team",
                "team_preview": team_preview,
            }
        )

        if not approved:
            return json.dumps({"success": False, "error": "用户取消了部署"}, ensure_ascii=False)

        # 5. Write to database
        try:
            from src.repositories.agent_config_repository import AgentConfigRepository
            from src.storage.postgres.manager import pg_manager

            async with pg_manager.get_async_session_context() as session:
                repo = AgentConfigRepository(session)
                config = await repo.create(
                    department_id=department_id,
                    agent_id="DynamicAgent",
                    name=name,
                    description=description or team_preview["team_goal"],
                    config_json={"context": runtime_context},
                    is_default=False,
                    created_by=user_id,
                )
                logger.info("Deployed team config id={} name={!r}", config.id, config.name)

            return json.dumps(
                {"success": True, "config_id": config.id, "name": config.name},
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.error("Failed to deploy team config: {}", exc)
            return json.dumps({"success": False, "error": f"数据库写入失败: {exc}"}, ensure_ascii=False)

    return [get_available_resources, validate_team_config, deploy_team]
