from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.agent_platform.types import ExecutionMode, RetrievalMode, WorkerKind


class ToolBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_ids: list[str] = Field(default_factory=list)


class McpBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_names: list[str] = Field(default_factory=list)


class RetrievalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_ids: list[str] = Field(default_factory=list)
    mode: RetrievalMode = RetrievalMode.HYBRID


class MemoryNamespaceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_preferences: str | None = None
    user_facts: str | None = None
    agent_playbooks: str | None = None


class WorkerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    description: str = ""
    objective: str = ""
    system_prompt: str = ""
    kind: WorkerKind = WorkerKind.REASONING
    model: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    allowed_next: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tool_binding: ToolBindingSpec = Field(default_factory=ToolBindingSpec)
    mcp_binding: McpBindingSpec = Field(default_factory=McpBindingSpec)
    retrieval: RetrievalSpec | None = None
    allow_dynamic_spawn: bool = False


class RoutingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ExecutionMode
    entry_worker: str
    topological_order: list[str] = Field(default_factory=list)


class MemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_term_backend: str = "thread_state"
    long_term_namespace: str | None = None
    namespaces: MemoryNamespaceSpec = Field(default_factory=MemoryNamespaceSpec)


class InterruptPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_required_tools: list[str] = Field(default_factory=list)


class PerformancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_parallel_workers: int = Field(default=1, ge=1)
    max_dynamic_workers: int = Field(default=0, ge=0)
    max_worker_steps: int = Field(default=12, ge=1)


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    name: str
    description: str = ""
    goal: str
    task_scope: str = ""
    execution_mode: ExecutionMode
    system_prompt: str = ""
    supervisor_prompt: str = ""
    product_agent: bool = True
    workers: list[WorkerSpec] = Field(default_factory=list)
    routing_policy: RoutingPolicy
    memory_policy: MemoryPolicy
    interrupt_policy: InterruptPolicy
    performance_policy: PerformancePolicy
    compile_notes: list[str] = Field(default_factory=list)
