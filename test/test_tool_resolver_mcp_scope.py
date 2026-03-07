from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agents.common.subagents.registry import ToolResolver
from src.agents.common.subagents.registry import SubAgentRegistry


def test_tool_resolver_respects_selected_mcp_servers(monkeypatch):
    requested_servers: list[str] = []

    class DummyTool:
        def __init__(self, name: str):
            self.name = name

    async def _fake_get_enabled_mcp_tools(server_name: str):
        requested_servers.append(server_name)
        return [DummyTool(f"{server_name}_tool")]

    monkeypatch.setattr(
        "src.agents.common.subagents.registry.get_enabled_mcp_tools",
        _fake_get_enabled_mcp_tools,
    )
    monkeypatch.setattr("src.agents.common.subagents.registry.get_buildin_tools", lambda: [])
    monkeypatch.setattr("src.agents.common.subagents.registry.get_kb_based_tools", lambda db_names=None: [])
    monkeypatch.setattr("src.agents.common.subagents.registry.get_tavily_search", lambda: None)

    tools = asyncio.run(ToolResolver.resolve(mcps=["docs", "chart"]))

    assert requested_servers == ["docs", "chart"]
    assert {tool.name for tool in tools} == {"docs_tool", "chart_tool"}


def test_tool_resolver_includes_builtin_kb_and_tavily(monkeypatch):
    class DummyTool:
        def __init__(self, name: str):
            self.name = name

    async def _fake_kb_tools(db_names=None):
        assert db_names == ["kb_a"]
        return [DummyTool("kb_tool")]

    async def _fake_get_enabled_mcp_tools(server_name: str):
        return [DummyTool(f"{server_name}_tool")]

    monkeypatch.setattr(
        "src.agents.common.subagents.registry.get_buildin_tools",
        lambda: [DummyTool("calculator")],
    )
    monkeypatch.setattr("src.agents.common.subagents.registry.get_kb_based_tools", _fake_kb_tools)
    monkeypatch.setattr(
        "src.agents.common.subagents.registry.get_tavily_search",
        lambda: DummyTool("tavily"),
    )
    monkeypatch.setattr(
        "src.agents.common.subagents.registry.get_enabled_mcp_tools",
        _fake_get_enabled_mcp_tools,
    )

    tools = asyncio.run(
        ToolResolver.resolve(
            tool_ids=["calculator", "unknown_tool"],
            knowledges=["kb_a"],
            mcps=["docs"],
        )
    )

    assert {tool.name for tool in tools} == {"calculator", "kb_tool", "tavily", "docs_tool"}


def test_tool_resolver_handles_kb_and_mcp_failures(monkeypatch):
    class DummyTool:
        def __init__(self, name: str):
            self.name = name

    async def _kb_raises(db_names=None):
        raise RuntimeError("kb failed")

    async def _mcp_raises(server_name: str):
        raise RuntimeError("mcp failed")

    monkeypatch.setattr("src.agents.common.subagents.registry.get_buildin_tools", lambda: [])
    monkeypatch.setattr("src.agents.common.subagents.registry.get_kb_based_tools", _kb_raises)
    monkeypatch.setattr("src.agents.common.subagents.registry.get_tavily_search", lambda: DummyTool("tavily"))
    monkeypatch.setattr("src.agents.common.subagents.registry.get_enabled_mcp_tools", _mcp_raises)

    tools = asyncio.run(ToolResolver.resolve(knowledges=["kb_a"], mcps=["docs"]))
    assert [tool.name for tool in tools] == ["tavily"]


def test_subagent_registry_register_get_and_list():
    registry = SubAgentRegistry()
    registry._registry.clear()

    class DummyAgent:
        async def get_graph(self, **kwargs):
            return {"ok": True, "kwargs": kwargs}

    registry.register("dummy", DummyAgent, description="dummy desc")
    listed = registry.list_available()

    assert listed == [{"name": "dummy", "description": "dummy desc"}]

    graph = asyncio.run(registry.get_compiled("dummy", x=1))
    assert graph["ok"] is True
    assert graph["kwargs"]["x"] == 1


def test_subagent_registry_get_compiled_missing():
    registry = SubAgentRegistry()
    registry._registry.clear()
    with pytest.raises(KeyError):
        asyncio.run(registry.get_compiled("missing"))
