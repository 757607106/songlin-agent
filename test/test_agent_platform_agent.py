from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agents.agent_platform.context import AgentPlatformContext
from src.agents.agent_platform.graph import AgentPlatformAgent
from src.agents.common.base import BaseAgent


@pytest.mark.asyncio
async def test_agent_platform_agent_is_no_longer_dynamic_agent(monkeypatch: pytest.MonkeyPatch):
    agent = AgentPlatformAgent()
    built_contexts: list[AgentPlatformContext] = []
    fake_graph = object()

    async def fake_get_checkpointer():
        return "cp"

    async def fake_get_store():
        return "store"

    async def fake_build_graph(context, *, checkpointer=None, store=None):
        built_contexts.append(context)
        assert checkpointer == "cp"
        assert store == "store"
        return fake_graph

    monkeypatch.setattr(agent, "_get_checkpointer", fake_get_checkpointer)
    monkeypatch.setattr(agent, "_get_store", fake_get_store)
    monkeypatch.setattr(agent._factory, "build_graph", fake_build_graph)

    graph = await agent.get_graph(
        model="openai/gpt-4.1-mini",
        system_prompt="Coordinate workers.",
        multi_agent_mode="supervisor",
        subagents=[{"name": "Planner", "description": "Plan", "system_prompt": "Plan first."}],
    )

    assert graph is fake_graph
    assert built_contexts
    assert isinstance(built_contexts[0], AgentPlatformContext)
    assert issubclass(AgentPlatformAgent, BaseAgent)
    assert AgentPlatformAgent.__bases__ == (BaseAgent,)
