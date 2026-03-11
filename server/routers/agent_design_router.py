from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from src.repositories.agent_config_repository import AgentConfigRepository
from src.services.agent_design_service import agent_design_service
from src.storage.postgres.models_business import User

agent_design = APIRouter(prefix="/agent-design", tags=["agent-design"])


class DraftBlueprintRequest(BaseModel):
    prompt: str
    available_resources: dict[str, list[str]] = Field(default_factory=dict)
    model_name: str | None = None
    use_ai: bool = True


class ValidateBlueprintRequest(BaseModel):
    blueprint: dict[str, Any]


class DraftTemplateRequest(BaseModel):
    prompt: str = ""
    available_resources: dict[str, list[str]] = Field(default_factory=dict)


class CompileBlueprintRequest(BaseModel):
    blueprint: dict[str, Any]


class DeployBlueprintRequest(BaseModel):
    blueprint: dict[str, Any]
    spec: dict[str, Any] | None = None
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    examples: list[str] | None = None
    set_default: bool = False


@agent_design.post("/draft")
async def draft_blueprint(body: DraftBlueprintRequest, current_user: User = Depends(get_required_user)):
    result = await agent_design_service.draft_blueprint(
        prompt=body.prompt,
        available_resources=body.available_resources,
        model_name=body.model_name,
        use_ai=body.use_ai,
    )
    return result.model_dump(mode="json")


@agent_design.get("/templates")
async def list_templates(current_user: User = Depends(get_required_user)):
    return agent_design_service.list_templates()


@agent_design.get("/examples")
async def list_examples(current_user: User = Depends(get_required_user)):
    return {"examples": agent_design_service.list_examples()}


@agent_design.post("/templates/{template_id:path}/draft")
async def draft_template(
    template_id: str,
    body: DraftTemplateRequest,
    current_user: User = Depends(get_required_user),
):
    result = await agent_design_service.draft_template(
        template_id=template_id,
        prompt=body.prompt,
        available_resources=body.available_resources,
    )
    return result.model_dump(mode="json")


@agent_design.post("/validate")
async def validate_blueprint(body: ValidateBlueprintRequest, current_user: User = Depends(get_required_user)):
    return agent_design_service.validate_blueprint(body.blueprint)


@agent_design.post("/compile")
async def compile_blueprint(body: CompileBlueprintRequest, current_user: User = Depends(get_required_user)):
    validation = agent_design_service.validate_blueprint(body.blueprint)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation["errors"])
    spec = agent_design_service.compile_blueprint(body.blueprint)
    return {
        "validation": validation,
        "spec": spec.model_dump(mode="json"),
    }


@agent_design.post("/deploy")
async def deploy_blueprint(
    body: DeployBlueprintRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.department_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定部门")

    validation = agent_design_service.validate_blueprint(body.blueprint)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation["errors"])

    repo = AgentConfigRepository(db)
    config = await agent_design_service.deploy_blueprint(
        repo=repo,
        department_id=current_user.department_id,
        user_id=str(current_user.id),
        blueprint=body.blueprint,
        spec=body.spec,
        name=body.name,
        description=body.description,
        icon=body.icon,
        pics=body.pics,
        examples=body.examples,
        set_default=body.set_default,
    )
    return {"config": config.to_dict()}
