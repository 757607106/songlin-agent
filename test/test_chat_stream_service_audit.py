from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.chat_stream_service import (  # noqa: E402
    _collect_supervisor_execution_entries,
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
