from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.agent_platform.runtime.models import RunContext
from src.agent_platform.spec.models import AgentSpec
from src.agent_platform.types import WorkerKind
from src.agent_platform.workers.registry import WorkerTemplateRegistry

WorkerLifecycle = Literal["static", "dynamic"]
WorkerStatus = Literal["ready", "busy", "completed", "expired"]
WorkerContextScope = Literal["minimal", "thread_summary", "explicit"]


class WorkerBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=6, ge=1)
    timeout_seconds: int = Field(default=300, ge=1)
    max_tokens: int = Field(default=4000, ge=1)


class WorkerMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payload: dict[str, Any]


class WorkerRuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    payload: dict[str, Any]


class RunWorkerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str
    run_id: str
    lifecycle: WorkerLifecycle
    status: WorkerStatus = "ready"
    key: str | None = None
    template_id: str | None = None
    name: str
    kind: WorkerKind
    description: str = ""
    objective: str = ""
    task_brief: str = ""
    context_scope: WorkerContextScope = "minimal"
    budget: WorkerBudget
    tools: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    inbox: list[WorkerMessage] = Field(default_factory=list)


class RunWorkerRegistry:
    def __init__(
        self,
        *,
        run_context: RunContext,
        spec: AgentSpec,
        template_registry: WorkerTemplateRegistry,
        max_worker_timeout_seconds: int = 900,
        max_worker_tokens: int = 12000,
    ):
        self._run_context = run_context
        self._spec = spec
        self._template_registry = template_registry
        self._max_worker_timeout_seconds = max_worker_timeout_seconds
        self._max_worker_tokens = max_worker_tokens
        self._records: dict[str, RunWorkerRecord] = {}
        self._events: list[WorkerRuntimeEvent] = []
        self._register_static_workers()

    def list_workers(self, *, lifecycle: WorkerLifecycle | None = None) -> list[RunWorkerRecord]:
        workers = list(self._records.values())
        if lifecycle is None:
            return workers
        return [worker for worker in workers if worker.lifecycle == lifecycle]

    def get_worker(self, worker_id: str) -> RunWorkerRecord:
        try:
            return self._records[worker_id]
        except KeyError as exc:
            raise KeyError(f"worker 不存在: {worker_id}") from exc

    def drain_events(self) -> list[WorkerRuntimeEvent]:
        events = list(self._events)
        self._events.clear()
        return events

    def spawn_worker(
        self,
        template_id: str,
        *,
        task_brief: str,
        context_scope: WorkerContextScope = "minimal",
        budget: WorkerBudget | dict | None = None,
    ) -> RunWorkerRecord:
        if self._spec.performance_policy.max_dynamic_workers <= 0:
            raise ValueError("当前执行计划未开放动态 worker")

        dynamic_workers = self.list_workers(lifecycle="dynamic")
        if len(dynamic_workers) >= self._spec.performance_policy.max_dynamic_workers:
            raise ValueError("动态 worker 数量已达到上限")

        template = self._template_registry.get(template_id)
        normalized_budget = self._normalize_budget(budget)
        worker_id = f"dynamic_{uuid.uuid4().hex[:12]}"
        record = RunWorkerRecord(
            worker_id=worker_id,
            run_id=self._run_context.run_id,
            lifecycle="dynamic",
            template_id=template.template_id,
            name=template.name,
            kind=template.kind,
            description=template.description,
            objective=template.objective,
            task_brief=str(task_brief or "").strip(),
            context_scope=context_scope,
            budget=normalized_budget,
            tools=list(template.tools),
            mcps=list(template.mcps),
            knowledge_ids=list(template.knowledge_ids),
            skills=list(template.skills),
        )
        self._records[worker_id] = record
        self._events.append(
            WorkerRuntimeEvent(
                event_type="worker.spawn",
                payload={
                    "worker_id": record.worker_id,
                    "template_id": record.template_id,
                    "name": record.name,
                    "context_scope": record.context_scope,
                },
            )
        )
        return record

    def send_to_worker(self, worker_id: str, payload: dict[str, Any]) -> WorkerMessage:
        record = self.get_worker(worker_id)
        message = WorkerMessage(payload=payload)
        record.inbox.append(message)
        self._records[worker_id] = record
        self._events.append(
            WorkerRuntimeEvent(
                event_type="worker.send",
                payload={
                    "worker_id": worker_id,
                    "message_id": message.message_id,
                },
            )
        )
        return message

    def _register_static_workers(self) -> None:
        for worker in self._spec.workers:
            record = RunWorkerRecord(
                worker_id=worker.key,
                run_id=self._run_context.run_id,
                lifecycle="static",
                key=worker.key,
                name=worker.name,
                kind=worker.kind,
                description=worker.description,
                objective=worker.objective,
                task_brief=worker.objective,
                context_scope="thread_summary",
                budget=WorkerBudget(
                    max_steps=self._spec.performance_policy.max_worker_steps,
                    timeout_seconds=self._max_worker_timeout_seconds,
                    max_tokens=self._max_worker_tokens,
                ),
                tools=list(worker.tool_binding.tool_ids),
                mcps=list(worker.mcp_binding.server_names),
                knowledge_ids=list(worker.retrieval.knowledge_ids if worker.retrieval else []),
                skills=list(worker.skills),
            )
            self._records[record.worker_id] = record

    def _normalize_budget(self, budget: WorkerBudget | dict | None) -> WorkerBudget:
        normalized = budget if isinstance(budget, WorkerBudget) else WorkerBudget.model_validate(budget or {})
        if normalized.max_steps > self._spec.performance_policy.max_worker_steps:
            raise ValueError("动态 worker 步骤预算超过限制")
        if normalized.timeout_seconds > self._max_worker_timeout_seconds:
            raise ValueError("动态 worker 超时预算超过限制")
        if normalized.max_tokens > self._max_worker_tokens:
            raise ValueError("动态 worker token 预算超过限制")
        return normalized
