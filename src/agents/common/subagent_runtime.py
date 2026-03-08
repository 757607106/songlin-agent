"""Subagent runtime — isolated execution engine for dynamically spawned sub-agents.

Inspired by nanobot's SubagentManager: each spawned sub-agent runs in an
independent asyncio task with an isolated tool set and its own LLM
conversation loop.  Results are injected back into the parent agent's
context via a callback or direct return.

Key design principles:
  - **Tool isolation**: each sub-agent gets only the tools relevant to its
    role, built via ToolResolver (not the full global set).
  - **Bounded execution**: sub-agents have a configurable max-iteration
    limit to prevent runaway loops.
  - **Concurrency control**: a semaphore enforces the maximum number of
    sub-agents that may run concurrently.
  - **Graceful error handling**: failures are captured and returned as
    structured results rather than propagated.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from collections.abc import Callable, Awaitable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src import config as app_config
from src.agents.common.models import load_chat_model
from src.agents.common.subagents.registry import ToolResolver
from src.utils import logger


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class SubagentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubagentTask:
    """Represents a single spawned sub-agent task."""

    task_id: str
    task: str
    label: str
    role_hint: str | None = None
    tools_hint: list[str] | None = None
    status: SubagentStatus = SubagentStatus.PENDING
    result: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: str | None = None
    iteration_count: int = 0


@dataclass
class SubagentResult:
    """Result returned after a sub-agent completes."""

    task_id: str
    label: str
    task: str
    status: SubagentStatus
    result: str | None = None
    error: str | None = None
    iteration_count: int = 0


# ---------------------------------------------------------------------------
# SubagentRuntime
# ---------------------------------------------------------------------------


class SubagentRuntime:
    """Manages background sub-agent execution with isolated tool sets.

    Usage::

        runtime = SubagentRuntime(max_concurrency=5)
        result = await runtime.spawn(
            task="Analyze this CSV and generate a summary report",
            role_hint="data_analyst",
            tools_hint=["calculator", "web_search"],
        )
        # result.result contains the sub-agent's final answer
    """

    def __init__(
        self,
        *,
        max_concurrency: int = 5,
        max_iterations: int = 15,
        model_name: str | None = None,
        temperature: float = 0.1,
        on_result: Callable[[SubagentResult], Awaitable[None]] | None = None,
    ):
        self._max_iterations = max_iterations
        self._model_name = model_name or app_config.default_model
        self._temperature = temperature
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._running: dict[str, asyncio.Task] = {}
        self._tasks: dict[str, SubagentTask] = {}
        self._on_result = on_result

    # -- public API ---------------------------------------------------------

    async def spawn(
        self,
        task: str,
        *,
        label: str | None = None,
        role_hint: str | None = None,
        tools_hint: list[str] | None = None,
        knowledges: list[str] | None = None,
        mcps: list[str] | None = None,
        wait: bool = True,
    ) -> SubagentResult:
        """Spawn an isolated sub-agent to execute *task*.

        Args:
            task: Natural-language description of what the sub-agent should do.
            label: Short display label (defaults to first 30 chars of *task*).
            role_hint: Guides tool selection and system prompt (e.g. ``"coder"``).
            tools_hint: Explicit list of tool IDs the sub-agent should use.
            knowledges: Knowledge base names to include.
            mcps: MCP server names to include.
            wait: If ``True``, block until completion; otherwise return immediately
                  with status ``PENDING``.

        Returns:
            SubagentResult with the final answer or error information.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or (task[:30] + ("..." if len(task) > 30 else ""))

        sa_task = SubagentTask(
            task_id=task_id,
            task=task,
            label=display_label,
            role_hint=role_hint,
            tools_hint=tools_hint,
        )
        self._tasks[task_id] = sa_task

        if wait:
            return await self._run_subagent(sa_task, knowledges=knowledges, mcps=mcps)
        else:
            bg = asyncio.create_task(self._run_subagent(sa_task, knowledges=knowledges, mcps=mcps))
            self._running[task_id] = bg
            bg.add_done_callback(lambda _t: self._running.pop(task_id, None))
            return SubagentResult(
                task_id=task_id,
                label=display_label,
                task=task,
                status=SubagentStatus.PENDING,
            )

    async def spawn_many(
        self,
        tasks: list[dict[str, Any]],
        *,
        wait: bool = True,
    ) -> list[SubagentResult]:
        """Spawn multiple sub-agents in parallel.

        Each item in *tasks* is a dict passed as kwargs to :meth:`spawn`.
        """
        coros = [self.spawn(**t, wait=wait) for t in tasks]
        return await asyncio.gather(*coros, return_exceptions=False)

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running sub-agent."""
        bg = self._running.pop(task_id, None)
        if bg and not bg.done():
            bg.cancel()
            sa = self._tasks.get(task_id)
            if sa:
                sa.status = SubagentStatus.CANCELLED
            return True
        return False

    async def cancel_all(self) -> int:
        """Cancel all running sub-agents.  Returns count cancelled."""
        ids = list(self._running.keys())
        count = 0
        for tid in ids:
            if await self.cancel(tid):
                count += 1
        return count

    @property
    def running_count(self) -> int:
        return len(self._running)

    @property
    def task_summaries(self) -> list[dict[str, Any]]:
        """Brief status of all tracked tasks."""
        return [
            {
                "task_id": t.task_id,
                "label": t.label,
                "status": t.status.value,
                "iterations": t.iteration_count,
            }
            for t in self._tasks.values()
        ]

    # -- internal -----------------------------------------------------------

    async def _run_subagent(
        self,
        sa_task: SubagentTask,
        *,
        knowledges: list[str] | None = None,
        mcps: list[str] | None = None,
    ) -> SubagentResult:
        """Execute the sub-agent loop under the concurrency semaphore."""
        async with self._semaphore:
            sa_task.status = SubagentStatus.RUNNING
            logger.info(f"Subagent [{sa_task.task_id}] started: {sa_task.label}")

            try:
                # 1. Resolve tools for this sub-agent
                tools = await self._resolve_tools(
                    role_hint=sa_task.role_hint,
                    tools_hint=sa_task.tools_hint,
                    knowledges=knowledges,
                    mcps=mcps,
                )

                # 2. Build isolated LLM
                model = load_chat_model(self._model_name, temperature=self._temperature)
                if tools:
                    model = model.bind_tools(tools)

                # 3. Build initial messages
                system_prompt = self._build_system_prompt(sa_task, tools)
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=sa_task.task),
                ]

                # 4. Agent loop
                final_result: str | None = None
                iteration = 0

                while iteration < self._max_iterations:
                    iteration += 1
                    sa_task.iteration_count = iteration

                    response: AIMessage = await model.ainvoke(messages)
                    messages.append(response)

                    if not response.tool_calls:
                        final_result = response.content or ""
                        break

                    # Execute tool calls
                    for tool_call in response.tool_calls:
                        tool_name = tool_call["name"]
                        tool_args = tool_call["args"]
                        tool_map = {t.name: t for t in tools}
                        tool_obj = tool_map.get(tool_name)

                        if tool_obj:
                            try:
                                tool_result = await tool_obj.ainvoke(tool_args)
                                if not isinstance(tool_result, str):
                                    tool_result = json.dumps(tool_result, ensure_ascii=False)
                            except Exception as e:
                                tool_result = f"Error executing {tool_name}: {e}"
                        else:
                            tool_result = f"Error: tool '{tool_name}' not available"

                        messages.append(
                            ToolMessage(
                                content=tool_result,
                                tool_call_id=tool_call["id"],
                                name=tool_name,
                            )
                        )

                if final_result is None:
                    final_result = "Sub-agent reached max iterations without producing a final answer."

                sa_task.status = SubagentStatus.COMPLETED
                sa_task.result = final_result
                sa_task.completed_at = datetime.utcnow().isoformat()
                logger.info(f"Subagent [{sa_task.task_id}] completed ({iteration} iterations)")

                result = SubagentResult(
                    task_id=sa_task.task_id,
                    label=sa_task.label,
                    task=sa_task.task,
                    status=SubagentStatus.COMPLETED,
                    result=final_result,
                    iteration_count=iteration,
                )

            except asyncio.CancelledError:
                sa_task.status = SubagentStatus.CANCELLED
                sa_task.completed_at = datetime.utcnow().isoformat()
                result = SubagentResult(
                    task_id=sa_task.task_id,
                    label=sa_task.label,
                    task=sa_task.task,
                    status=SubagentStatus.CANCELLED,
                    error="Task was cancelled",
                )
            except Exception as e:
                sa_task.status = SubagentStatus.FAILED
                sa_task.error = str(e)
                sa_task.completed_at = datetime.utcnow().isoformat()
                logger.error(f"Subagent [{sa_task.task_id}] failed: {e}")
                result = SubagentResult(
                    task_id=sa_task.task_id,
                    label=sa_task.label,
                    task=sa_task.task,
                    status=SubagentStatus.FAILED,
                    error=str(e),
                )

            # Fire callback if registered
            if self._on_result:
                try:
                    await self._on_result(result)
                except Exception as cb_err:
                    logger.warning(f"Subagent result callback failed: {cb_err}")

            return result

    async def _resolve_tools(
        self,
        *,
        role_hint: str | None = None,
        tools_hint: list[str] | None = None,
        knowledges: list[str] | None = None,
        mcps: list[str] | None = None,
    ) -> list:
        """Build an isolated tool set for the sub-agent.

        If *tools_hint* is provided, use exactly those tool IDs.
        Otherwise, use *role_hint* to pick a sensible default set.
        """
        if tools_hint:
            return await ToolResolver.resolve(
                tool_ids=tools_hint,
                knowledges=knowledges,
                mcps=mcps,
            )

        # If no explicit tools, give a baseline set based on role
        default_tools = self._default_tools_for_role(role_hint)
        return await ToolResolver.resolve(
            tool_ids=default_tools,
            knowledges=knowledges,
            mcps=mcps,
        )

    @staticmethod
    def _default_tools_for_role(role_hint: str | None) -> list[str]:
        """Map a role hint to a sensible default tool set.

        This is a best-effort heuristic — the LLM will refine via
        tools_hint when it has more context.
        """
        if not role_hint:
            return ["calculator"]

        role = role_hint.lower()
        role_tool_map: dict[str, list[str]] = {
            "researcher": ["calculator"],
            "analyst": ["calculator"],
            "data_analyst": ["calculator"],
            "coder": ["calculator"],
            "writer": [],
            "reviewer": [],
        }

        # Fuzzy match
        for key, tools in role_tool_map.items():
            if key in role:
                return tools

        return ["calculator"]

    @staticmethod
    def _build_system_prompt(sa_task: SubagentTask, tools: list) -> str:
        """Build a focused system prompt for the sub-agent."""
        tool_names = [t.name for t in tools] if tools else []
        tools_desc = f"\n可用工具: {', '.join(tool_names)}" if tool_names else ""

        role_desc = ""
        if sa_task.role_hint:
            role_desc = f"\n你的角色: {sa_task.role_hint}"

        return f"""# 子智能体

你是一个被主智能体动态创建的子智能体，负责完成一项具体任务。
{role_desc}{tools_desc}

## 工作准则

1. 专注于分配给你的任务，不要偏离主题
2. 使用可用工具来完成任务
3. 执行完成后，给出清晰、结构化的最终回答
4. 如果任务无法完成，说明原因并给出建议
5. 回答要简洁有效，避免不必要的冗长

## 当前时间
{datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}"""
