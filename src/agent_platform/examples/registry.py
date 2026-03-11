from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.agent_platform.blueprint.models import AgentBlueprint
from src.agent_platform.spec.models import AgentSpec


class AgentExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_id: str
    name: str
    category: str = "general"
    description: str = ""
    sample_prompts: list[str] = Field(default_factory=list)
    blueprint: AgentBlueprint
    spec: AgentSpec


class AgentExampleRegistry:
    def __init__(self, examples: list[AgentExample] | None = None):
        self._examples: dict[str, AgentExample] = {}
        for example in examples or []:
            self.register(example)

    def register(self, example: AgentExample) -> None:
        self._examples[example.example_id] = example

    def get(self, example_id: str) -> AgentExample:
        try:
            return self._examples[example_id]
        except KeyError as exc:
            raise KeyError(f"未注册的 agent example: {example_id}") from exc

    def list(self) -> list[AgentExample]:
        return list(self._examples.values())
