from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agent_platform.types import ExecutionMode, RetrievalMode, WorkerKind, dedupe_strings, slugify_name


class BlueprintWorker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    name: str = Field(min_length=1)
    description: str = ""
    objective: str = ""
    system_prompt: str = ""
    kind: WorkerKind = WorkerKind.REASONING
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    allowed_next: list[str] = Field(default_factory=list)
    allow_dynamic_spawn: bool = False

    @model_validator(mode="after")
    def normalize(self) -> BlueprintWorker:
        self.key = slugify_name(self.key or self.name, fallback="worker")
        self.tools = dedupe_strings(self.tools)
        self.mcps = dedupe_strings(self.mcps)
        self.knowledge_ids = dedupe_strings(self.knowledge_ids)
        self.skills = dedupe_strings(self.skills)
        self.depends_on = dedupe_strings(self.depends_on)
        self.allowed_next = dedupe_strings(self.allowed_next)
        return self


class AgentBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    goal: str = Field(min_length=1)
    task_scope: str = ""
    execution_mode: ExecutionMode = ExecutionMode.SINGLE
    system_prompt: str = ""
    supervisor_prompt: str = ""
    default_model: str | None = None
    product_agent: bool = True
    tools: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID
    long_term_memory_namespace: str | None = None
    interrupt_on_tools: list[str] = Field(default_factory=list)
    max_parallel_workers: int = Field(default=1, ge=1)
    max_dynamic_workers: int = Field(default=0, ge=0)
    max_worker_steps: int = Field(default=12, ge=1)
    workers: list[BlueprintWorker] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> AgentBlueprint:
        self.tools = dedupe_strings(self.tools)
        self.mcps = dedupe_strings(self.mcps)
        self.knowledge_ids = dedupe_strings(self.knowledge_ids)
        self.skills = dedupe_strings(self.skills)
        self.interrupt_on_tools = dedupe_strings(self.interrupt_on_tools)
        self.tags = dedupe_strings(self.tags)
        if self.execution_mode is ExecutionMode.SINGLE:
            self.max_parallel_workers = 1
        return self


class BlueprintValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    dependency_order: list[str] = Field(default_factory=list)
    normalized_blueprint: AgentBlueprint
