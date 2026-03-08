import asyncio
import json
import textwrap
import traceback
import uuid
from datetime import UTC, datetime
from time import monotonic

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.models_business import User
from server.routers.auth_router import get_admin_user
from server.utils.auth_middleware import get_db, get_required_user
from src import config as conf, knowledge_base
from src.agents import agent_manager
from src.agents.common.tools import get_buildin_tools
from src.models import select_model
from src.repositories.conversation_repository import ConversationRepository
from src.services.chat_stream_service import get_agent_state_view, stream_agent_chat, stream_agent_resume
from src.services.conversation_service import (
    create_thread_view,
    delete_thread_attachment_view,
    delete_thread_view,
    list_thread_attachments_view,
    list_threads_view,
    update_thread_view,
    upload_thread_attachment_view,
)
from src.services.feedback_service import get_message_feedback_view, submit_message_feedback_view
from src.services.mcp_service import get_mcp_server_names
from src.services.skill_catalog_service import get_skill_names
from src.services.history_query_service import get_agent_history_view
from src.services.task_service import TaskContext, tasker
from src.services.team_orchestration_service import team_orchestration_service
from src.repositories.agent_config_repository import AgentConfigRepository
from src.utils.logging_config import logger
from src.utils.image_processor import process_uploaded_image


# 图片上传响应模型
class ImageUploadResponse(BaseModel):
    success: bool
    image_content: str | None = None
    thumbnail_content: str | None = None
    width: int | None = None
    height: int | None = None
    format: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    error: str | None = None


class AgentConfigCreate(BaseModel):
    name: str
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    examples: list[str] | None = None
    config_json: dict | None = None
    set_default: bool = False


class AgentConfigUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    examples: list[str] | None = None
    config_json: dict | None = None


class TeamWizardRequest(BaseModel):
    message: str
    draft: dict | None = None
    auto_complete: bool = True


class TeamValidationRequest(BaseModel):
    team: dict
    strict: bool = True


class TeamCreateRequest(BaseModel):
    name: str
    team: dict
    description: str | None = None
    set_default: bool = False


class TeamAutoCreateRequest(BaseModel):
    message: str
    name: str | None = None
    description: str | None = None
    set_default: bool = True
    auto_complete: bool = True


class TeamDocsQueryRequest(BaseModel):
    query: str
    server_name: str = "langchain-docs"


class TeamBenchmarkRequest(BaseModel):
    team: dict
    iterations: int = 8
    async_task: bool = False


class TeamSessionCreateRequest(BaseModel):
    title: str | None = None
    message: str | None = None
    draft: dict | None = None
    auto_complete: bool = True


class TeamSessionMessageRequest(BaseModel):
    message: str
    auto_complete: bool = True


class TeamSessionDraftUpdateRequest(BaseModel):
    draft: dict
    strict: bool = True


class TeamSessionCreateProfileRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    set_default: bool = True


chat = APIRouter(prefix="/chat", tags=["chat"])
TEAM_SESSION_TYPE = "team_builder"
_TEAM_STATIC_RESOURCES_CACHE_TTL_SECONDS = 15.0
_TEAM_KNOWLEDGE_CACHE_TTL_SECONDS = 10.0
_team_static_resources_cache: dict[str, object] = {"expires_at": 0.0, "value": None}
_team_knowledge_cache: dict[str, tuple[float, list[str]]] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get_static_team_resources() -> dict[str, list[str]]:
    now = monotonic()
    expires_at = float(_team_static_resources_cache.get("expires_at") or 0.0)
    cached = _team_static_resources_cache.get("value")
    if now < expires_at and isinstance(cached, dict):
        return {
            "tools": list(cached.get("tools") or []),
            "mcps": list(cached.get("mcps") or []),
            "skills": list(cached.get("skills") or []),
        }

    refreshed = {
        "tools": sorted({tool.name for tool in get_buildin_tools() if getattr(tool, "name", None)}),
        "mcps": sorted(set(get_mcp_server_names())),
        "skills": sorted(set(get_skill_names())),
    }
    _team_static_resources_cache["value"] = refreshed
    _team_static_resources_cache["expires_at"] = now + _TEAM_STATIC_RESOURCES_CACHE_TTL_SECONDS
    return {
        "tools": list(refreshed["tools"]),
        "mcps": list(refreshed["mcps"]),
        "skills": list(refreshed["skills"]),
    }


def _team_knowledge_cache_key(current_user: User) -> str:
    return f"{current_user.role}:{current_user.department_id or ''}"


def _suggest_team_profile_name(team_goal: str, fallback_message: str) -> str:
    source = (team_goal or fallback_message or "").strip()
    if not source:
        return "AI自动组建团队"
    compact = source.replace("：", " ").replace(":", " ").strip()
    compact = compact[:24].strip()
    return compact or "AI自动组建团队"


def _ensure_dynamic_agent(agent_id: str, message: str) -> None:
    if agent_id != "DynamicAgent":
        raise HTTPException(status_code=422, detail=message)


def _ensure_dynamic_or_admin(agent_id: str, current_user: User) -> None:
    if agent_id == "DynamicAgent":
        return
    if current_user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="需要管理员权限")


async def _build_team_available_resources(current_user: User) -> dict[str, list[str]]:
    static_resources = _get_static_team_resources()

    knowledge_names: list[str] = []
    now = monotonic()
    cache_key = _team_knowledge_cache_key(current_user)
    cached_knowledge = _team_knowledge_cache.get(cache_key)
    if cached_knowledge and now < cached_knowledge[0]:
        knowledge_names = list(cached_knowledge[1])
    else:
        user_info = {
            "role": current_user.role,
            "department_id": current_user.department_id,
        }
        if knowledge_base is not None:
            try:
                accessible = await knowledge_base.get_databases_by_user(user_info)
                knowledge_names = sorted(
                    {
                        db.get("name")
                        for db in (accessible or {}).get("databases", [])
                        if isinstance(db, dict) and db.get("name")
                    }
                )
                _team_knowledge_cache[cache_key] = (now + _TEAM_KNOWLEDGE_CACHE_TTL_SECONDS, knowledge_names)
            except Exception as exc:
                logger.warning(f"Failed to load accessible knowledges for user {current_user.id}: {exc}")
                if cached_knowledge:
                    knowledge_names = list(cached_knowledge[1])

    return {
        "tools": static_resources["tools"],
        "knowledges": knowledge_names,
        "mcps": static_resources["mcps"],
        "skills": static_resources["skills"],
    }


def _build_team_builder_state(result: dict) -> dict:
    return {
        "draft": result.get("draft") or {},
        "validation": result.get("validation") or {},
        "mode_recommendation": result.get("mode_recommendation") or {},
        "assembly_meta": result.get("assembly_meta") or {},
        "resource_validation": result.get("resource_validation") or {},
        "questions": result.get("questions") or [],
        "assistant_message": result.get("assistant_message") or "",
        "is_complete": bool(result.get("is_complete")),
        "updated_at": _now_iso(),
    }


async def _get_team_session_conversation_or_404(
    *,
    conv_repo: ConversationRepository,
    thread_id: str,
    current_user: User,
) -> tuple[object, dict]:
    conversation = await conv_repo.get_conversation_by_thread_id(thread_id)
    if not conversation or conversation.user_id != str(current_user.id) or conversation.status == "deleted":
        raise HTTPException(status_code=404, detail="团队会话不存在")

    metadata = conversation.extra_metadata or {}
    if metadata.get("session_type") != TEAM_SESSION_TYPE:
        raise HTTPException(status_code=404, detail="团队会话不存在")
    if conversation.agent_id != "DynamicAgent":
        raise HTTPException(status_code=404, detail="团队会话不存在")
    return conversation, metadata


def _serialize_team_history(messages: list[object]) -> list[dict]:
    history: list[dict] = []
    for item in messages:
        role = getattr(item, "role", "")
        content = getattr(item, "content", "")
        created_at = getattr(item, "created_at", None)
        history.append(
            {
                "role": role,
                "content": content,
                "created_at": created_at.isoformat() if created_at else None,
            }
        )
    return history


def _team_stream_chunk(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _split_stream_text(text: str, chunk_size: int = 24) -> list[str]:
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


# =============================================================================
# > === 智能体管理分组 ===
# =============================================================================


@chat.get("/default_agent")
async def get_default_agent(current_user: User = Depends(get_required_user)):
    """获取默认智能体ID（需要登录）"""
    try:
        default_agent_id = conf.default_agent_id
        # 如果没有设置默认智能体，尝试获取第一个可用的智能体
        if not default_agent_id:
            agents = await agent_manager.get_agents_info()
            if agents:
                default_agent_id = agents[0].get("id", "")

        return {"default_agent_id": default_agent_id}
    except Exception as e:
        logger.error(f"获取默认智能体出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取默认智能体出错: {str(e)}")


@chat.post("/set_default_agent")
async def set_default_agent(request_data: dict = Body(...), current_user=Depends(get_admin_user)):
    """设置默认智能体ID (仅管理员)"""
    try:
        agent_id = request_data.get("agent_id")
        if not agent_id:
            raise HTTPException(status_code=422, detail="缺少必需的 agent_id 字段")

        # 验证智能体是否存在
        agents = await agent_manager.get_agents_info()
        agent_ids = [agent.get("id", "") for agent in agents]

        if agent_id not in agent_ids:
            raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

        # 设置默认智能体ID
        conf.default_agent_id = agent_id
        # 保存配置
        conf.save()

        return {"success": True, "default_agent_id": agent_id}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"设置默认智能体出错: {e}")
        raise HTTPException(status_code=500, detail=f"设置默认智能体出错: {str(e)}")


@chat.post("/call")
async def call(query: str = Body(...), meta: dict = Body(None), current_user: User = Depends(get_required_user)):
    """调用模型进行简单问答（需要登录）"""
    meta = meta or {}

    # 确保 request_id 存在
    if "request_id" not in meta or not meta.get("request_id"):
        meta["request_id"] = str(uuid.uuid4())

    model = select_model(
        model_provider=meta.get("model_provider"),
        model_name=meta.get("model_name"),
        model_spec=meta.get("model_spec") or meta.get("model"),
    )

    response = await model.call(query)
    logger.debug({"query": query, "response": response.content})

    return {"response": response.content, "request_id": meta["request_id"]}


@chat.post("/optimize-prompt")
async def optimize_prompt(
    prompt: str = Body(..., description="待优化的提示词"),
    agent_type: str = Body("", description="智能体类型（可选，用于优化上下文）"),
    current_user: User = Depends(get_required_user),
):
    """使用 LLM 优化智能体系统提示词

    根据用户输入的提示词，生成更清晰、更专业的优化版本。
    """
    if not prompt or not prompt.strip():
        raise HTTPException(status_code=400, detail="提示词不能为空")

    # 构建优化提示词
    optimization_prompt = textwrap.dedent(f"""
        你是一个 AI 提示词优化专家。请帮我优化以下智能体系统提示词。

        待优化的提示词:
        {prompt}

        优化要求：
        1. 保持原有提示词的核心意图和功能
        2. 使语言更加清晰、结构化
        3. 添加必要的角色定义和行为指导
        4. 明确输入输出格式和限制条件
        5. 如果原提示词太短或模糊，可以适当扩展
        6. 确保提示词适合作为 AI 智能体的系统提示词使用
        7. 优化后的提示词应该简洁有力，通常 5-15 句即可
        8. 如果原提示词已经很好，可以只做微调或保持不变

        请直接输出优化后的提示词，不要有任何前缀说明或解释。
    """).strip()

    try:
        model = select_model()
        response = await model.call(optimization_prompt)
        optimized = response.content.strip()
        logger.debug(f"Optimized prompt: {optimized[:100]}...")
        return {"optimized_prompt": optimized, "status": "success"}
    except Exception as e:
        logger.error(f"优化提示词失败: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"优化提示词失败: {e}")


@chat.get("/agent")
async def get_agent(current_user: User = Depends(get_required_user)):
    """获取所有可用智能体的基本信息（需要登录）"""
    agents_info = await agent_manager.get_agents_info()

    # Return agents with basic information (without configurable_items for performance)
    agents = [
        {
            "id": agent_info["id"],
            "name": agent_info.get("name", "Unknown"),
            "description": agent_info.get("description", ""),
            "examples": agent_info.get("examples", []),
            "has_checkpointer": agent_info.get("has_checkpointer", False),
            "capabilities": agent_info.get("capabilities", []),  # 智能体能力列表
        }
        for agent_info in agents_info
    ]

    return {"agents": agents}


@chat.get("/agent/{agent_id}")
async def get_single_agent(agent_id: str, current_user: User = Depends(get_required_user)):
    """获取指定智能体的完整信息（包含配置选项）（需要登录）"""
    try:
        # 检查智能体是否存在
        if not (agent := agent_manager.get_agent(agent_id)):
            raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

        # 获取智能体的完整信息（包含 configurable_items）
        agent_info = await agent.get_info()

        return {
            "id": agent_info["id"],
            "name": agent_info.get("name", "Unknown"),
            "description": agent_info.get("description", ""),
            "examples": agent_info.get("examples", []),
            "configurable_items": agent_info.get("configurable_items", []),
            "has_checkpointer": agent_info.get("has_checkpointer", False),
            "capabilities": agent_info.get("capabilities", []),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取智能体 {agent_id} 信息出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取智能体信息出错: {str(e)}")


@chat.post("/agent/reload")
async def reload_agents(current_user: User = Depends(get_admin_user)):
    """重新发现并加载 Agent 插件模块（仅管理员）。"""
    await agent_manager.reload_all()
    agents_info = await agent_manager.get_agents_info()
    return {"success": True, "agents": [agent.get("id") for agent in agents_info]}


@chat.get("/agent/{agent_id}/configs")
async def list_agent_configs(
    agent_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")

    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

    repo = AgentConfigRepository(db)
    items = await repo.list_by_department_agent(department_id=current_user.department_id, agent_id=agent_id)
    if not items:
        await repo.get_or_create_default(
            department_id=current_user.department_id,
            agent_id=agent_id,
            created_by=str(current_user.id),
        )
        items = await repo.list_by_department_agent(department_id=current_user.department_id, agent_id=agent_id)

    configs = [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "icon": item.icon,
            "pics": item.pics or [],
            "examples": item.examples or [],
            "is_default": bool(item.is_default),
        }
        for item in items
    ]
    return {"configs": configs}


@chat.get("/agent/{agent_id}/configs/{config_id}")
async def get_agent_config_profile(
    agent_id: str,
    config_id: int,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")

    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="配置不存在")

    return {"config": item.to_dict()}


@chat.post("/agent/{agent_id}/configs")
async def create_agent_config_profile(
    agent_id: str,
    payload: AgentConfigCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")

    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_or_admin(agent_id, current_user)

    repo = AgentConfigRepository(db)
    item = await repo.create(
        department_id=current_user.department_id,
        agent_id=agent_id,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        pics=payload.pics,
        examples=payload.examples,
        config_json=payload.config_json,
        is_default=payload.set_default,
        created_by=str(current_user.id),
    )
    if payload.set_default:
        item = await repo.set_default(config=item, updated_by=str(current_user.id))

    return {"config": item.to_dict()}


@chat.put("/agent/{agent_id}/configs/{config_id}")
async def update_agent_config_profile(
    agent_id: str,
    config_id: int,
    payload: AgentConfigUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")

    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_or_admin(agent_id, current_user)

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="配置不存在")

    updated = await repo.update(
        item,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        pics=payload.pics,
        examples=payload.examples,
        config_json=payload.config_json,
        updated_by=str(current_user.id),
    )
    return {"config": updated.to_dict()}


@chat.post("/agent/{agent_id}/configs/{config_id}/set_default")
async def set_agent_config_default(
    agent_id: str,
    config_id: int,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")

    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_or_admin(agent_id, current_user)

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="配置不存在")

    updated = await repo.set_default(config=item, updated_by=str(current_user.id))
    return {"config": updated.to_dict()}


@chat.delete("/agent/{agent_id}/configs/{config_id}")
async def delete_agent_config_profile(
    agent_id: str,
    config_id: int,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")

    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_or_admin(agent_id, current_user)

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="配置不存在")

    await repo.delete(config=item, updated_by=str(current_user.id))
    return {"success": True}


@chat.post("/agent/{agent_id}/team/wizard")
async def team_wizard_step(
    agent_id: str,
    payload: TeamWizardRequest,
    current_user: User = Depends(get_required_user),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队创建仅支持 DynamicAgent")
    available_resources = await _build_team_available_resources(current_user)

    return await team_orchestration_service.wizard_step_with_ai(
        payload.message,
        payload.draft,
        auto_complete=payload.auto_complete,
        available_resources=available_resources,
    )


@chat.post("/agent/{agent_id}/team/validate")
async def validate_team_config(
    agent_id: str,
    payload: TeamValidationRequest,
    current_user: User = Depends(get_required_user),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队校验仅支持 DynamicAgent")
    available_resources = await _build_team_available_resources(current_user)

    return team_orchestration_service.validate_team(
        payload.team,
        strict=payload.strict,
        available_resources=available_resources,
    )


@chat.post("/agent/{agent_id}/team/create")
async def create_team_profile(
    agent_id: str,
    payload: TeamCreateRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队创建仅支持 DynamicAgent")
    _ensure_dynamic_or_admin(agent_id, current_user)
    available_resources = await _build_team_available_resources(current_user)

    runtime_context = team_orchestration_service.build_runtime_context(
        payload.team,
        strict=True,
        available_resources=available_resources,
        assembly_meta={
            "pipeline": "direct_create_request",
            "status": "provided_by_user",
            "attempts": [],
        },
    )

    repo = AgentConfigRepository(db)
    item = await repo.create(
        department_id=current_user.department_id,
        agent_id=agent_id,
        name=payload.name,
        description=payload.description,
        config_json={"context": runtime_context},
        is_default=payload.set_default,
        created_by=str(current_user.id),
    )
    if payload.set_default:
        item = await repo.set_default(config=item, updated_by=str(current_user.id))

    return {
        "config": item.to_dict(),
        "team_validation": team_orchestration_service.validate_team(
            payload.team,
            available_resources=available_resources,
        ),
    }


@chat.post("/agent/{agent_id}/team/auto-create")
async def auto_create_team_profile(
    agent_id: str,
    payload: TeamAutoCreateRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队自动创建仅支持 DynamicAgent")
    _ensure_dynamic_or_admin(agent_id, current_user)
    available_resources = await _build_team_available_resources(current_user)

    wizard = await team_orchestration_service.wizard_step_with_ai(
        payload.message,
        draft=None,
        auto_complete=payload.auto_complete,
        available_resources=available_resources,
    )
    draft = wizard.get("draft") or {}
    if not wizard.get("is_complete"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "AI 已生成草稿，但仍缺少必要字段",
                "questions": wizard.get("questions") or [],
                "draft": draft,
                "validation": wizard.get("validation") or {},
            },
        )

    runtime_context = team_orchestration_service.build_runtime_context(
        draft,
        strict=True,
        available_resources=available_resources,
        assembly_meta=wizard.get("assembly_meta") or {},
        mode_recommendation=wizard.get("mode_recommendation") or {},
    )
    profile_name = payload.name or _suggest_team_profile_name(runtime_context.get("team_goal", ""), payload.message)
    profile_desc = payload.description or runtime_context.get("task_scope") or runtime_context.get("team_goal")

    repo = AgentConfigRepository(db)
    item = await repo.create(
        department_id=current_user.department_id,
        agent_id=agent_id,
        name=profile_name,
        description=profile_desc,
        config_json={"context": runtime_context},
        is_default=payload.set_default,
        created_by=str(current_user.id),
    )
    if payload.set_default:
        item = await repo.set_default(config=item, updated_by=str(current_user.id))

    return {
        "config": item.to_dict(),
        "wizard": wizard,
        "team_validation": team_orchestration_service.validate_team(
            draft,
            strict=True,
            available_resources=available_resources,
        ),
    }


@chat.post("/agent/{agent_id}/team/session")
async def create_team_session(
    agent_id: str,
    payload: TeamSessionCreateRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队会话仅支持 DynamicAgent")

    available_resources = await _build_team_available_resources(current_user)
    conv_repo = ConversationRepository(db)

    if payload.message and payload.message.strip():
        wizard = await team_orchestration_service.wizard_step_with_ai(
            payload.message.strip(),
            payload.draft,
            auto_complete=payload.auto_complete,
            available_resources=available_resources,
        )
    else:
        wizard = team_orchestration_service.wizard_step(
            "",
            payload.draft,
            available_resources=available_resources,
        )

    team_builder_state = _build_team_builder_state(wizard)
    title = payload.title or (team_builder_state["draft"].get("team_goal") or "团队组建会话")
    conversation = await conv_repo.create_conversation(
        user_id=str(current_user.id),
        agent_id=agent_id,
        title=title,
        metadata={
            "session_type": TEAM_SESSION_TYPE,
            "team_builder": team_builder_state,
        },
    )

    if payload.message and payload.message.strip():
        await conv_repo.add_message_by_thread_id(
            thread_id=conversation.thread_id,
            role="user",
            content=payload.message.strip(),
            message_type="text",
            extra_metadata={"session_type": TEAM_SESSION_TYPE},
        )
        assistant_message = team_builder_state.get("assistant_message") or ""
        if assistant_message:
            await conv_repo.add_message_by_thread_id(
                thread_id=conversation.thread_id,
                role="assistant",
                content=assistant_message,
                message_type="text",
                extra_metadata={"session_type": TEAM_SESSION_TYPE},
            )

    history = await conv_repo.get_messages_by_thread_id(conversation.thread_id)
    return {
        "thread_id": conversation.thread_id,
        "title": conversation.title,
        "team_builder": team_builder_state,
        "history": _serialize_team_history(history),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


@chat.get("/agent/{agent_id}/team/sessions")
async def list_team_sessions(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队会话仅支持 DynamicAgent")

    conv_repo = ConversationRepository(db)
    conversations = await conv_repo.list_conversations(
        user_id=str(current_user.id),
        agent_id=agent_id,
        status="active",
        limit=max(limit + 40, 80),
        offset=0,
    )
    sessions = []
    for conv in conversations:
        metadata = conv.extra_metadata or {}
        if metadata.get("session_type") != TEAM_SESSION_TYPE:
            continue
        team_builder = metadata.get("team_builder") or {}
        sessions.append(
            {
                "thread_id": conv.thread_id,
                "title": conv.title,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "team_builder": team_builder,
            }
        )

    return {"sessions": sessions[offset : offset + limit]}


@chat.get("/agent/{agent_id}/team/session/{thread_id}")
async def get_team_session(
    agent_id: str,
    thread_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队会话仅支持 DynamicAgent")

    conv_repo = ConversationRepository(db)
    conversation, metadata = await _get_team_session_conversation_or_404(
        conv_repo=conv_repo,
        thread_id=thread_id,
        current_user=current_user,
    )
    history = await conv_repo.get_messages_by_thread_id(thread_id)
    return {
        "thread_id": thread_id,
        "title": conversation.title,
        "team_builder": metadata.get("team_builder") or {},
        "history": _serialize_team_history(history),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


@chat.post("/agent/{agent_id}/team/session/{thread_id}/message")
async def send_team_session_message(
    agent_id: str,
    thread_id: str,
    payload: TeamSessionMessageRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=422, detail="message 不能为空")
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队会话仅支持 DynamicAgent")

    conv_repo = ConversationRepository(db)
    conversation, metadata = await _get_team_session_conversation_or_404(
        conv_repo=conv_repo,
        thread_id=thread_id,
        current_user=current_user,
    )

    available_resources = await _build_team_available_resources(current_user)
    current_state = metadata.get("team_builder") or {}
    current_draft = current_state.get("draft") or {}
    wizard = await team_orchestration_service.wizard_step_with_ai(
        payload.message.strip(),
        current_draft,
        auto_complete=payload.auto_complete,
        available_resources=available_resources,
    )
    team_builder_state = _build_team_builder_state(wizard)

    await conv_repo.add_message_by_thread_id(
        thread_id=thread_id,
        role="user",
        content=payload.message.strip(),
        message_type="text",
        extra_metadata={"session_type": TEAM_SESSION_TYPE},
    )
    assistant_message = team_builder_state.get("assistant_message") or ""
    if assistant_message:
        await conv_repo.add_message_by_thread_id(
            thread_id=thread_id,
            role="assistant",
            content=assistant_message,
            message_type="text",
            extra_metadata={"session_type": TEAM_SESSION_TYPE},
        )

    updated = await conv_repo.update_conversation(
        thread_id=thread_id,
        metadata={
            "session_type": TEAM_SESSION_TYPE,
            "team_builder": team_builder_state,
        },
    )

    history = await conv_repo.get_messages_by_thread_id(thread_id)
    return {
        "thread_id": thread_id,
        "title": (updated or conversation).title,
        "team_builder": team_builder_state,
        "history": _serialize_team_history(history),
        "updated_at": (
            (updated or conversation).updated_at.isoformat() if (updated or conversation).updated_at else None
        ),
    }


@chat.post("/agent/{agent_id}/team/session/{thread_id}/message/stream")
async def stream_team_session_message(
    agent_id: str,
    thread_id: str,
    payload: TeamSessionMessageRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=422, detail="message 不能为空")
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队会话仅支持 DynamicAgent")

    conv_repo = ConversationRepository(db)
    conversation, metadata = await _get_team_session_conversation_or_404(
        conv_repo=conv_repo,
        thread_id=thread_id,
        current_user=current_user,
    )
    available_resources = await _build_team_available_resources(current_user)
    request_id = str(uuid.uuid4())
    assistant_msg_id = f"{request_id}-assistant"

    async def generate():
        try:
            current_state = metadata.get("team_builder") or {}
            current_draft = current_state.get("draft") or {}
            wizard = await team_orchestration_service.wizard_step_with_ai(
                payload.message.strip(),
                current_draft,
                auto_complete=payload.auto_complete,
                available_resources=available_resources,
            )
            team_builder_state = _build_team_builder_state(wizard)

            yield _team_stream_chunk(
                {
                    "status": "init",
                    "request_id": request_id,
                    "thread_id": thread_id,
                }
            )

            assistant_message = team_builder_state.get("assistant_message") or ""
            for part in _split_stream_text(assistant_message):
                yield _team_stream_chunk(
                    {
                        "status": "loading",
                        "request_id": request_id,
                        "thread_id": thread_id,
                        "msg": {
                            "type": "AIMessageChunk",
                            "id": assistant_msg_id,
                            "content": part,
                        },
                    }
                )
                await asyncio.sleep(0.01)

            await conv_repo.add_message_by_thread_id(
                thread_id=thread_id,
                role="user",
                content=payload.message.strip(),
                message_type="text",
                extra_metadata={"session_type": TEAM_SESSION_TYPE},
            )
            if assistant_message:
                await conv_repo.add_message_by_thread_id(
                    thread_id=thread_id,
                    role="assistant",
                    content=assistant_message,
                    message_type="text",
                    extra_metadata={"session_type": TEAM_SESSION_TYPE},
                )

            updated = await conv_repo.update_conversation(
                thread_id=thread_id,
                metadata={
                    "session_type": TEAM_SESSION_TYPE,
                    "team_builder": team_builder_state,
                },
            )

            yield _team_stream_chunk(
                {
                    "status": "finished",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "title": (updated or conversation).title,
                    "team_builder": team_builder_state,
                    "updated_at": (updated or conversation).updated_at.isoformat()
                    if (updated or conversation).updated_at
                    else None,
                }
            )
        except asyncio.CancelledError:
            logger.info(f"Team session stream cancelled: thread_id={thread_id}, request_id={request_id}")
            raise
        except Exception as exc:
            logger.error(f"Team session stream failed: {exc}")
            logger.error(traceback.format_exc())
            yield _team_stream_chunk(
                {
                    "status": "error",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "message": str(exc),
                }
            )

    return StreamingResponse(generate(), media_type="application/json")


@chat.put("/agent/{agent_id}/team/session/{thread_id}/draft")
async def update_team_session_draft(
    agent_id: str,
    thread_id: str,
    payload: TeamSessionDraftUpdateRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队会话仅支持 DynamicAgent")

    conv_repo = ConversationRepository(db)
    _, _ = await _get_team_session_conversation_or_404(
        conv_repo=conv_repo,
        thread_id=thread_id,
        current_user=current_user,
    )
    available_resources = await _build_team_available_resources(current_user)
    wizard = team_orchestration_service.wizard_step(
        "",
        payload.draft,
        available_resources=available_resources,
    )
    team_builder_state = _build_team_builder_state(wizard)
    if payload.strict:
        strict_validation = team_orchestration_service.validate_team(
            payload.draft,
            strict=True,
            available_resources=available_resources,
        )
        if not strict_validation["valid"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "团队草稿不满足严格校验",
                    "validation": strict_validation,
                },
            )
        team_builder_state["validation"] = strict_validation
        team_builder_state["resource_validation"] = strict_validation.get("resource_validation") or {}

    updated = await conv_repo.update_conversation(
        thread_id=thread_id,
        metadata={
            "session_type": TEAM_SESSION_TYPE,
            "team_builder": team_builder_state,
        },
    )

    return {
        "thread_id": thread_id,
        "title": updated.title if updated else "",
        "team_builder": team_builder_state,
        "updated_at": updated.updated_at.isoformat() if updated and updated.updated_at else None,
    }


@chat.post("/agent/{agent_id}/team/session/{thread_id}/create")
async def create_team_profile_from_session(
    agent_id: str,
    thread_id: str,
    payload: TeamSessionCreateProfileRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    _ensure_dynamic_agent(agent_id, "团队会话仅支持 DynamicAgent")
    _ensure_dynamic_or_admin(agent_id, current_user)

    conv_repo = ConversationRepository(db)
    conversation, metadata = await _get_team_session_conversation_or_404(
        conv_repo=conv_repo,
        thread_id=thread_id,
        current_user=current_user,
    )
    team_builder_state = metadata.get("team_builder") or {}
    draft = team_builder_state.get("draft") or {}
    available_resources = await _build_team_available_resources(current_user)
    runtime_context = team_orchestration_service.build_runtime_context(
        draft,
        strict=True,
        available_resources=available_resources,
        assembly_meta=team_builder_state.get("assembly_meta") or {},
        mode_recommendation=team_builder_state.get("mode_recommendation") or {},
    )
    validation = team_orchestration_service.validate_team(
        draft,
        strict=True,
        available_resources=available_resources,
    )

    profile_name = payload.name or _suggest_team_profile_name(
        runtime_context.get("team_goal", ""),
        conversation.title or "团队组建会话",
    )
    profile_desc = payload.description or runtime_context.get("task_scope") or runtime_context.get("team_goal")

    repo = AgentConfigRepository(db)
    item = await repo.create(
        department_id=current_user.department_id,
        agent_id=agent_id,
        name=profile_name,
        description=profile_desc,
        config_json={"context": runtime_context},
        is_default=payload.set_default,
        created_by=str(current_user.id),
    )
    if payload.set_default:
        item = await repo.set_default(config=item, updated_by=str(current_user.id))

    team_builder_state["last_created_config_id"] = item.id
    team_builder_state["updated_at"] = _now_iso()
    await conv_repo.update_conversation(
        thread_id=thread_id,
        metadata={
            "session_type": TEAM_SESSION_TYPE,
            "team_builder": team_builder_state,
        },
    )

    return {
        "config": item.to_dict(),
        "team_validation": validation,
        "thread_id": thread_id,
        "team_builder": team_builder_state,
    }


@chat.post("/agent/{agent_id}/team/langchain-docs")
async def query_langchain_docs_with_mcp(
    agent_id: str,
    payload: TeamDocsQueryRequest,
    current_user: User = Depends(get_required_user),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    if agent_id != "DynamicAgent":
        raise HTTPException(status_code=422, detail="文档检索仅支持 DynamicAgent")

    try:
        return await team_orchestration_service.query_langchain_docs(
            payload.query,
            server_name=payload.server_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@chat.post("/agent/{agent_id}/team/benchmark")
async def benchmark_team_modes(
    agent_id: str,
    payload: TeamBenchmarkRequest,
    current_user: User = Depends(get_admin_user),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")
    if agent_id != "DynamicAgent":
        raise HTTPException(status_code=422, detail="团队基准仅支持 DynamicAgent")

    if payload.async_task:

        async def _run_task(context: TaskContext):
            await context.set_progress(5.0, "开始执行多模式基准")
            result = team_orchestration_service.benchmark_modes(payload.team, iterations=payload.iterations)
            await context.set_result(result)
            await context.set_progress(100.0, "基准测试完成")

        task = await tasker.enqueue(
            name=f"DynamicAgent 多模式基准 ({payload.iterations} 次)",
            task_type="dynamic_agent_benchmark",
            payload={"agent_id": agent_id, "iterations": payload.iterations},
            coroutine=_run_task,
        )
        return {"task_id": task.id, "status": "queued"}

    result = team_orchestration_service.benchmark_modes(payload.team, iterations=payload.iterations)
    return {"result": result}


@chat.post("/agent/{agent_id}")
async def chat_agent(
    agent_id: str,
    query: str = Body(...),
    config: dict = Body({}),
    meta: dict = Body({}),
    run_id: str | None = Body(None),
    image_content: str | None = Body(None),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """使用特定智能体进行对话（需要登录）"""
    logger.info(f"agent_id: {agent_id}, query: {query}, config: {config}, meta: {meta}")
    logger.info(f"image_content present: {image_content is not None}")
    if image_content:
        logger.info(f"image_content length: {len(image_content)}")
        logger.info(f"image_content preview: {image_content[:50]}...")

    # 确保 request_id 存在
    if "request_id" not in meta or not meta.get("request_id"):
        meta["request_id"] = str(uuid.uuid4())

    meta.update(
        {
            "query": query,
            "agent_id": agent_id,
            "server_model_name": config.get("model", agent_id),
            "thread_id": config.get("thread_id"),
            "user_id": current_user.id,
            "has_image": bool(image_content),
            "run_id": run_id or meta.get("run_id") or config.get("run_id"),
        }
    )
    return StreamingResponse(
        stream_agent_chat(
            agent_id=agent_id,
            query=query,
            config=config,
            meta=meta,
            image_content=image_content,
            current_user=current_user,
            db=db,
        ),
        media_type="application/json",
    )


# =============================================================================
# > === 模型管理分组 ===
# =============================================================================


@chat.get("/models")
async def get_chat_models(model_provider: str, current_user: User = Depends(get_admin_user)):
    """获取指定模型提供商的模型列表（需要登录）"""
    model = select_model(model_provider=model_provider)
    models = await model.get_models()
    return {"models": models}


@chat.post("/models/update")
async def update_chat_models(model_provider: str, model_names: list[str], current_user=Depends(get_admin_user)):
    """更新指定模型提供商的模型列表 (仅管理员)"""
    conf.model_names[model_provider].models = model_names
    conf._save_models_to_file(model_provider)
    return {"models": conf.model_names[model_provider].models}


@chat.post("/agent/{agent_id}/resume")
async def resume_agent_chat(
    agent_id: str,
    thread_id: str = Body(...),
    run_id: str | None = Body(None),
    approved: bool | None = Body(default=None),
    decision: str | None = Body(default=None),
    edited_text: str | None = Body(default=None),
    config: dict = Body({}),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """恢复被人工审批中断的对话（需要登录）"""
    if decision:
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"approve", "reject", "edit"}:
            raise HTTPException(status_code=422, detail="decision 仅支持 approve/reject/edit")
        if normalized_decision == "approve":
            resume_payload: bool | dict = True
        elif normalized_decision == "reject":
            resume_payload = False
        else:
            resume_payload = {"decision": "edit", "content": edited_text or ""}
    else:
        if approved is None:
            raise HTTPException(status_code=422, detail="approved 或 decision 至少提供一个")
        normalized_decision = "approve" if approved else "reject"
        resume_payload = approved

    logger.info(
        f"Resuming agent_id: {agent_id}, thread_id: {thread_id}, decision: {normalized_decision}, approved: {approved}"
    )

    meta = {
        "agent_id": agent_id,
        "thread_id": thread_id,
        "run_id": run_id or config.get("run_id"),
        "user_id": current_user.id,
        "approved": approved,
        "decision": normalized_decision,
    }
    if "request_id" not in meta or not meta.get("request_id"):
        meta["request_id"] = str(uuid.uuid4())
    return StreamingResponse(
        stream_agent_resume(
            agent_id=agent_id,
            thread_id=thread_id,
            resume_payload=resume_payload,
            meta=meta,
            config=config,
            current_user=current_user,
            db=db,
        ),
        media_type="application/json",
    )


@chat.post("/agent/{agent_id}/config")
async def save_agent_config(
    agent_id: str,
    config: dict = Body(...),
    reload_graph: bool = Query(True),
    current_user: User = Depends(get_required_user),
):
    """保存智能体配置到YAML文件（需要登录）"""
    try:
        # 获取Agent实例和配置类
        if not (agent := agent_manager.get_agent(agent_id)):
            raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

        # === 校验知识库权限 ===
        from src import knowledge_base

        if agent_id == "DynamicAgent":
            validation = team_orchestration_service.validate_team(config, strict=False)
            if validation["errors"]:
                raise HTTPException(status_code=422, detail=f"团队配置校验失败: {'; '.join(validation['errors'])}")

        requested_kbs = set(config.get("knowledges") or [])
        for sa in config.get("subagents") or []:
            if isinstance(sa, dict):
                requested_kbs.update(sa.get("knowledges") or [])

        if requested_kbs:
            # 获取用户有权访问的知识库名称
            try:
                user_info = {"role": current_user.role, "department_id": current_user.department_id}
                accessible_databases = await knowledge_base.get_databases_by_user(user_info)
                accessible_kb_names = {
                    db.get("name") for db in accessible_databases.get("databases", []) if db.get("name")
                }
            except Exception as db_error:
                logger.warning(f"获取知识库列表失败: {db_error}")
                # 如果获取失败，superadmin 可以访问所有，非 superadmin 无法访问任何
                if current_user.role != "superadmin":
                    raise HTTPException(status_code=500, detail="无法获取知识库列表")
                # 回退：获取所有数据库名称
                from src.repositories.knowledge_base_repository import KnowledgeBaseRepository

                kb_repo = KnowledgeBaseRepository()
                rows = await kb_repo.get_all()
                accessible_kb_names = {row.name for row in rows if row.name}

            # 检查配置中的知识库是否都可用
            invalid_kbs = [kb for kb in requested_kbs if kb not in accessible_kb_names]
            if invalid_kbs:
                raise HTTPException(status_code=403, detail=f"无权访问以下知识库: {', '.join(invalid_kbs)}")
        # === 校验结束 ===

        # 使用配置类的save_to_file方法保存配置
        result = agent.context_schema.save_to_file(config, agent.module_name)

        if result:
            if reload_graph:
                agent_manager.get_agent(agent_id, reload_graph=True)
            return {"success": True, "message": f"智能体 {agent.name} 配置已保存"}
        else:
            raise HTTPException(status_code=500, detail="保存智能体配置失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存智能体配置出错: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"保存智能体配置出错: {str(e)}")


@chat.get("/agent/{agent_id}/history")
async def get_agent_history(
    agent_id: str, thread_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """获取智能体历史消息（需要登录）- 包含用户反馈状态"""
    try:
        return await get_agent_history_view(
            agent_id=agent_id,
            thread_id=thread_id,
            current_user_id=str(current_user.id),
            db=db,
        )

    except Exception as e:
        logger.error(f"获取智能体历史消息出错: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取智能体历史消息出错: {str(e)}")


@chat.get("/agent/{agent_id}/state")
async def get_agent_state(
    agent_id: str,
    thread_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取智能体当前状态（需要登录）"""
    try:
        return await get_agent_state_view(
            agent_id=agent_id,
            thread_id=thread_id,
            current_user_id=str(current_user.id),
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取AgentState出错: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取AgentState出错: {str(e)}")


@chat.get("/agent/{agent_id}/config")
async def get_agent_config(agent_id: str, current_user: User = Depends(get_required_user)):
    """从YAML文件加载智能体配置（需要登录）"""
    try:
        # 检查智能体是否存在
        if not (agent := agent_manager.get_agent(agent_id)):
            raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

        config = await agent.get_config()
        logger.debug(f"config: {config}, ContextClass: {agent.context_schema=}")
        return {"success": True, "config": config}

    except Exception as e:
        logger.error(f"加载智能体配置出错: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"加载智能体配置出错: {str(e)}")


# ==================== 线程管理 API ====================


class ThreadCreate(BaseModel):
    title: str | None = None
    agent_id: str
    metadata: dict | None = None


class ThreadResponse(BaseModel):
    id: str
    user_id: str
    agent_id: str
    title: str | None = None
    last_message: str = ""
    runtime_status: str = "idle"
    current_run_id: str | None = None
    status_updated_at: str | None = None
    has_interrupt: bool = False
    is_loading: bool = False
    created_at: str
    updated_at: str


class AttachmentResponse(BaseModel):
    file_id: str
    file_name: str
    file_type: str | None = None
    file_size: int
    status: str
    uploaded_at: str
    truncated: bool | None = False


class AttachmentLimits(BaseModel):
    allowed_extensions: list[str]
    max_size_bytes: int


class AttachmentListResponse(BaseModel):
    attachments: list[AttachmentResponse]
    limits: AttachmentLimits


# =============================================================================
# > === 会话管理分组 ===
# =============================================================================


@chat.post("/thread", response_model=ThreadResponse)
async def create_thread(
    thread: ThreadCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_required_user)
):
    """创建新对话线程 (使用新存储系统)"""
    return await create_thread_view(
        agent_id=thread.agent_id,
        title=thread.title,
        metadata=thread.metadata,
        db=db,
        current_user_id=str(current_user.id),
    )


@chat.get("/threads", response_model=list[ThreadResponse])
async def list_threads(
    agent_id: str,
    runtime_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """获取用户的所有对话线程 (使用新存储系统)"""
    return await list_threads_view(
        agent_id=agent_id,
        db=db,
        current_user_id=str(current_user.id),
        runtime_status=runtime_status,
        limit=limit,
        offset=offset,
    )


@chat.delete("/thread/{thread_id}")
async def delete_thread(
    thread_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_required_user)
):
    """删除对话线程 (使用新存储系统)"""
    return await delete_thread_view(thread_id=thread_id, db=db, current_user_id=str(current_user.id))


class ThreadUpdate(BaseModel):
    title: str | None = None


@chat.put("/thread/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    thread_update: ThreadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """更新对话线程信息 (使用新存储系统)"""
    return await update_thread_view(
        thread_id=thread_id,
        title=thread_update.title,
        db=db,
        current_user_id=str(current_user.id),
    )


# ================================
# > === 附件管理分组 ===
# ================================


@chat.post("/thread/{thread_id}/attachments", response_model=AttachmentResponse)
async def upload_thread_attachment(
    thread_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """上传并解析附件为 Markdown，附加到指定对话线程。"""
    return await upload_thread_attachment_view(
        thread_id=thread_id,
        file=file,
        db=db,
        current_user_id=str(current_user.id),
    )


@chat.get("/thread/{thread_id}/attachments", response_model=AttachmentListResponse)
async def list_thread_attachments(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """列出当前对话线程的所有附件元信息。"""
    return await list_thread_attachments_view(
        thread_id=thread_id,
        db=db,
        current_user_id=str(current_user.id),
    )


@chat.delete("/thread/{thread_id}/attachments/{file_id}")
async def delete_thread_attachment(
    thread_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """移除指定附件。"""
    return await delete_thread_attachment_view(
        thread_id=thread_id,
        file_id=file_id,
        db=db,
        current_user_id=str(current_user.id),
    )


# =============================================================================
# > === 消息反馈分组 ===
# =============================================================================


class MessageFeedbackRequest(BaseModel):
    rating: str  # 'like' or 'dislike'
    reason: str | None = None  # Optional reason for dislike


class MessageFeedbackResponse(BaseModel):
    id: int
    message_id: int
    rating: str
    reason: str | None
    created_at: str


@chat.post("/message/{message_id}/feedback", response_model=MessageFeedbackResponse)
async def submit_message_feedback(
    message_id: int,
    feedback_data: MessageFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """提交消息反馈（需要登录）"""
    result = await submit_message_feedback_view(
        message_id=message_id,
        rating=feedback_data.rating,
        reason=feedback_data.reason,
        db=db,
        current_user_id=str(current_user.id),
    )
    return MessageFeedbackResponse(**result)


@chat.get("/message/{message_id}/feedback")
async def get_message_feedback(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """获取指定消息的用户反馈（需要登录）"""
    return await get_message_feedback_view(
        message_id=message_id,
        db=db,
        current_user_id=str(current_user.id),
    )


# =============================================================================
# > === 多模态图片支持分组 ===
# =============================================================================


@chat.post("/image/upload", response_model=ImageUploadResponse)
async def upload_image(file: UploadFile = File(...), current_user: User = Depends(get_required_user)):
    """
    上传并处理图片，返回base64编码的图片数据
    """
    try:
        # 验证文件类型
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="只支持图片文件上传")

        # 读取文件内容
        image_data = await file.read()

        # 检查文件大小（10MB限制，超过后会压缩到5MB）
        if len(image_data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片文件过大，请上传小于10MB的图片")

        # 处理图片
        result = process_uploaded_image(image_data, file.filename)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=f"图片处理失败: {result['error']}")

        logger.info(
            f"用户 {current_user.id} 成功上传图片: {file.filename}, "
            f"尺寸: {result['width']}x{result['height']}, "
            f"格式: {result['format']}, "
            f"大小: {result['size_bytes']} bytes"
        )

        return ImageUploadResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"图片上传处理失败: {str(e)}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"图片处理失败: {str(e)}")
