"""DynamicAgent context schema — configurable multi-agent parameters.

Extends BaseContext with fields for multi-agent collaboration,
including mode selection and subagent configuration.
"""

from dataclasses import dataclass, field
from typing import Annotated

from src.agents.common.context import BaseContext

# --- Multi-Agent Mode Choices ---
MULTI_AGENT_MODES = ["disabled", "supervisor", "deep_agents"]

# --- Default subagent template ---
DEFAULT_SUBAGENT_TEMPLATE = {
    "name": "",
    "description": "",
    "system_prompt": "",
    "tools": [],
    "model": None,
    "knowledges": [],
    "mcps": [],
    "depends_on": [],
    "allowed_targets": [],
    "communication_mode": "hybrid",
    "max_retries": 1,
    "plugin": "default",
}


@dataclass(kw_only=True)
class DynamicAgentContext(BaseContext):
    """Context schema for DynamicAgent.

    Adds multi-agent collaboration fields on top of the base configuration.

    Configuration priority (same as BaseContext):
      1. Runtime config (function parameters) — highest
      2. File config (config.private.yaml) — medium
      3. Class defaults — lowest
    """

    multi_agent_mode: Annotated[
        str,
        {"__template_metadata__": {"kind": "select"}},
    ] = field(
        default="disabled",
        metadata={
            "name": "多智能体协作模式",
            "options": MULTI_AGENT_MODES,
            "description": (
                "选择多智能体协作模式：\n"
                "• disabled — 单智能体模式\n"
                "• supervisor — Supervisor 子图模式（完全可观测子智能体过程）\n"
                "• deep_agents — Deep Agents 模式（高效并行，子智能体过程不可见）"
            ),
        },
    )

    team_goal: Annotated[
        str,
        {"__template_metadata__": {"kind": "prompt"}},
    ] = field(
        default="",
        metadata={
            "name": "团队目标",
            "description": "团队级任务目标，用于统一多 Agent 的执行方向。",
        },
    )

    task_scope: Annotated[
        str,
        {"__template_metadata__": {"kind": "prompt"}},
    ] = field(
        default="",
        metadata={
            "name": "任务范围",
            "description": "定义本团队职责边界，避免无关任务进入执行链路。",
        },
    )

    communication_protocol: Annotated[
        str,
        {"__template_metadata__": {"kind": "select"}},
    ] = field(
        default="hybrid",
        metadata={
            "name": "通信协议",
            "options": ["sync", "async", "hybrid"],
            "description": "团队内通信模式：同步、异步或混合。",
        },
    )

    max_parallel_tasks: int = field(
        default=4,
        metadata={
            "name": "最大并行任务数",
            "description": "Deep Agents 模式的并行阶段上限。",
        },
    )

    allow_cross_agent_comm: bool = field(
        default=False,
        metadata={
            "name": "允许跨 Agent 自由通信",
            "description": "关闭后按依赖关系和 allowed_targets 约束通信。",
        },
    )

    subagents: Annotated[
        list[dict],
        {"__template_metadata__": {"kind": "subagents"}},
    ] = field(
        default_factory=list,
        metadata={
            "name": "子智能体列表",
            "description": (
                "配置多智能体协作中的子智能体。"
                "每个子智能体需要 name、description、system_prompt 字段。"
                "可选 tools、model、knowledges、mcps 字段。"
            ),
        },
    )

    supervisor_system_prompt: Annotated[
        str,
        {"__template_metadata__": {"kind": "prompt"}},
    ] = field(
        default="",
        metadata={
            "name": "Supervisor 提示词",
            "description": (
                "仅在 Supervisor 模式下生效。用于指导 Supervisor 如何路由任务到子智能体。留空则使用默认路由提示词。"
            ),
        },
    )
