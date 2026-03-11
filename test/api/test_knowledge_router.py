"""
Integration tests for knowledge router and mindmap router endpoints.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from src import knowledge_base

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _assert_forbidden_response(response):
    """验证 403 禁止访问响应的格式"""
    assert response.status_code == 403
    payload = response.json()
    assert "detail" in payload
    assert isinstance(payload["detail"], str)


async def _upload_and_ingest_markdown_file(test_client, admin_headers, db_id: str, filename: str) -> None:
    upload_response = await test_client.post(
        f"/api/knowledge/files/upload?db_id={db_id}",
        files={"file": (filename, b"# FAQ\n\n## Q1\nA1\n", "text/markdown")},
        headers=admin_headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    upload_payload = upload_response.json()
    file_path = upload_payload["file_path"]
    content_hash = upload_payload["content_hash"]

    enqueue_response = await test_client.post(
        f"/api/knowledge/databases/{db_id}/documents",
        json={
            "items": [file_path],
            "params": {"content_type": "file", "content_hashes": {file_path: content_hash}},
        },
        headers=admin_headers,
    )
    assert enqueue_response.status_code == 200, enqueue_response.text
    task_id = enqueue_response.json()["task_id"]

    for _ in range(40):
        detail_response = await test_client.get(f"/api/tasks/{task_id}", headers=admin_headers)
        assert detail_response.status_code == 200, detail_response.text
        task_status = detail_response.json().get("task", {}).get("status")
        if task_status in {"success", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.5)
    else:
        pytest.fail("Knowledge ingestion task did not reach a terminal status within timeout window")

    assert task_status == "success"


async def test_admin_can_manage_knowledge_databases(test_client, admin_headers, knowledge_database):
    db_id = knowledge_database["db_id"]

    list_response = await test_client.get("/api/knowledge/databases", headers=admin_headers)
    assert list_response.status_code == 200, list_response.text
    databases = list_response.json().get("databases", [])
    assert any(entry["db_id"] == db_id for entry in databases)

    get_response = await test_client.get(f"/api/knowledge/databases/{db_id}", headers=admin_headers)
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["db_id"] == db_id

    update_response = await test_client.put(
        f"/api/knowledge/databases/{db_id}",
        json={"name": knowledge_database["name"], "description": "Updated by pytest"},
        headers=admin_headers,
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["database"]["description"] == "Updated by pytest"


async def test_knowledge_routes_enforce_permissions(test_client, standard_user, knowledge_database):
    db_id = knowledge_database["db_id"]

    forbidden_create = await test_client.post(
        "/api/knowledge/databases",
        json={
            "database_name": "unauthorized_db",
            "description": "Should not succeed",
            "embed_model_name": "siliconflow/BAAI/bge-m3",
        },
        headers=standard_user["headers"],
    )
    _assert_forbidden_response(forbidden_create)

    forbidden_list = await test_client.get("/api/knowledge/databases", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_list)

    forbidden_get = await test_client.get(f"/api/knowledge/databases/{db_id}", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_get)


async def test_admin_can_create_vector_db_with_reranker(test_client, admin_headers):
    """测试创建向量库并配置 reranker 参数（通过 query_params.options）

    注意：数据库清理由 conftest.py 中的 session fixture 自动处理。
    """
    db_name = f"pytest_rerank_{uuid.uuid4().hex[:6]}"
    payload = {
        "database_name": db_name,
        "description": "Vector DB with reranker",
        "embed_model_name": "siliconflow/BAAI/bge-m3",
        "kb_type": "milvus",
        "additional_params": {},
    }

    create_response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text

    db_payload = create_response.json()
    db_id = db_payload["db_id"]

    # 获取查询参数配置
    params_response = await test_client.get(f"/api/knowledge/databases/{db_id}/query-params", headers=admin_headers)
    assert params_response.status_code == 200, params_response.text

    params_payload = params_response.json()
    options = params_payload.get("params", {}).get("options", [])
    option_keys = {option.get("key") for option in options}

    # 验证新的参数名称
    assert "final_top_k" in option_keys
    assert "use_reranker" in option_keys
    assert "recall_top_k" in option_keys
    assert "reranker_model" in option_keys

    # 验证参数配置
    final_top_k_option = next((opt for opt in options if opt.get("key") == "final_top_k"), None)
    assert final_top_k_option is not None
    assert final_top_k_option.get("default") == 10

    use_reranker_option = next((opt for opt in options if opt.get("key") == "use_reranker"), None)
    assert use_reranker_option is not None
    assert use_reranker_option.get("default") is False

    # 保存查询参数（模拟前端配置）
    update_params = {
        "final_top_k": 5,
        "use_reranker": True,
        "recall_top_k": 20,
    }
    update_response = await test_client.put(
        f"/api/knowledge/databases/{db_id}/query-params", json=update_params, headers=admin_headers
    )
    assert update_response.status_code == 200, update_response.text

    # 再次获取参数，验证保存成功
    params_response2 = await test_client.get(f"/api/knowledge/databases/{db_id}/query-params", headers=admin_headers)
    assert params_response2.status_code == 200, params_response2.text

    params_payload2 = params_response2.json()
    options2 = params_payload2.get("params", {}).get("options", [])

    # 验证保存的值
    final_top_k_option2 = next((opt for opt in options2 if opt.get("key") == "final_top_k"), None)
    assert final_top_k_option2 is not None
    assert final_top_k_option2.get("default") == 5  # 保存的值

    use_reranker_option2 = next((opt for opt in options2 if opt.get("key") == "use_reranker"), None)
    assert use_reranker_option2 is not None
    assert use_reranker_option2.get("default") is True  # 保存的值


# =============================================================================
# === Mindmap Router Tests ===
# =============================================================================


async def test_get_databases_overview(test_client, admin_headers, knowledge_database):
    """测试获取所有知识库概览"""
    response = await test_client.get("/api/mindmap/databases", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "databases" in payload
    assert "total" in payload

    # 验证知识库在列表中
    db_ids = [db["db_id"] for db in payload["databases"]]
    assert knowledge_database["db_id"] in db_ids


async def test_get_database_files(test_client, admin_headers, knowledge_database):
    """测试获取知识库文件列表"""
    db_id = knowledge_database["db_id"]
    response = await test_client.get(f"/api/mindmap/databases/{db_id}/files", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert payload["db_id"] == db_id
    assert "files" in payload
    assert "total" in payload
    assert payload["db_name"] == knowledge_database["name"]


async def test_get_database_files_after_ingest_rehydrates_from_db(test_client, admin_headers, knowledge_database):
    """文件列表应以数据库记录为准，即使运行时内存元数据被清空。"""
    db_id = knowledge_database["db_id"]

    await _upload_and_ingest_markdown_file(test_client, admin_headers, db_id, "mindmap-regression.md")

    kb_instance = await knowledge_base.aget_kb(db_id)
    stale_file_ids = [file_id for file_id, meta in kb_instance.files_meta.items() if meta.get("database_id") == db_id]
    for file_id in stale_file_ids:
        kb_instance.files_meta.pop(file_id, None)

    response = await test_client.get(f"/api/mindmap/databases/{db_id}/files", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 1
    assert payload["files"][0]["filename"] == "mindmap-regression.md"
    assert payload["files"][0]["status"] == "parsed"


async def test_get_database_files_not_found(test_client, admin_headers):
    """测试获取不存在的知识库文件列表"""
    response = await test_client.get("/api/mindmap/databases/nonexistent_db_id/files", headers=admin_headers)
    assert response.status_code == 404


async def test_generate_mindmap_empty_files(test_client, admin_headers, knowledge_database):
    """测试空文件列表生成思维导图"""
    db_id = knowledge_database["db_id"]
    response = await test_client.post(
        "/api/mindmap/generate",
        json={"db_id": db_id, "file_ids": [], "user_prompt": ""},
        headers=admin_headers,
    )
    # 空文件应该返回400错误
    assert response.status_code == 400
    assert "中没有文件" in response.json()["detail"]


async def test_get_database_mindmap_not_exists(test_client, admin_headers, knowledge_database):
    """测试获取不存在的思维导图"""
    db_id = knowledge_database["db_id"]
    response = await test_client.get(f"/api/mindmap/database/{db_id}", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["db_id"] == db_id
    assert payload["mindmap"] is None  # 尚未生成思维导图


async def test_generate_and_get_mindmap(test_client, admin_headers, knowledge_database, monkeypatch):
    """测试上传文件后生成并读取思维导图。"""
    from server.routers import mindmap_router

    db_id = knowledge_database["db_id"]
    await _upload_and_ingest_markdown_file(test_client, admin_headers, db_id, "mindmap-generate.md")

    class _FakeResponse:
        content = """
        {
          "content": "测试知识库",
          "children": [
            {
              "content": "📚 文档",
              "children": [
                {"content": "mindmap-generate.md", "children": []}
              ]
            }
          ]
        }
        """

    class _FakeModel:
        async def call(self, messages, stream=False):
            return _FakeResponse()

    monkeypatch.setattr(mindmap_router, "select_model", lambda: _FakeModel())

    generate_response = await test_client.post(
        "/api/mindmap/generate",
        json={"db_id": db_id, "file_ids": [], "user_prompt": ""},
        headers=admin_headers,
    )
    assert generate_response.status_code == 200, generate_response.text
    generate_payload = generate_response.json()
    assert generate_payload["message"] == "success"
    assert generate_payload["file_count"] == 1
    assert generate_payload["mindmap"]["content"]
    assert generate_payload["mindmap"]["children"][0]["children"][0]["content"] == "mindmap-generate.md"

    saved_response = await test_client.get(f"/api/mindmap/database/{db_id}", headers=admin_headers)
    assert saved_response.status_code == 200, saved_response.text
    saved_payload = saved_response.json()
    assert saved_payload["db_id"] == db_id
    assert saved_payload["mindmap"]["children"][0]["children"][0]["content"] == "mindmap-generate.md"


# =============================================================================
# === Knowledge Router Additional Tests ===
# =============================================================================


async def test_get_accessible_databases(test_client, admin_headers, knowledge_database):
    """测试获取可访问的知识库列表"""
    response = await test_client.get("/api/knowledge/databases/accessible", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "databases" in payload

    # 验证知识库在列表中
    db_ids = [db["db_id"] for db in payload["databases"]]
    assert knowledge_database["db_id"] in db_ids


async def test_get_knowledge_base_types(test_client, admin_headers):
    """测试获取支持的知识库类型"""
    response = await test_client.get("/api/knowledge/types", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "kb_types" in payload


async def test_get_knowledge_base_statistics(test_client, admin_headers):
    """测试获取知识库统计信息"""
    response = await test_client.get("/api/knowledge/stats", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "stats" in payload


async def test_get_supported_file_types(test_client, admin_headers):
    """测试获取支持的文件类型"""
    response = await test_client.get("/api/knowledge/files/supported-types", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["message"] == "success"
    assert "file_types" in payload
    assert isinstance(payload["file_types"], list)


async def test_duplicate_database_name(test_client, admin_headers, knowledge_database):
    """测试重复创建同名知识库"""
    db_name = knowledge_database["name"]
    response = await test_client.post(
        "/api/knowledge/databases",
        json={
            "database_name": db_name,
            "description": "Duplicate name test",
            "embed_model_name": "siliconflow/BAAI/bge-m3",
            "kb_type": "lightrag",
            "additional_params": {},
        },
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert "已存在" in response.json()["detail"]


async def test_create_milvus_knowledge_base(test_client, admin_headers):
    """测试创建 Milvus 知识库

    注意：数据库清理由 conftest.py 中的 session fixture 自动处理。
    """
    db_name = f"pytest_milvus_{uuid.uuid4().hex[:6]}"
    payload = {
        "database_name": db_name,
        "description": "Pytest Milvus knowledge base",
        "embed_model_name": "siliconflow/BAAI/bge-m3",
        "kb_type": "milvus",
        "additional_params": {},
    }

    create_response = await test_client.post("/api/knowledge/databases", json=payload, headers=admin_headers)
    assert create_response.status_code == 200, create_response.text

    db_payload = create_response.json()
    assert db_payload["kb_type"] == "milvus"


async def test_sample_questions_endpoints(test_client, admin_headers, knowledge_database):
    """测试示例问题接口（空文件时预期返回400）"""
    db_id = knowledge_database["db_id"]

    # 获取示例问题（空知识库应该返回空列表）
    get_response = await test_client.get(f"/api/knowledge/databases/{db_id}/sample-questions", headers=admin_headers)
    assert get_response.status_code == 200, get_response.text
    get_payload = get_response.json()
    assert get_payload["db_id"] == db_id
    assert "questions" in get_payload
    assert get_payload["count"] == 0  # 空知识库没有问题

    # 生成示例问题（空知识库应该返回400）
    generate_response = await test_client.post(
        f"/api/knowledge/databases/{db_id}/sample-questions",
        json={"count": 5},
        headers=admin_headers,
    )
    assert generate_response.status_code == 400
    assert "中没有文件" in generate_response.json()["detail"]


async def test_mindmap_permissions(test_client, standard_user, knowledge_database):
    """测试思维导图接口的权限控制"""
    db_id = knowledge_database["db_id"]

    # 普通用户应该无法访问
    forbidden_list = await test_client.get("/api/mindmap/databases", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_list)

    forbidden_files = await test_client.get(f"/api/mindmap/databases/{db_id}/files", headers=standard_user["headers"])
    _assert_forbidden_response(forbidden_files)

    forbidden_generate = await test_client.post(
        "/api/mindmap/generate",
        json={"db_id": db_id, "file_ids": []},
        headers=standard_user["headers"],
    )
    _assert_forbidden_response(forbidden_generate)
