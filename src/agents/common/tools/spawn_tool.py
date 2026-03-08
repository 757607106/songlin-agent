"""SpawnTool — lets the LLM autonomously create sub-agents at runtime.

Inspired by nanobot's SpawnTool design: the LLM decides *when* a task
deserves its own sub-agent by calling this tool, rather than relying on
a pre-configured team layout.

The tool delegates to :class:`SubagentRuntime` for isolated execution
and returns the sub-agent's result directly.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.agents.common.subagent_runtime import SubagentRuntime, SubagentStatus
from src.utils import logger


class SpawnSubagentInput(BaseModel):
    """Input schema for the spawn_subagent tool."""

    task: str = Field(description="要分配给子智能体的具体任务描述。需要清晰、完整，子智能体会独立执行此任务。")
    label: str | None = Field(
        default=None,
        description="任务的简短标签（用于显示和追踪），例如'分析CSV数据'。",
    )
    role_hint: str | None = Field(
        default=None,
        description="角色提示，帮助系统为子智能体选择合适的工具集。"
        "例如: 'researcher', 'data_analyst', 'coder', 'writer'。",
    )
    tools_hint: list[str] | None = Field(
        default=None,
        description="指定子智能体应使用的工具ID列表。"
        "如果不指定，系统会根据 role_hint 自动选择。"
        "例如: ['calculator', 'web_search']。",
    )


class SpawnSubagentTool(BaseTool):
    """LangChain tool that spawns an isolated sub-agent to handle a task.

    The main agent calls this tool when it encounters a sub-task that:
    - Can be executed independently and in parallel
    - Requires focused, potentially multi-step reasoning
    - Benefits from an isolated context to avoid polluting the main thread

    Example usage by the LLM::

        I need to analyze this data while continuing the conversation.
        Let me spawn a sub-agent for the analysis.

        Tool: spawn_subagent
        Args: {"task": "Analyze the sales data in /tmp/sales.csv",
               "role_hint": "data_analyst"}
    """

    name: str = "spawn_subagent"
    description: str = (
        "创建一个独立的子智能体来执行后台任务。"
        "适用于复杂的、可独立执行的、需要多步推理的子任务。"
        "子智能体拥有独立的工具集和上下文，会执行任务并返回结果。"
        "注意：只有当任务确实需要独立处理时才使用此工具，简单问题请直接回答。"
    )
    args_schema: type[BaseModel] = SpawnSubagentInput

    # Runtime instance (injected at registration time)
    runtime: SubagentRuntime = Field(default_factory=SubagentRuntime)

    class Config:
        arbitrary_types_allowed = True

    def _run(self, **kwargs: Any) -> str:
        """Sync fallback — not expected to be used."""
        raise NotImplementedError("SpawnSubagentTool only supports async execution")

    async def _arun(
        self,
        task: str,
        label: str | None = None,
        role_hint: str | None = None,
        tools_hint: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Execute the spawn: create a sub-agent, wait for result, return."""
        logger.info(f"SpawnTool: spawning sub-agent — task='{task[:50]}...', role={role_hint}, tools={tools_hint}")

        try:
            result = await self.runtime.spawn(
                task=task,
                label=label,
                role_hint=role_hint,
                tools_hint=tools_hint,
                wait=True,
            )

            if result.status == SubagentStatus.COMPLETED:
                return (
                    f"✅ 子智能体 [{result.label}] 完成任务 "
                    f"(经过 {result.iteration_count} 轮迭代)\n\n"
                    f"结果:\n{result.result}"
                )
            elif result.status == SubagentStatus.FAILED:
                return f"❌ 子智能体 [{result.label}] 执行失败\n错误: {result.error}"
            elif result.status == SubagentStatus.CANCELLED:
                return f"⚠️ 子智能体 [{result.label}] 已被取消"
            else:
                return f"⏳ 子智能体 [{result.label}] 状态: {result.status.value}"

        except Exception as e:
            logger.error(f"SpawnTool: failed to spawn sub-agent: {e}")
            return f"❌ 子智能体创建失败: {str(e)}"


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

_runtime_instance: SubagentRuntime | None = None


def get_spawn_tool(
    *,
    max_concurrency: int = 5,
    max_iterations: int = 15,
    model_name: str | None = None,
) -> SpawnSubagentTool:
    """Get a configured SpawnSubagentTool instance.

    Uses a module-level runtime singleton so that concurrency limits
    are shared across all tools in the same process.
    """
    global _runtime_instance
    if _runtime_instance is None:
        _runtime_instance = SubagentRuntime(
            max_concurrency=max_concurrency,
            max_iterations=max_iterations,
            model_name=model_name,
        )

    return SpawnSubagentTool(runtime=_runtime_instance)
