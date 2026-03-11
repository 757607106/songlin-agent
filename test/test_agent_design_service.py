from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

import pytest

from src.agent_platform.types import ExecutionMode
from src.services.agent_design_service import AGENT_PLATFORM_CONFIG_ID, AgentBlueprint, AgentDesignService


def test_parse_intent_prefers_supervisor_for_database_report_tasks():
    service = AgentDesignService()

    intent = service.parse_intent("帮我创建一个数据库报表分析 agent，要求能校验 SQL 并输出图表")

    assert intent.execution_mode is ExecutionMode.SUPERVISOR
    assert intent.requires_tools is True
    assert intent.requires_mcp is True
    assert "数据库报表分析" in intent.inferred_name


@pytest.mark.asyncio
async def test_draft_blueprint_rules_attach_resources():
    service = AgentDesignService()

    result = await service.draft_blueprint(
        prompt="帮我创建一个支持 API 调用、搜索内容和图表展示的多智能体助手",
        available_resources={
            "tools": ["http_request", "calculator"],
            "knowledges": ["product-kb"],
            "mcps": ["browser-mcp"],
            "skills": ["research-skill"],
        },
        use_ai=False,
    )

    worker_map = {worker.key: worker for worker in result.blueprint.workers}

    assert result.source == "rules"
    assert result.intent.execution_mode is ExecutionMode.SUPERVISOR
    assert worker_map["intake_worker"].knowledge_ids == ["product-kb"]
    assert worker_map["execution_worker"].tools == ["http_request", "calculator"]
    assert worker_map["execution_worker"].mcps == ["browser-mcp"]


@pytest.mark.asyncio
async def test_draft_blueprint_prefers_legacy_template_for_knowledge_qa():
    service = AgentDesignService()

    result = await service.draft_blueprint(
        prompt="帮我创建一个知识库 FAQ 问答助手",
        available_resources={
            "knowledges": ["faq-kb"],
        },
        use_ai=False,
    )

    worker_map = {worker.key: worker for worker in result.blueprint.workers}

    assert result.source == "template"
    assert result.blueprint.execution_mode is ExecutionMode.SUPERVISOR
    assert "faq-kb" in worker_map["retrieval_worker"].knowledge_ids
    assert worker_map["answer_worker"].depends_on == ["retrieval_worker"]


def test_list_templates_exposes_legacy_blueprint_and_worker_templates():
    service = AgentDesignService()

    payload = service.list_templates()
    blueprint_ids = {item["template_id"] for item in payload["blueprint_templates"]}
    worker_ids = {item["template_id"] for item in payload["worker_templates"]}

    assert "legacy/knowledge_qa" in blueprint_ids
    assert "legacy/research_analyst" in blueprint_ids
    assert "legacy/document_organizer" in blueprint_ids
    assert "legacy/knowledge_retriever" in worker_ids
    assert "legacy/document_curator" in worker_ids


def test_list_examples_exposes_legacy_development_examples():
    service = AgentDesignService()

    payload = service.list_examples()
    example_ids = {item["example_id"] for item in payload}

    assert "legacy/knowledge_qa_minimal" in example_ids
    assert "legacy/research_analyst_deep" in example_ids
    assert "legacy/document_organizer_review" in example_ids
    first = next(item for item in payload if item["example_id"] == "legacy/knowledge_qa_minimal")
    assert first["spec"]["execution_mode"] == "supervisor"


@pytest.mark.asyncio
async def test_draft_template_merges_resources_into_template_workers():
    service = AgentDesignService()

    result = await service.draft_template(
        template_id="legacy/knowledge_qa",
        prompt="",
        available_resources={
            "knowledges": ["faq-kb"],
            "tools": ["search_docs"],
        },
    )

    worker_map = {worker.key: worker for worker in result.blueprint.workers}

    assert result.source == "template"
    assert result.blueprint.name == "知识问答助手"
    assert worker_map["retrieval_worker"].knowledge_ids == ["faq-kb"]
    assert result.intent.execution_mode is ExecutionMode.SUPERVISOR


@pytest.mark.asyncio
async def test_draft_blueprint_prefers_llm_when_available(monkeypatch: pytest.MonkeyPatch):
    service = AgentDesignService()
    expected = AgentBlueprint(
        name="LLM 设计团队",
        description="LLM 生成的设计稿",
        goal="完成复杂研究任务",
        task_scope="复杂研究任务",
        execution_mode=ExecutionMode.DEEP_AGENTS,
    )

    async def fake_llm(**kwargs):
        return expected

    monkeypatch.setattr(service, "_draft_with_llm", fake_llm)

    result = await service.draft_blueprint(prompt="帮我创建一个研究型 agent", use_ai=True)

    assert result.source == "llm"
    assert result.blueprint == expected


@pytest.mark.asyncio
async def test_deploy_blueprint_persists_platform_v2_payload():
    service = AgentDesignService()
    created_calls: list[dict] = []
    default_calls: list[dict] = []

    class FakeRepo:
        async def create(self, **kwargs):
            created_calls.append(kwargs)
            return SimpleNamespace(to_dict=lambda: {"id": 1, **kwargs}, is_default=kwargs["is_default"])

        async def set_default(self, *, config, updated_by: str | None = None):
            default_calls.append({"config": config, "updated_by": updated_by})
            return config

    blueprint = AgentBlueprint(
        name="Deploy Team",
        description="For deploy",
        goal="Ship a generated agent",
        task_scope="ship generated agent",
        execution_mode=ExecutionMode.SINGLE,
    )

    config = await service.deploy_blueprint(
        repo=FakeRepo(),
        department_id=7,
        user_id="u-1",
        blueprint=blueprint,
        set_default=True,
    )

    assert created_calls[0]["agent_id"] == AGENT_PLATFORM_CONFIG_ID
    assert created_calls[0]["config_json"]["version"] == "agent_platform_v2"
    assert created_calls[0]["config_json"]["blueprint"]["name"] == "Deploy Team"
    assert created_calls[0]["config_json"]["spec"]["name"] == "Deploy Team"
    assert default_calls and default_calls[0]["updated_by"] == "u-1"
    assert config.to_dict()["name"] == "Deploy Team"
