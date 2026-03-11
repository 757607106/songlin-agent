from __future__ import annotations

from src.agents.reporter.agents.analysis_agent import build_analysis_system_prompt


def test_analysis_prompt_keeps_status_contract_with_custom_prompt():
    prompt = build_analysis_system_prompt("请重点分析趋势、异常点和下一步建议。")

    assert "status: ANALYSIS_READY | ANALYSIS_SKIPPED | ANALYSIS_ERROR" in prompt
    assert "请重点分析趋势、异常点和下一步建议。" in prompt
