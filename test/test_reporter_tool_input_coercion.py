from __future__ import annotations

from src.agents.reporter.tools import ErrorPatternInput, GenerateSqlInput, RecoveryStrategyInput


def test_generate_sql_input_accepts_stringified_structures():
    payload = GenerateSqlInput(
        user_query="统计已支付订单金额",
        schema_info='{"schema_text": "orders(id, amount, status)"}',
        value_mappings='{"orders.status": {"已支付": "paid"}}',
        sample_qa_pairs='[]',
        db_type="sqlite",
    )

    assert payload.schema_info == {"schema_text": "orders(id, amount, status)"}
    assert payload.value_mappings == {"orders.status": {"已支付": "paid"}}
    assert payload.sample_qa_pairs == []


def test_error_recovery_inputs_accept_stringified_structures():
    error_pattern = ErrorPatternInput(
        error_history='[{"stage": "sql_generation", "error": "value_mappings: Input should be a valid dictionary"}]'
    )
    recovery = RecoveryStrategyInput(
        error_analysis='{"most_common_type": "unknown_error"}',
        current_state='{"retry_count": 1}',
    )

    assert error_pattern.error_history == [
        {"stage": "sql_generation", "error": "value_mappings: Input should be a valid dictionary"}
    ]
    assert recovery.error_analysis == {"most_common_type": "unknown_error"}
    assert recovery.current_state == {"retry_count": 1}
