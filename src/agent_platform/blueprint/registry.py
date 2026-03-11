from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.agent_platform.blueprint.models import AgentBlueprint


class BlueprintTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    name: str
    category: str = "general"
    description: str = ""
    prompt_hints: list[str] = Field(default_factory=list)
    blueprint: AgentBlueprint


class BlueprintTemplateRegistry:
    def __init__(self, templates: list[BlueprintTemplate] | None = None):
        self._templates: dict[str, BlueprintTemplate] = {}
        for template in templates or []:
            self.register(template)

    def register(self, template: BlueprintTemplate) -> None:
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> BlueprintTemplate:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise KeyError(f"未注册的 blueprint template: {template_id}") from exc

    def list(self) -> list[BlueprintTemplate]:
        return list(self._templates.values())
