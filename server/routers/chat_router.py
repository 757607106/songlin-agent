import textwrap
import traceback
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.models_business import User
from server.routers.auth_router import get_admin_user
from server.utils.auth_middleware import get_db, get_required_user
from src import config as conf
from src.agents import agent_manager
from src.models import select_model
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
from src.services.history_query_service import get_agent_history_view
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


chat = APIRouter(prefix="/chat", tags=["chat"])


def _ensure_dynamic_or_admin(agent_id: str, current_user: User) -> None:
    if agent_id == "DynamicAgent":
        return
    if current_user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="需要管理员权限")


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
