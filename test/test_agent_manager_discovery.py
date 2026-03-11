from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.agents import AgentManager
from src.agents.common.base import BaseAgent


class _LazyReporterAgent(BaseAgent):
    async def get_graph(self, **kwargs):
        raise NotImplementedError


_LazyReporterAgent.__module__ = "src.agents.reporter.graph"


def test_discover_agent_classes_supports_lazy_exports():
    module = types.ModuleType("src.agents.reporter")
    module.__all__ = ["SqlReporterAgent"]

    def _load_attr(name: str):
        if name == "SqlReporterAgent":
            return _LazyReporterAgent
        raise AttributeError(name)

    module.__getattr__ = _load_attr  # type: ignore[attr-defined]

    manager = AgentManager()
    discovered = manager._discover_agent_classes(module, "src.agents.reporter")

    assert discovered == [_LazyReporterAgent]
