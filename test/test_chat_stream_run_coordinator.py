from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agent_platform.constants import AGENT_PLATFORM_AGENT_ID
from src.services.chat_stream_run_coordinator import (  # noqa: E402
    MissingDepartmentError,
    RunCoordinator,
    ThreadBusyError,
    apply_accessible_knowledge_scope,
    reserve_thread_slot,
)


class _FakeRepo:
    def __init__(self, config_item):
        self.config_item = config_item

    async def get_by_id(self, config_id: int):
        return self.config_item if self.config_item and self.config_item.id == config_id else None

    async def get_or_create_default(self, **kwargs):
        return self.config_item


@pytest.mark.asyncio
async def test_prepare_chat_run_uses_default_config_and_generates_thread_id(monkeypatch):
    config_item = SimpleNamespace(
        id=11,
        department_id=10,
        agent_id="reporter",
        config_json={
            "context": {
                "multi_agent_mode": "supervisor",
                "subagents": [{"name": "SQL Planner"}, {"name": "Chart Worker"}],
            }
        },
    )
    fake_agent = SimpleNamespace(_build_runtime_context=lambda input_context: SimpleNamespace(unused=True))

    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.AgentConfigRepository",
        lambda db: _FakeRepo(config_item),
    )
    monkeypatch.setattr("src.services.chat_stream_run_coordinator.agent_manager.get_agent", lambda agent_id: fake_agent)

    prepared = await RunCoordinator(db=object()).prepare_chat_run(
        agent_id="reporter",
        config={},
        current_user=SimpleNamespace(id=7, department_id=10),
    )

    assert prepared.agent is fake_agent
    assert prepared.thread_id
    assert prepared.user_id == "7"
    assert prepared.agent_config_id == 11
    assert prepared.team_execution_mode == "supervisor"
    assert prepared.graph_kwargs == {"user_id": "7", "department_id": 10}
    assert prepared.excluded_ai_names == {"SQL Planner", "Chart Worker"}


@pytest.mark.asyncio
async def test_prepare_resume_run_builds_platform_graph_kwargs(monkeypatch):
    config_item = SimpleNamespace(
        id=22,
        department_id=10,
        agent_id=AGENT_PLATFORM_AGENT_ID,
        config_json={"spec": {"execution_mode": "supervisor"}},
    )
    runtime_context = SimpleNamespace(
        model="openai/gpt-4.1-mini",
        system_prompt="system",
        multi_agent_mode="supervisor",
        team_goal="goal",
        task_scope="scope",
        communication_protocol="protocol",
        max_parallel_tasks=2,
        allow_cross_agent_comm=False,
        subagents=[{"name": "Worker A"}],
        supervisor_system_prompt="supervisor",
        tools=["sql_query"],
        knowledges=["sales_schema"],
        mcps=["chart-mcp"],
    )
    fake_agent = SimpleNamespace(_build_runtime_context=lambda input_context: runtime_context)

    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.AgentConfigRepository",
        lambda db: _FakeRepo(config_item),
    )
    monkeypatch.setattr("src.services.chat_stream_run_coordinator.agent_manager.get_agent", lambda agent_id: fake_agent)
    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.build_dynamic_context_from_platform_config",
        lambda raw: {"subagents": [{"name": "Worker A"}], "multi_agent_mode": "supervisor"},
    )

    prepared = await RunCoordinator(db=object()).prepare_resume_run(
        agent_id=AGENT_PLATFORM_AGENT_ID,
        thread_id="thread-123",
        config={"agent_config_id": 22},
        current_user=SimpleNamespace(id=8, department_id=10),
    )

    assert prepared.thread_id == "thread-123"
    assert prepared.context is runtime_context
    assert prepared.graph_kwargs["multi_agent_mode"] == "supervisor"
    assert prepared.graph_kwargs["tools"] == ["sql_query"]
    assert prepared.excluded_ai_names == {"Worker A"}


@pytest.mark.asyncio
async def test_apply_accessible_knowledge_scope_filters_main_and_subagent_knowledges(monkeypatch):
    async def fake_get_databases_by_user(user_info):
        assert user_info == {"role": "user", "department_id": 10}
        return {"databases": [{"name": "allowed_kb"}, {"name": "shared_kb"}]}

    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.knowledge_base",
        SimpleNamespace(get_databases_by_user=fake_get_databases_by_user),
    )

    agent_config = {
        "knowledges": ["allowed_kb", "blocked_kb"],
        "subagents": [
            {"name": "Retriever", "knowledges": ["shared_kb", "blocked_kb"]},
            {"name": "Chart", "knowledges": ["blocked_kb_only"]},
        ],
    }

    await apply_accessible_knowledge_scope(agent_config, user_id="7", department_id=10)

    assert agent_config["knowledges"] == ["allowed_kb"]
    assert agent_config["subagents"][0]["knowledges"] == ["shared_kb"]
    assert agent_config["subagents"][1]["knowledges"] == []


@pytest.mark.asyncio
async def test_prepare_resume_run_filters_platform_knowledge_scope_before_building_graph_kwargs(monkeypatch):
    config_item = SimpleNamespace(
        id=23,
        department_id=10,
        agent_id=AGENT_PLATFORM_AGENT_ID,
        config_json={"spec": {"execution_mode": "supervisor"}},
    )
    def build_runtime_context(input_context):
        agent_config = input_context["agent_config"]
        return SimpleNamespace(
            model="openai/gpt-4.1-mini",
            system_prompt="system",
            multi_agent_mode="supervisor",
            team_goal="goal",
            task_scope="scope",
            communication_protocol="protocol",
            max_parallel_tasks=2,
            allow_cross_agent_comm=False,
            subagents=agent_config["subagents"],
            supervisor_system_prompt="supervisor",
            tools=["sql_query"],
            knowledges=agent_config["knowledges"],
            mcps=["chart-mcp"],
        )

    fake_agent = SimpleNamespace(_build_runtime_context=build_runtime_context)

    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.AgentConfigRepository",
        lambda db: _FakeRepo(config_item),
    )
    monkeypatch.setattr("src.services.chat_stream_run_coordinator.agent_manager.get_agent", lambda agent_id: fake_agent)
    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.build_dynamic_context_from_platform_config",
        lambda raw: {
            "subagents": [{"name": "Worker A", "knowledges": ["allowed_kb", "blocked_kb"]}],
            "knowledges": ["allowed_kb", "blocked_kb"],
            "multi_agent_mode": "supervisor",
        },
    )

    async def fake_get_databases_by_user(user_info):
        return {"databases": [{"name": "allowed_kb"}]}

    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.knowledge_base",
        SimpleNamespace(get_databases_by_user=fake_get_databases_by_user),
    )

    prepared = await RunCoordinator(db=object()).prepare_resume_run(
        agent_id=AGENT_PLATFORM_AGENT_ID,
        thread_id="thread-234",
        config={"agent_config_id": 23},
        current_user=SimpleNamespace(id=8, department_id=10),
    )

    assert prepared.agent_config["knowledges"] == ["allowed_kb"]
    assert prepared.agent_config["subagents"][0]["knowledges"] == ["allowed_kb"]
    assert prepared.graph_kwargs["knowledges"] == ["allowed_kb"]
    assert prepared.graph_kwargs["subagents"][0]["knowledges"] == ["allowed_kb"]


@pytest.mark.asyncio
async def test_prepare_run_requires_department(monkeypatch):
    monkeypatch.setattr(
        "src.services.chat_stream_run_coordinator.agent_manager.get_agent",
        lambda agent_id: SimpleNamespace(_build_runtime_context=lambda input_context: None),
    )

    with pytest.raises(MissingDepartmentError):
        await RunCoordinator(db=object()).prepare_chat_run(
            agent_id="reporter",
            config={},
            current_user=SimpleNamespace(id=1, department_id=None),
        )


@pytest.mark.asyncio
async def test_reserve_thread_slot_blocks_parallel_access():
    async with reserve_thread_slot("thread-lock-test"):
        with pytest.raises(ThreadBusyError):
            async with reserve_thread_slot("thread-lock-test"):
                pass
