from __future__ import annotations

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.chat_stream_event_adapter import make_stream_chunk_factory, resolve_stream_event  # noqa: E402
from src.services.chat_stream_event_adapter import (  # noqa: E402
    agent_state_chunk,
    execution_audit_chunk,
    human_approval_required_chunk,
    interrupted_chunk,
    loading_chunk,
    subagent_step_chunk,
)
from src.services.chat_stream_service import (  # noqa: E402
    _collect_worker_route_entries,
    _collect_supervisor_execution_entries,
    extract_agent_state,
    _map_supervisor_entry_to_runtime_event,
    _supervisor_entry_fingerprint,
)


def test_collect_supervisor_execution_entries_from_state_update():
    update_event = {
        "type": "state_update",
        "data": {
            "supervisor": {
                "execution_log": [
                    {"ts": "2026-03-08T00:00:00+00:00", "type": "route", "target": "planner"},
                    {"ts": "2026-03-08T00:00:01+00:00", "type": "finish", "reason": "done"},
                ]
            },
            "planner": {"messages": []},
        },
    }

    entries = _collect_supervisor_execution_entries(update_event)

    assert len(entries) == 2
    assert entries[0]["type"] == "route"
    assert entries[1]["type"] == "finish"


def test_supervisor_entry_mapping_and_fingerprint_are_stable():
    route_entry = {"type": "route", "target": "researcher", "retry": 0}
    unknown_entry = {"type": "unknown_custom_event", "x": 1}

    assert _map_supervisor_entry_to_runtime_event("route") == "supervisor.route"
    assert _map_supervisor_entry_to_runtime_event("unknown_custom_event") == "supervisor.event"

    fp1 = _supervisor_entry_fingerprint(route_entry)
    fp2 = _supervisor_entry_fingerprint(dict(route_entry))
    assert fp1 == fp2
    assert _supervisor_entry_fingerprint(unknown_entry)


def test_extract_agent_state_includes_reporter_worker_fields():
    state = extract_agent_state(
        {
            "route_log": ["schema_worker", "sql_generation_worker"],
            "active_worker": "sql_generation_worker",
            "stage_outputs": {"schema_worker": {"status": "SCHEMA_READY"}},
        }
    )

    assert state["route_log"] == ["schema_worker", "sql_generation_worker"]
    assert state["active_worker"] == "sql_generation_worker"
    assert state["stage_outputs"]["schema_worker"]["status"] == "SCHEMA_READY"


def test_collect_worker_route_entries_uses_incremental_index():
    agent_state = {"route_log": ["schema_worker", "clarification_worker", "sql_generation_worker"]}

    entries, emitted_count = _collect_worker_route_entries(agent_state, emitted_count=1)

    assert emitted_count == 3
    assert entries == [
        {"type": "worker_route", "worker": "clarification_worker", "index": 1},
        {"type": "worker_route", "worker": "sql_generation_worker", "index": 2},
    ]


def test_resolve_stream_event_maps_statuses_and_audit_types():
    assert resolve_stream_event({"status": "init"}) == "run.started"
    assert resolve_stream_event({"status": "execution_audit", "audit_event_type": "worker.route"}) == "worker.route"
    assert resolve_stream_event({"status": "human_approval_required"}) == "interrupt.requested"
    assert resolve_stream_event({"status": "loading", "msg": {"type": "tool"}}) == "tool.completed"
    assert resolve_stream_event({"status": "loading", "msg": {"type": "ai"}}) == "message.chunk"


def test_make_stream_chunk_factory_adds_normalized_event_field():
    make_chunk = make_stream_chunk_factory({"request_id": "req-1"})

    audit_chunk = json.loads(
        make_chunk(status="execution_audit", audit_event_type="supervisor.route", audit_event={"type": "route"})
    )
    loading_chunk = json.loads(make_chunk(status="loading", msg={"type": "tool", "id": "tool-1"}))

    assert audit_chunk["request_id"] == "req-1"
    assert audit_chunk["event"] == "supervisor.route"
    assert loading_chunk["event"] == "tool.completed"


def test_standard_stream_chunk_builders_emit_expected_event_and_status():
    agent_state_payload = json.loads(
        agent_state_chunk(
            meta={"request_id": "req-2"},
            agent_state={"active_worker": "w1"},
        )
    )
    audit_payload = json.loads(
        execution_audit_chunk(
            meta={"request_id": "req-2"},
            audit_event_type="worker.route",
            audit_event={"type": "worker_route", "worker": "w1"},
        )
    )
    step_payload = json.loads(
        subagent_step_chunk(
            meta={"request_id": "req-2"},
            subagent_name="researcher",
            step="tools",
            namespace=["root"],
        )
    )
    interrupt_payload = json.loads(
        human_approval_required_chunk(
            meta={"request_id": "req-2"},
            message="approve?",
            thread_id="thread-1",
            interrupt_info={"kind": "approval", "question": "approve?"},
        )
    )
    loading_payload = json.loads(
        loading_chunk(
            meta={"request_id": "req-2"},
            msg={"type": "ai", "id": "m1"},
            metadata={"source": "graph"},
        )
    )
    interrupted_payload = json.loads(interrupted_chunk(meta={"request_id": "req-2"}, message="stopped"))

    assert agent_state_payload["status"] == "agent_state"
    assert agent_state_payload["event"] == "state.snapshot"
    assert audit_payload["status"] == "execution_audit"
    assert audit_payload["event"] == "worker.route"
    assert step_payload["status"] == "subagent_step"
    assert step_payload["event"] == "worker.progress"
    assert interrupt_payload["status"] == "human_approval_required"
    assert interrupt_payload["event"] == "interrupt.requested"
    assert interrupt_payload["interrupt_info"]["kind"] == "approval"
    assert loading_payload["status"] == "loading"
    assert loading_payload["event"] == "message.chunk"
    assert interrupted_payload["status"] == "interrupted"
    assert interrupted_payload["event"] == "run.interrupted"
