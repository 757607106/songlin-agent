from __future__ import annotations

from src.agents.reporter.tools import _select_relevant_schema
from src.services.text2sql_service import _extract_json_payload


def test_extract_json_payload_from_fenced_block():
    payload = """```json
    {\"intent\": \"统计\", \"tables\": [\"orders\"]}
    ```"""
    parsed = _extract_json_payload(payload)
    assert parsed is not None
    assert parsed["intent"] == "统计"
    assert parsed["tables"] == ["orders"]


def test_select_relevant_schema_expands_one_hop_relationship():
    tables = [
        {
            "table_name": "orders",
            "table_comment": "订单信息",
            "columns": [{"column_name": "customer_id", "column_comment": "客户ID"}],
        },
        {
            "table_name": "customers",
            "table_comment": "客户信息",
            "columns": [{"column_name": "id", "column_comment": "客户ID"}],
        },
        {
            "table_name": "products",
            "table_comment": "商品信息",
            "columns": [{"column_name": "name", "column_comment": "名称"}],
        },
    ]
    relationships = [
        {
            "source_table": "orders",
            "source_column": "customer_id",
            "target_table": "customers",
            "target_column": "id",
            "relationship_type": "many_to_one",
        }
    ]

    selected_tables, selected_relationships = _select_relevant_schema(
        tables=tables,
        relationships=relationships,
        question="统计订单数量",
        query_analysis={"tables": ["orders"], "columns": ["customer_id"]},
        max_tables=2,
    )

    selected_names = {t["table_name"] for t in selected_tables}
    assert "orders" in selected_names
    # one-hop relationship expansion should bring customers in.
    assert "customers" in selected_names
    assert len(selected_relationships) == 1
