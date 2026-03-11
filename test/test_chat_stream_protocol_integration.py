from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services import chat_stream_service as svc  # noqa: E402
from src.services.chat_stream_run_coordinator import PreparedAgentRun  # noqa: E402


class FakeToolMessage:
    content = "tool finished"

    def model_dump(self):
        return {
            "id": "tool-1",
            "type": "tool",
            "name": "web_search",
            "tool_call_id": "tool-call-1",
            "content": "tool finished",
        }


class FakeGraph:
    async def astream(self, _resume_command, **_kwargs):
        yield FakeToolMessage(), {"langgraph_node": "research_worker"}

    async def aget_state(self, _config):
        return SimpleNamespace(values={"messages": []})


class FakeAgent:
    async def get_graph(self, **_kwargs):
        return FakeGraph()


class FakeRunCoordinator:
    def __init__(self, _db):
        pass

    async def prepare_resume_run(self, **_kwargs):
        return PreparedAgentRun(
            agent=FakeAgent(),
            user_id="user-1",
            department_id=1,
            thread_id="thread-1",
            agent_config_id=None,
            agent_config={},
            team_execution_mode="disabled",
            runtime_audit={},
            input_context={},
            graph_kwargs={},
            excluded_ai_names=set(),
            context=None,
        )


@pytest.mark.asyncio
async def test_stream_agent_resume_emits_protocol_events_in_expected_order(monkeypatch: pytest.MonkeyPatch):
    @asynccontextmanager
    async def fake_reserve_thread_slot(_thread_id):
        yield

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(svc, "RunCoordinator", FakeRunCoordinator)
    monkeypatch.setattr(svc, "reserve_thread_slot", fake_reserve_thread_slot)
    monkeypatch.setattr(svc, "update_thread_runtime_status", noop)
    monkeypatch.setattr(svc, "save_messages_from_langgraph_state", noop)
    monkeypatch.setattr(svc, "_runtime_transition", noop)
    monkeypatch.setattr(svc, "_runtime_append_event", noop)

    chunks = []
    async for raw_chunk in svc.stream_agent_resume(
        agent_id="SqlReporterAgent",
        thread_id="thread-1",
        resume_payload={"kind": "approval", "decision": "approve"},
        meta={"request_id": "req-1", "decision": "approve"},
        config={},
        current_user=SimpleNamespace(id="user-1"),
        db=object(),
    ):
        chunks.append(json.loads(raw_chunk))

    assert [chunk["event"] for chunk in chunks] == [
        "interrupt.resumed",
        "run.started",
        "tool.completed",
        "run.completed",
    ]
    assert chunks[0]["audit_event"]["decision"] == "approve"
    assert chunks[2]["msg"]["name"] == "web_search"
