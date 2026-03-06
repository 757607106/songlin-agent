"""Basic smoke test for reporter supervisor graph."""

from __future__ import annotations

import pytest

from src.agents.reporter import SqlReporterAgent


@pytest.mark.asyncio
async def test_reporter_supervisor_graph_builds():
    agent = SqlReporterAgent()
    graph = await agent.get_graph()
    assert graph is not None
