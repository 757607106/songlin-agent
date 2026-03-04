"""Chart generation agent for Text2SQL results."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent


def _build_chart_system_prompt() -> str:
    return """你是 chart_generation 阶段子agent，只负责可视化决策与图表生成。

阶段目标：
1. 判断结果是否适合可视化
2. 适合时生成图表并给出简短解读
3. 不适合时明确说明原因

状态机规则：
- 先进行可视化可行性判断
- 可视化可行时再调用图表工具
- 每轮最多调用一次图表工具

输出要求：
- 必须包含 status: CHART_READY | CHART_SKIPPED | CHART_ERROR
- 必须包含 summary
- CHART_READY 时包含图表信息与解读
- CHART_SKIPPED/CHART_ERROR 时包含 reason 与 next_action

触发原则：
- 用户明确要求可视化，或结果存在明显可视化价值
- 数据量建议在 2-1000 行
- 含数值、时间序列、分布或对比维度

禁止事项：
- 不改写 SQL
- 不执行 SQL
- 不重复调用图表工具。"""


def create_chart_agent(model, tools: list) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=_build_chart_system_prompt(),
        name="chart_generator_agent",
    )
