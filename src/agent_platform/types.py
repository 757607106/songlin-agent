from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum


class ExecutionMode(StrEnum):
    SINGLE = "single"
    SUPERVISOR = "supervisor"
    DEEP_AGENTS = "deep_agents"
    SWARM_HANDOFF = "swarm_handoff"


class WorkerKind(StrEnum):
    REASONING = "reasoning"
    TOOL = "tool"
    RETRIEVAL = "retrieval"


class RetrievalMode(StrEnum):
    LOCAL = "local"
    GLOBAL = "global"
    HYBRID = "hybrid"
    MIX = "mix"


def dedupe_strings(values: Iterable[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        items.append(value)
        seen.add(value)
    return items


def slugify_name(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or fallback
