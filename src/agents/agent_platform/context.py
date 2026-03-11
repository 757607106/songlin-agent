"""AgentPlatform runtime context schema.

用于新平台自定义 Agent 的运行时配置，替代旧多智能体公开上下文入口。
"""

from dataclasses import dataclass, field
from typing import Annotated

from src.agents.common.context import BaseContext
from src.services.skill_catalog_service import list_skill_catalog

MULTI_AGENT_MODES = ["disabled", "supervisor", "deep_agents", "swarm"]


@dataclass(kw_only=True)
class AgentPlatformContext(BaseContext):
    multi_agent_mode: Annotated[
        str,
        {"__template_metadata__": {"kind": "select"}},
    ] = field(
        default="disabled",
        metadata={
            "name": "多智能体协作模式",
            "options": MULTI_AGENT_MODES,
            "description": (
                "选择执行模式：\n"
                "• disabled — 单智能体模式\n"
                "• supervisor — Supervisor 受控编排\n"
                "• deep_agents — Deep Agents 自治执行\n"
                "• swarm — Swarm Handoff 协作"
            ),
        },
    )

    team_goal: Annotated[
        str,
        {"__template_metadata__": {"kind": "prompt"}},
    ] = field(
        default="",
        metadata={"name": "团队目标", "description": "多 worker 协作的全局目标。"},
    )

    task_scope: Annotated[
        str,
        {"__template_metadata__": {"kind": "prompt"}},
    ] = field(
        default="",
        metadata={"name": "任务范围", "description": "当前 agent 的职责边界。"},
    )

    communication_protocol: Annotated[
        str,
        {"__template_metadata__": {"kind": "select"}},
    ] = field(
        default="hybrid",
        metadata={
            "name": "通信协议",
            "options": ["sync", "async", "hybrid"],
            "description": "worker 间协作模式。",
        },
    )

    max_parallel_tasks: int = field(
        default=4,
        metadata={"name": "最大并行任务数", "description": "并行 worker 阶段上限。"},
    )

    allow_cross_agent_comm: bool = field(
        default=False,
        metadata={"name": "允许跨 Agent 通信", "description": "关闭后按依赖与允许路由约束执行。"},
    )

    spawn_enabled: bool = field(
        default=True,
        metadata={"name": "启用动态 Spawn", "description": "是否允许运行时创建临时 worker。"},
    )

    max_spawn_concurrency: int = field(
        default=5,
        metadata={"name": "最大 Spawn 并发数", "description": "同时运行的动态 worker 数量上限。"},
    )

    skills: Annotated[
        list[str],
        {"__template_metadata__": {"kind": "skills"}},
    ] = field(
        default_factory=list,
        metadata={
            "name": "技能",
            "options": lambda: list_skill_catalog(),
            "description": "主 agent 可加载的 Skills。",
        },
    )

    subagents: Annotated[
        list[dict],
        {"__template_metadata__": {"kind": "subagents"}},
    ] = field(
        default_factory=list,
        metadata={
            "name": "Worker 列表",
            "description": "执行期 worker 配置，由 AgentSpec 编译后生成。",
        },
    )

    supervisor_system_prompt: Annotated[
        str,
        {"__template_metadata__": {"kind": "prompt"}},
    ] = field(
        default="",
        metadata={"name": "Supervisor 提示词", "description": "Supervisor 执行模式下的路由提示词。"},
    )
