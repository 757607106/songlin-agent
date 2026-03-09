from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest

# Add project root to path for imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from src.services.runtime_service import runtime_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_runtime_create_requires_login(test_client):
    response = await test_client.post(
        "/api/runtime/runs",
        json={
            "agent_id": "DynamicAgent",
            "thread_id": "thread-auth-check",
            "mode": "hybrid",
            "input": {"query": "hello"},
        },
        headers={"X-Idempotency-Key": "idem-auth-check"},
    )
    assert response.status_code == 401


async def test_runtime_run_lifecycle_minimal(test_client, admin_headers):
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    idem_key = f"idem-{uuid.uuid4().hex}"
    create_response = await test_client.post(
        "/api/runtime/runs",
        json={
            "agent_id": "DynamicAgent",
            "thread_id": thread_id,
            "mode": "hybrid",
            "input": {"query": "build runtime"},
            "runtime_options": {"max_attempts": 2},
        },
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    assert create_response.status_code == 200, create_response.text
    payload = create_response.json()
    run_id = payload.get("run_id")
    assert run_id
    assert payload.get("status") == "queued"

    detail_response = await test_client.get(f"/api/runtime/runs/{run_id}", headers=admin_headers)
    assert detail_response.status_code == 200, detail_response.text
    detail_payload = detail_response.json()
    assert detail_payload.get("run_id") == run_id

    events_response = await test_client.get(f"/api/runtime/runs/{run_id}/events", headers=admin_headers)
    assert events_response.status_code == 200, events_response.text
    events_payload = events_response.json()
    items = events_payload.get("items") or []
    assert isinstance(items, list)
    assert any(item.get("event_type") == "run.created" for item in items)
    assert events_payload.get("next_cursor", 0) >= 0

    cancel_response = await test_client.post(f"/api/runtime/runs/{run_id}/cancel", headers=admin_headers)
    assert cancel_response.status_code == 200, cancel_response.text
    assert cancel_response.json().get("status") == "cancelled"

    post_cancel_events = await test_client.get(f"/api/runtime/runs/{run_id}/events", headers=admin_headers)
    assert post_cancel_events.status_code == 200, post_cancel_events.text
    post_items = post_cancel_events.json().get("items") or []
    assert any(item.get("event_type") == "run.cancelled" for item in post_items)


async def test_runtime_idempotency_replay(test_client, admin_headers):
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    idem_key = f"idem-{uuid.uuid4().hex}"
    body = {
        "agent_id": "DynamicAgent",
        "thread_id": thread_id,
        "mode": "hybrid",
        "input": {"query": "same request"},
        "runtime_options": {"max_attempts": 1},
    }
    first = await test_client.post(
        "/api/runtime/runs",
        json=body,
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    second = await test_client.post(
        "/api/runtime/runs",
        json=body,
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload.get("run_id") == second_payload.get("run_id")
    assert second_payload.get("is_replay") is True


async def test_runtime_events_support_server_filters(test_client, admin_headers):
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    idem_key = f"idem-{uuid.uuid4().hex}"
    create_response = await test_client.post(
        "/api/runtime/runs",
        json={
            "agent_id": "DynamicAgent",
            "thread_id": thread_id,
            "mode": "hybrid",
            "input": {"query": "filter events"},
        },
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    assert create_response.status_code == 200, create_response.text
    run_id = create_response.json().get("run_id")
    assert run_id

    await runtime_service.append_event(
        run_id=run_id,
        event_type="tool.invoke",
        actor_type="tool",
        actor_name="search-tool",
        payload={"tool": "search"},
    )
    await runtime_service.append_event(
        run_id=run_id,
        event_type="supervisor.route",
        actor_type="supervisor",
        actor_name="planner",
        payload={"target": "researcher"},
    )

    by_event_type = await test_client.get(
        f"/api/runtime/runs/{run_id}/events?event_type=tool.invoke",
        headers=admin_headers,
    )
    assert by_event_type.status_code == 200, by_event_type.text
    by_event_items = by_event_type.json().get("items") or []
    assert len(by_event_items) == 1
    assert by_event_items[0].get("event_type") == "tool.invoke"

    by_actor_type = await test_client.get(
        f"/api/runtime/runs/{run_id}/events?actor_type=supervisor",
        headers=admin_headers,
    )
    assert by_actor_type.status_code == 200, by_actor_type.text
    by_actor_items = by_actor_type.json().get("items") or []
    assert len(by_actor_items) == 1
    assert by_actor_items[0].get("actor_type") == "supervisor"

    by_actor_name = await test_client.get(
        f"/api/runtime/runs/{run_id}/events?actor_name=search",
        headers=admin_headers,
    )
    assert by_actor_name.status_code == 200, by_actor_name.text
    by_name_items = by_actor_name.json().get("items") or []
    assert len(by_name_items) == 1
    assert by_name_items[0].get("actor_name") == "search-tool"

    cursor = by_actor_name.json().get("next_cursor", 0)
    with_cursor = await test_client.get(
        f"/api/runtime/runs/{run_id}/events?actor_name=search&cursor={cursor}",
        headers=admin_headers,
    )
    assert with_cursor.status_code == 200, with_cursor.text
    assert with_cursor.json().get("items") == []
    assert with_cursor.json().get("next_cursor") == cursor


async def test_runtime_events_seq_monotonic_under_parallel_appends(test_client, admin_headers):
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    idem_key = f"idem-{uuid.uuid4().hex}"
    create_response = await test_client.post(
        "/api/runtime/runs",
        json={
            "agent_id": "DynamicAgent",
            "thread_id": thread_id,
            "mode": "hybrid",
            "input": {"query": "parallel events"},
        },
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    assert create_response.status_code == 200, create_response.text
    run_id = create_response.json().get("run_id")
    assert run_id

    async def _append(idx: int):
        await runtime_service.append_event(
            run_id=run_id,
            event_type="tool.invoke",
            actor_type="tool",
            actor_name=f"tool-{idx}",
            payload={"idx": idx},
        )

    await asyncio.gather(*[_append(i) for i in range(20)])

    events_response = await test_client.get(f"/api/runtime/runs/{run_id}/events?limit=500", headers=admin_headers)
    assert events_response.status_code == 200, events_response.text
    items = events_response.json().get("items") or []
    seqs = [int(item["seq"]) for item in items]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))


async def test_runtime_cancel_sets_cancel_requested_flag(test_client, admin_headers):
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    idem_key = f"idem-{uuid.uuid4().hex}"
    create_response = await test_client.post(
        "/api/runtime/runs",
        json={
            "agent_id": "DynamicAgent",
            "thread_id": thread_id,
            "mode": "hybrid",
            "input": {"query": "cancel me"},
        },
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    assert create_response.status_code == 200, create_response.text
    run_id = create_response.json().get("run_id")
    assert run_id

    dispatch = await runtime_service.transition_status(
        run_id=run_id,
        next_status="dispatching",
        actor_type="system",
        actor_name="pytest",
    )
    assert dispatch
    running = await runtime_service.transition_status(
        run_id=run_id,
        next_status="running",
        actor_type="system",
        actor_name="pytest",
    )
    assert running

    cancel_response = await test_client.post(f"/api/runtime/runs/{run_id}/cancel", headers=admin_headers)
    assert cancel_response.status_code == 200, cancel_response.text

    detail_response = await test_client.get(f"/api/runtime/runs/{run_id}", headers=admin_headers)
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail.get("status") == "cancelled"
    assert detail.get("cancel_requested") is True


async def test_runtime_run_mode_can_be_aligned_after_creation(test_client, admin_headers):
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    idem_key = f"idem-{uuid.uuid4().hex}"
    create_response = await test_client.post(
        "/api/runtime/runs",
        json={
            "agent_id": "DynamicAgent",
            "thread_id": thread_id,
            "mode": "hybrid",
            "input": {"query": "mode alignment"},
        },
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    assert create_response.status_code == 200, create_response.text
    run_id = create_response.json().get("run_id")
    assert run_id

    updated = await runtime_service.update_run_fields(run_id, mode="deep_agents")
    assert updated is not None
    assert updated.get("mode") == "deep_agents"

    detail_response = await test_client.get(f"/api/runtime/runs/{run_id}", headers=admin_headers)
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json().get("mode") == "deep_agents"


async def test_runtime_terminal_transition_emits_single_terminal_event(test_client, admin_headers):
    thread_id = f"thread-{uuid.uuid4().hex[:10]}"
    idem_key = f"idem-{uuid.uuid4().hex}"
    create_response = await test_client.post(
        "/api/runtime/runs",
        json={
            "agent_id": "DynamicAgent",
            "thread_id": thread_id,
            "mode": "hybrid",
            "input": {"query": "terminal event"},
        },
        headers={**admin_headers, "X-Idempotency-Key": idem_key},
    )
    assert create_response.status_code == 200, create_response.text
    run_id = create_response.json().get("run_id")
    assert run_id

    await runtime_service.transition_status(
        run_id=run_id,
        next_status="dispatching",
        actor_type="system",
        actor_name="pytest",
    )
    await runtime_service.transition_status(
        run_id=run_id,
        next_status="running",
        actor_type="system",
        actor_name="pytest",
    )
    await runtime_service.transition_status(
        run_id=run_id,
        next_status="failed",
        actor_type="system",
        actor_name="pytest",
        reason="boom",
    )

    events_response = await test_client.get(f"/api/runtime/runs/{run_id}/events?limit=500", headers=admin_headers)
    assert events_response.status_code == 200, events_response.text
    items = events_response.json().get("items") or []
    failed_events = [item for item in items if item.get("event_type") == "run.failed"]
    assert len(failed_events) == 1
