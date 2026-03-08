"""
Integration tests for DynamicAgent team builder session and permissions.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _sample_team_payload() -> dict:
    return {
        "team_goal": "交付需求开发版本",
        "task_scope": "覆盖需求、研发、测试与文档交付",
        "multi_agent_mode": "deep_agents",
        "communication_protocol": "hybrid",
        "max_parallel_tasks": 3,
        "skills": [],
        "subagents": [
            {
                "name": "planner",
                "description": "拆解任务并定义依赖",
                "system_prompt": "负责任务拆解与排期。",
                "depends_on": [],
                "skills": [],
            },
            {
                "name": "executor",
                "description": "执行研发任务并输出结果",
                "system_prompt": "负责执行研发任务并提交结果。",
                "depends_on": ["planner"],
                "skills": [],
            },
        ],
    }


def _sample_chat_profile_payload(mode: str) -> dict:
    return {
        "team_goal": f"执行 {mode} 模式回归",
        "task_scope": "只执行最小聊天回复，不调用外部能力。",
        "multi_agent_mode": mode,
        "communication_protocol": "hybrid",
        "max_parallel_tasks": 2,
        "system_prompt": "你是主智能体，收到任务后给出简洁结果。",
        "supervisor_system_prompt": "你负责将任务路由给合适子智能体并汇总结果。",
        "subagents": [
            {
                "name": "planner",
                "description": "规划执行步骤并给出结论草稿",
                "system_prompt": "你负责理解问题并给出结论草稿。",
                "depends_on": [],
            },
            {
                "name": "writer",
                "description": "输出最终结果",
                "system_prompt": "你负责把结果整理成简短答复。",
                "depends_on": ["planner"],
            },
        ],
    }


async def _require_live_dynamic_agent_chat_or_skip():
    if os.getenv("TEST_ENABLE_LIVE_DYNAMIC_AGENT_CHAT", "0") != "1":
        pytest.skip("Set TEST_ENABLE_LIVE_DYNAMIC_AGENT_CHAT=1 to run live DynamicAgent chat tests.")


async def _require_department_or_skip(test_client, headers):
    profile = await test_client.get("/api/auth/me", headers=headers)
    assert profile.status_code == 200, profile.text
    data = profile.json()
    if not data.get("department_id"):
        pytest.skip("Test user has no department binding; skip team builder integration tests.")


async def test_standard_user_can_crud_dynamic_config_but_not_other_agents(test_client, admin_headers, standard_user):
    await _require_department_or_skip(test_client, standard_user["headers"])

    dynamic_create = await test_client.post(
        "/api/chat/agent/DynamicAgent/configs",
        json={
            "name": f"pytest_dynamic_cfg_{uuid.uuid4().hex[:8]}",
            "description": "dynamic config by standard user",
            "config_json": {"context": {"multi_agent_mode": "disabled"}},
        },
        headers=standard_user["headers"],
    )
    assert dynamic_create.status_code == 200, dynamic_create.text
    config_id = dynamic_create.json()["config"]["id"]

    dynamic_set_default = await test_client.post(
        f"/api/chat/agent/DynamicAgent/configs/{config_id}/set_default",
        json={},
        headers=standard_user["headers"],
    )
    assert dynamic_set_default.status_code == 200, dynamic_set_default.text

    agents_response = await test_client.get("/api/chat/agent", headers=admin_headers)
    assert agents_response.status_code == 200, agents_response.text
    agents = agents_response.json().get("agents", [])
    non_dynamic = next((a["id"] for a in agents if a.get("id") and a.get("id") != "DynamicAgent"), None)
    if non_dynamic:
        forbidden = await test_client.post(
            f"/api/chat/agent/{non_dynamic}/configs",
            json={"name": "forbidden_cfg", "config_json": {"context": {}}},
            headers=standard_user["headers"],
        )
        assert forbidden.status_code == 403, forbidden.text

    cleanup = await test_client.delete(
        f"/api/chat/agent/DynamicAgent/configs/{config_id}",
        headers=standard_user["headers"],
    )
    assert cleanup.status_code == 200, cleanup.text


async def test_team_session_flow_create_resume_and_create_profile(test_client, standard_user):
    await _require_department_or_skip(test_client, standard_user["headers"])
    team_payload = _sample_team_payload()

    create_session = await test_client.post(
        "/api/chat/agent/DynamicAgent/team/session",
        json={
            "title": "pytest team session",
            "message": "请基于当前草稿生成会话",
            "draft": team_payload,
            "auto_complete": False,
        },
        headers=standard_user["headers"],
    )
    assert create_session.status_code == 200, create_session.text
    session_data = create_session.json()
    thread_id = session_data["thread_id"]
    available_skills = (
        session_data.get("team_builder", {}).get("resource_validation", {}).get("available", {}).get("skills", [])
    )
    draft = session_data["team_builder"]["draft"]
    assert draft["skills"] == []
    assert draft["subagents"][0]["skills"] == []
    assert draft["subagents"][1]["skills"] == []

    send_message = await test_client.post(
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}/message",
        json={"message": "追加说明：需要稳定优先。", "auto_complete": False},
        headers=standard_user["headers"],
    )
    assert send_message.status_code == 200, send_message.text

    get_session = await test_client.get(
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}",
        headers=standard_user["headers"],
    )
    assert get_session.status_code == 200, get_session.text
    assert get_session.json()["thread_id"] == thread_id

    update_draft = await test_client.put(
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}/draft",
        json={
            "draft": {
                **team_payload,
                "skills": [available_skills[0]] if available_skills else [],
            },
            "strict": True,
        },
        headers=standard_user["headers"],
    )
    assert update_draft.status_code == 200, update_draft.text
    updated_draft = update_draft.json()["team_builder"]["draft"]
    assert updated_draft["skills"] == ([available_skills[0]] if available_skills else [])

    create_profile = await test_client.post(
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}/create",
        json={"name": f"pytest_team_profile_{uuid.uuid4().hex[:8]}", "set_default": False},
        headers=standard_user["headers"],
    )
    assert create_profile.status_code == 200, create_profile.text
    config_id = create_profile.json()["config"]["id"]

    cleanup = await test_client.delete(
        f"/api/chat/agent/DynamicAgent/configs/{config_id}",
        headers=standard_user["headers"],
    )
    assert cleanup.status_code == 200, cleanup.text


async def test_team_session_message_stream_returns_chunks_and_persists_history(test_client, standard_user):
    await _require_department_or_skip(test_client, standard_user["headers"])

    create_session = await test_client.post(
        "/api/chat/agent/DynamicAgent/team/session",
        json={"title": "pytest team stream session"},
        headers=standard_user["headers"],
    )
    assert create_session.status_code == 200, create_session.text
    thread_id = create_session.json()["thread_id"]

    statuses = []
    async with test_client.stream(
        "POST",
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}/message/stream",
        json={"message": "请继续完善团队，并优先稳定性。", "auto_complete": False},
        headers=standard_user["headers"],
    ) as response:
        assert response.status_code == 200
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            statuses.append(chunk.get("status"))

    assert "init" in statuses
    assert "loading" in statuses
    assert "finished" in statuses

    get_session = await test_client.get(
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}",
        headers=standard_user["headers"],
    )
    assert get_session.status_code == 200, get_session.text
    history = get_session.json().get("history", [])
    assert len(history) >= 2
    assert history[-2]["role"] == "user"
    assert history[-1]["role"] == "assistant"


async def test_team_session_stream_builds_team_draft_from_json_message(test_client, standard_user):
    await _require_department_or_skip(test_client, standard_user["headers"])

    create_session = await test_client.post(
        "/api/chat/agent/DynamicAgent/team/session",
        json={"title": "pytest stream build session"},
        headers=standard_user["headers"],
    )
    assert create_session.status_code == 200, create_session.text
    thread_id = create_session.json()["thread_id"]

    target_team = {
        "team_goal": "交付稳定可观测的需求开发版本",
        "task_scope": "覆盖需求、研发、测试，不包含运维值班",
        "multi_agent_mode": "deep_agents",
        "communication_protocol": "hybrid",
        "max_parallel_tasks": 3,
        "tools": ["calculator"],
        "knowledges": ["kb_a"],
        "mcps": ["dev-mcp"],
        "skills": ["team/research"],
        "subagents": [
            {
                "name": "planner",
                "description": "拆解任务并编排依赖",
                "system_prompt": "你负责规划与依赖编排。",
                "tools": ["calculator"],
                "skills": ["planner/checklist"],
                "depends_on": [],
                "allowed_targets": ["executor"],
                "communication_mode": "sync",
                "max_retries": 1,
            },
            {
                "name": "executor",
                "description": "执行研发任务并输出产物",
                "system_prompt": "你负责执行研发任务。",
                "mcps": ["dev-mcp"],
                "skills": ["executor/delivery"],
                "depends_on": ["planner"],
                "allowed_targets": [],
                "communication_mode": "hybrid",
                "max_retries": 2,
            },
        ],
    }
    stream_message = f"请将团队配置更新为以下 JSON：```json\n{json.dumps(target_team, ensure_ascii=False)}\n```"

    statuses = []
    finished_chunk = None
    async with test_client.stream(
        "POST",
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}/message/stream",
        json={"message": stream_message, "auto_complete": False},
        headers=standard_user["headers"],
    ) as response:
        assert response.status_code == 200
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            statuses.append(chunk.get("status"))
            if chunk.get("status") == "finished":
                finished_chunk = chunk

    assert "init" in statuses
    assert "loading" in statuses
    assert "finished" in statuses
    assert finished_chunk is not None
    finished_draft = finished_chunk["team_builder"]["draft"]
    assert finished_draft["multi_agent_mode"] == "deep_agents"
    assert finished_draft["tools"] == ["calculator"]
    assert finished_draft["knowledges"] == ["kb_a"]
    assert finished_draft["mcps"] == ["dev-mcp"]
    assert finished_draft["skills"] == ["team/research"]
    assert finished_draft["subagents"][0]["allowed_targets"] == ["executor"]
    assert finished_draft["subagents"][0]["communication_mode"] == "sync"
    assert finished_draft["subagents"][1]["communication_mode"] == "hybrid"
    assert finished_draft["subagents"][1]["max_retries"] == 2

    get_session = await test_client.get(
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}",
        headers=standard_user["headers"],
    )
    assert get_session.status_code == 200, get_session.text
    persisted_draft = get_session.json()["team_builder"]["draft"]
    assert persisted_draft["tools"] == ["calculator"]
    assert persisted_draft["knowledges"] == ["kb_a"]
    assert persisted_draft["mcps"] == ["dev-mcp"]
    assert persisted_draft["skills"] == ["team/research"]
    assert persisted_draft["subagents"][0]["skills"] == ["planner/checklist"]
    assert persisted_draft["subagents"][1]["skills"] == ["executor/delivery"]
    assert persisted_draft["subagents"][0]["allowed_targets"] == ["executor"]
    assert persisted_draft["subagents"][0]["communication_mode"] == "sync"
    assert persisted_draft["subagents"][1]["communication_mode"] == "hybrid"
    assert persisted_draft["subagents"][1]["max_retries"] == 2


async def _create_team_profile_for_mode(test_client, headers: dict[str, str], mode: str) -> int:
    create_session = await test_client.post(
        "/api/chat/agent/DynamicAgent/team/session",
        json={
            "title": f"pytest live {mode} session",
            "draft": _sample_chat_profile_payload(mode),
            "auto_complete": False,
        },
        headers=headers,
    )
    assert create_session.status_code == 200, create_session.text
    thread_id = create_session.json()["thread_id"]

    create_profile = await test_client.post(
        f"/api/chat/agent/DynamicAgent/team/session/{thread_id}/create",
        json={"name": f"pytest_live_{mode}_{uuid.uuid4().hex[:8]}", "set_default": False},
        headers=headers,
    )
    assert create_profile.status_code == 200, create_profile.text
    return int(create_profile.json()["config"]["id"])


async def _run_dynamic_agent_chat_and_collect_status(
    test_client,
    headers: dict[str, str],
    *,
    agent_config_id: int,
) -> list[str]:
    thread_id = str(uuid.uuid4())
    statuses: list[str] = []
    async with test_client.stream(
        "POST",
        "/api/chat/agent/DynamicAgent",
        json={
            "query": "请用一句话回复：已完成。",
            "config": {
                "thread_id": thread_id,
                "agent_config_id": agent_config_id,
            },
            "meta": {},
        },
        headers=headers,
    ) as response:
        assert response.status_code == 200
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            status = chunk.get("status")
            if status:
                statuses.append(status)
    return statuses


async def test_live_dynamic_agent_chat_with_deep_agents_profile(test_client, standard_user):
    await _require_department_or_skip(test_client, standard_user["headers"])
    await _require_live_dynamic_agent_chat_or_skip()

    config_id = await _create_team_profile_for_mode(test_client, standard_user["headers"], mode="deep_agents")
    try:
        statuses = await _run_dynamic_agent_chat_and_collect_status(
            test_client, standard_user["headers"], agent_config_id=config_id
        )
        assert "init" in statuses
        assert "finished" in statuses
    finally:
        await test_client.delete(
            f"/api/chat/agent/DynamicAgent/configs/{config_id}",
            headers=standard_user["headers"],
        )


async def test_live_dynamic_agent_chat_with_supervisor_profile(test_client, standard_user):
    await _require_department_or_skip(test_client, standard_user["headers"])
    await _require_live_dynamic_agent_chat_or_skip()

    config_id = await _create_team_profile_for_mode(test_client, standard_user["headers"], mode="supervisor")
    try:
        statuses = await _run_dynamic_agent_chat_and_collect_status(
            test_client, standard_user["headers"], agent_config_id=config_id
        )
        assert "init" in statuses
        assert "finished" in statuses
    finally:
        await test_client.delete(
            f"/api/chat/agent/DynamicAgent/configs/{config_id}",
            headers=standard_user["headers"],
        )
