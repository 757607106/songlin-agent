from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_agent_design_draft_endpoint(test_client, admin_headers):
    response = await test_client.post(
        "/api/agent-design/draft",
        json={
            "prompt": "帮我创建一个知识库检索和 API 调用的多智能体助手",
            "available_resources": {
                "tools": ["http_request"],
                "knowledges": ["kb-demo"],
                "mcps": ["browser-mcp"],
            },
            "use_ai": False,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source"] == "template"
    assert payload["intent"]["execution_mode"] == "supervisor"
    workers = payload["blueprint"]["workers"]
    assert workers
    worker_map = {worker["key"]: worker for worker in workers}
    assert "kb-demo" in worker_map["retrieval_worker"]["knowledge_ids"]
    assert "http_request" in worker_map["retrieval_worker"]["tools"] or "http_request" in payload["blueprint"]["tools"]


async def test_agent_design_validate_and_compile_endpoints(test_client, admin_headers):
    blueprint = {
        "name": "Compile Team",
        "description": "compile test",
        "goal": "compile generated blueprint",
        "task_scope": "compile generated blueprint",
        "execution_mode": "supervisor",
        "workers": [
            {
                "key": "intake_worker",
                "name": "Intake Worker",
                "description": "collect input",
            },
            {
                "key": "execution_worker",
                "name": "Execution Worker",
                "description": "execute task",
                "depends_on": ["intake_worker"],
            },
        ],
    }

    validate_response = await test_client.post(
        "/api/agent-design/validate",
        json={"blueprint": blueprint},
        headers=admin_headers,
    )
    assert validate_response.status_code == 200, validate_response.text
    validation = validate_response.json()
    assert validation["valid"] is True

    compile_response = await test_client.post(
        "/api/agent-design/compile",
        json={"blueprint": blueprint},
        headers=admin_headers,
    )
    assert compile_response.status_code == 200, compile_response.text
    compiled = compile_response.json()
    assert compiled["validation"]["valid"] is True
    assert compiled["spec"]["execution_mode"] == "supervisor"
    assert compiled["spec"]["routing_policy"]["topological_order"] == [
        "intake_worker",
        "execution_worker",
    ]
