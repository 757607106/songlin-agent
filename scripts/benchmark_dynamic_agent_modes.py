from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure `python scripts/benchmark_dynamic_agent_modes.py` works without manual PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.team_orchestration_service import team_orchestration_service  # noqa: E402


SAMPLE_TEAM = {
    "team_goal": "完成跨来源研究并输出可执行结论",
    "task_scope": "仅使用公开资料，产出研究结论与建议",
    "multi_agent_mode": "deep_agents",
    "communication_protocol": "hybrid",
    "max_parallel_tasks": 2,
    "subagents": [
        {
            "name": "planner",
            "description": "拆解任务并定义执行阶段",
            "system_prompt": "你负责任务拆解、依赖管理和调度建议。",
            "depends_on": [],
            "max_retries": 1,
        },
        {
            "name": "researcher",
            "description": "检索与归纳证据",
            "system_prompt": "你负责检索公开信息并输出结构化证据。",
            "depends_on": ["planner"],
            "max_retries": 2,
        },
        {
            "name": "analyst",
            "description": "冲突裁决与结论汇总",
            "system_prompt": "你负责冲突结论裁决并输出最终报告。",
            "depends_on": ["researcher"],
            "max_retries": 1,
        },
    ],
}


def render_markdown(benchmark: dict) -> str:
    mode = benchmark["mode_comparison"]
    timings = benchmark["timings"]
    groups = benchmark.get("execution_groups") or []

    lines = [
        "# DynamicAgent 三模式性能基准报告",
        "",
        f"- 生成时间: {datetime.now(UTC).isoformat()}",
        "- 基准方式: TeamOrchestrationService 本地基准（校验+上下文构建+模式估算）",
        "",
        "## 结果总览",
        "",
        f"- 校验平均耗时: `{timings['avg_validate_ms']} ms`",
        f"- 上下文构建平均耗时: `{timings['avg_build_context_ms']} ms`",
        f"- disabled 估算成本: `{mode['disabled_estimated_cost']}`",
        f"- supervisor 估算成本: `{mode['supervisor_estimated_cost']}`",
        f"- deep_agents 估算成本: `{mode['deep_agents_estimated_cost']}`",
        f"- deep_agents vs disabled 加速比: `{mode['deep_vs_disabled_speedup']}x`",
        f"- deep_agents vs supervisor 加速比: `{mode['deep_vs_supervisor_speedup']}x`",
        "",
        "## 执行阶段",
        "",
    ]

    if groups:
        for idx, group in enumerate(groups, start=1):
            lines.append(f"- 阶段 {idx}: {', '.join(group)}")
    else:
        lines.append("- 无执行阶段数据")

    lines += [
        "",
        "## 说明",
        "",
        "- 该报告用于比较三种模式在同一团队拓扑下的相对执行开销。",
        "- 真正线上性能仍受模型响应时延、MCP 工具耗时、知识库检索耗时影响。",
    ]

    return "\n".join(lines)


def main() -> None:
    benchmark = team_orchestration_service.benchmark_modes(SAMPLE_TEAM, iterations=20)

    out_dir = Path("docs/vibe/multi-agent-team-system")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "performance-benchmark.json"
    md_path = out_dir / "performance-benchmark.md"

    json_path.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(benchmark), encoding="utf-8")

    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
