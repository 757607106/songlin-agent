from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from server.routers.agent_design_router import agent_design
from server.utils.auth_middleware import get_db, get_required_user
from src.agent_platform.blueprint.models import AgentBlueprint
from src.agent_platform.types import ExecutionMode
from src.services import agent_design_service as design_service_module
from src.services.agent_design_service import DraftBlueprintResult, AgentIntent


@asynccontextmanager
async def _test_app_client():
    app = FastAPI()
    app.include_router(agent_design, prefix="/api")
    app.dependency_overrides[get_required_user] = lambda: SimpleNamespace(id=1, department_id=10)

    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_agent_design_router_draft(monkeypatch: pytest.MonkeyPatch):
    async def fake_draft_blueprint(**kwargs):
        return DraftBlueprintResult(
            source="rules",
            intent=AgentIntent(
                original_request=kwargs["prompt"],
                inferred_name="测试团队",
                summary="测试团队",
                execution_mode=ExecutionMode.SUPERVISOR,
                complexity="medium",
            ),
            blueprint=AgentBlueprint(
                name="测试团队",
                description="desc",
                goal="测试团队",
                task_scope="测试团队",
                execution_mode=ExecutionMode.SUPERVISOR,
            ),
        )

    monkeypatch.setattr(design_service_module.agent_design_service, "draft_blueprint", fake_draft_blueprint)

    async with _test_app_client() as client:
        response = await client.post(
            "/api/agent-design/draft",
            json={"prompt": "帮我创建一个测试团队", "use_ai": False},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "rules"
    assert payload["intent"]["execution_mode"] == "supervisor"


@pytest.mark.asyncio
async def test_agent_design_router_compile_rejects_invalid_blueprint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        design_service_module.agent_design_service,
        "validate_blueprint",
        lambda _blueprint: {"valid": False, "errors": ["invalid blueprint"], "warnings": []},
    )

    async with _test_app_client() as client:
        response = await client.post("/api/agent-design/compile", json={"blueprint": {"name": "bad"}})

    assert response.status_code == 422
    assert response.json()["detail"] == ["invalid blueprint"]


@pytest.mark.asyncio
async def test_agent_design_router_deploy_returns_config(monkeypatch: pytest.MonkeyPatch):
    blueprint = {
        "name": "Deploy Team",
        "description": "desc",
        "goal": "deploy",
        "task_scope": "deploy",
        "execution_mode": "single",
    }
    monkeypatch.setattr(
        design_service_module.agent_design_service,
        "validate_blueprint",
        lambda _blueprint: {"valid": True, "errors": [], "warnings": []},
    )

    async def fake_deploy_blueprint(**kwargs):
        return SimpleNamespace(to_dict=lambda: {"id": 1, "name": kwargs["name"] or kwargs["blueprint"]["name"]})

    monkeypatch.setattr(design_service_module.agent_design_service, "deploy_blueprint", fake_deploy_blueprint)

    async with _test_app_client() as client:
        response = await client.post(
            "/api/agent-design/deploy",
            json={"blueprint": blueprint, "name": "Deploy Team"},
        )

    assert response.status_code == 200
    assert response.json()["config"]["name"] == "Deploy Team"


@pytest.mark.asyncio
async def test_agent_design_router_templates(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        design_service_module.agent_design_service,
        "list_templates",
        lambda: {
            "blueprint_templates": [{"template_id": "legacy/knowledge_qa"}],
            "worker_templates": [{"template_id": "legacy/knowledge_retriever"}],
        },
    )

    async with _test_app_client() as client:
        response = await client.get("/api/agent-design/templates")

    assert response.status_code == 200
    payload = response.json()
    assert payload["blueprint_templates"][0]["template_id"] == "legacy/knowledge_qa"
    assert payload["worker_templates"][0]["template_id"] == "legacy/knowledge_retriever"


@pytest.mark.asyncio
async def test_agent_design_router_examples(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        design_service_module.agent_design_service,
        "list_examples",
        lambda: [{"example_id": "legacy/knowledge_qa_minimal"}],
    )

    async with _test_app_client() as client:
        response = await client.get("/api/agent-design/examples")

    assert response.status_code == 200
    payload = response.json()
    assert payload["examples"][0]["example_id"] == "legacy/knowledge_qa_minimal"


@pytest.mark.asyncio
async def test_agent_design_router_draft_template(monkeypatch: pytest.MonkeyPatch):
    async def fake_draft_template(**kwargs):
        return DraftBlueprintResult(
            source="template",
            intent=AgentIntent(
                original_request=kwargs["prompt"] or "知识问答",
                inferred_name="知识问答助手",
                summary="知识问答",
                execution_mode=ExecutionMode.SUPERVISOR,
                complexity="medium",
            ),
            blueprint=AgentBlueprint(
                name="知识问答助手",
                description="desc",
                goal="知识问答",
                task_scope="知识问答",
                execution_mode=ExecutionMode.SUPERVISOR,
            ),
        )

    monkeypatch.setattr(design_service_module.agent_design_service, "draft_template", fake_draft_template)

    async with _test_app_client() as client:
        response = await client.post(
            "/api/agent-design/templates/legacy/knowledge_qa/draft",
            json={"prompt": "", "available_resources": {"knowledges": ["faq-kb"]}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "template"
    assert payload["blueprint"]["name"] == "知识问答助手"
