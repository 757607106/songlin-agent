from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.agent_platform.types import WorkerKind


class WorkerTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    name: str
    kind: WorkerKind
    description: str = ""
    objective: str = ""
    tools: list[str] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class WorkerTemplateRegistry:
    def __init__(self, templates: list[WorkerTemplate] | None = None):
        self._templates: dict[str, WorkerTemplate] = {}
        for template in templates or []:
            self.register(template)

    def register(self, template: WorkerTemplate) -> None:
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> WorkerTemplate:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise KeyError(f"未注册的 worker template: {template_id}") from exc

    def list(self) -> list[WorkerTemplate]:
        return list(self._templates.values())
