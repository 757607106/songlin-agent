from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.agent_platform.runtime.models import RunContext
from src.agent_platform.spec.models import AgentSpec, MemoryNamespaceSpec


class ResolvedMemoryNamespaces(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_preferences: str | None = None
    user_facts: str | None = None
    agent_playbooks: str | None = None


def resolve_memory_namespaces(spec: AgentSpec, run_context: RunContext) -> ResolvedMemoryNamespaces:
    namespaces = spec.memory_policy.namespaces
    user_id = _sanitize_namespace_segment(run_context.user_id)
    return ResolvedMemoryNamespaces(
        user_preferences=_resolve_template(namespaces.user_preferences, user_id=user_id),
        user_facts=_resolve_template(namespaces.user_facts, user_id=user_id),
        agent_playbooks=_resolve_template(namespaces.agent_playbooks, user_id=user_id),
    )


def memory_namespaces_to_context_payload(namespaces: MemoryNamespaceSpec) -> dict[str, str]:
    payload: dict[str, str] = {}
    if namespaces.user_preferences:
        payload["user_preferences"] = namespaces.user_preferences
    if namespaces.user_facts:
        payload["user_facts"] = namespaces.user_facts
    if namespaces.agent_playbooks:
        payload["agent_playbooks"] = namespaces.agent_playbooks
    return payload


def _resolve_template(template: str | None, *, user_id: str) -> str | None:
    if not template:
        return None
    return template.format(user_id=user_id)


def _sanitize_namespace_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "anonymous"
    return text.replace("/", "-")
