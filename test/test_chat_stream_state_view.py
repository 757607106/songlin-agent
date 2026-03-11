from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services import chat_stream_service as svc  # noqa: E402


@pytest.mark.asyncio
async def test_compute_agent_state_view_does_not_fallback_to_db_attachments(monkeypatch: pytest.MonkeyPatch):
    class FakeConversationRepository:
        def __init__(self, _db):
            pass

        async def get_conversation_by_thread_id(self, thread_id):
            assert thread_id == "thread-1"
            return SimpleNamespace(
                user_id="u1",
                status="active",
                extra_metadata={},
            )

        async def get_attachments_by_thread_id(self, _thread_id):
            raise AssertionError("agent_state view should not read attachment fallback from DB")

    class FakeGraph:
        async def aget_state(self, config):
            assert config == {"configurable": {"user_id": "u1", "thread_id": "thread-1"}}
            return SimpleNamespace(values={"files": {}, "route_log": ["sql_generation_worker"]})

    class FakeAgent:
        async def get_graph(self, **kwargs):
            assert kwargs == {"user_id": "u1"}
            return FakeGraph()

    monkeypatch.setattr(svc, "ConversationRepository", FakeConversationRepository)
    monkeypatch.setattr(svc.agent_manager, "get_agent", lambda _agent_id: FakeAgent())

    result = await svc._compute_agent_state_view(
        agent_id="SqlReporterAgent",
        thread_id="thread-1",
        current_user_id="u1",
        db=object(),
    )

    assert result["agent_state"]["files"] == {}
    assert result["agent_state"]["route_log"] == ["sql_generation_worker"]
