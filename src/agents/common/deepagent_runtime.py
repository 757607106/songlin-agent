from __future__ import annotations

import os
from typing import Any

from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from src.agents.common.middlewares import (
    RuntimeConfigMiddleware,
    create_summary_offload_middleware,
    save_attachments_to_fs,
)

_SUMMARY_ENABLED = os.getenv("AGENT_SUMMARY_ENABLED", "1") == "1"


def _safe_int_env(name: str, default: int, *, minimum: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(minimum, int(value))
    except Exception:
        return default


_SUMMARY_TRIGGER_TOKENS = _safe_int_env("AGENT_SUMMARY_TRIGGER_TOKENS", 24000, minimum=1024)
_SUMMARY_KEEP_MESSAGES = _safe_int_env("AGENT_SUMMARY_KEEP_MESSAGES", 20, minimum=5)
_SUMMARY_OFFLOAD_THRESHOLD = _safe_int_env("AGENT_SUMMARY_OFFLOAD_THRESHOLD", 1000, minimum=200)


def create_state_store_backend(runtime: Any) -> CompositeBackend:
    """DeepAgents backend: state + long-term store routes."""
    return CompositeBackend(
        default=StateBackend(runtime),
        routes={
            "/memories/": StoreBackend(runtime),
            "/preferences/": StoreBackend(runtime),
        },
    )


def create_main_middlewares(*, model: Any, mcp_tools: list[Any]) -> list[Any]:
    """Build middlewares for top-level deep agent graphs."""
    middlewares: list[Any] = [RuntimeConfigMiddleware(extra_tools=mcp_tools)]
    if _SUMMARY_ENABLED:
        middlewares.append(
            create_summary_offload_middleware(
                model=model,
                trigger=("tokens", _SUMMARY_TRIGGER_TOKENS),
                keep=("messages", _SUMMARY_KEEP_MESSAGES),
                summary_offload_threshold=_SUMMARY_OFFLOAD_THRESHOLD,
            )
        )
    middlewares.append(save_attachments_to_fs)
    return middlewares


def create_subagent_middlewares(*, model: Any | None = None, mcp_tools: list[Any]) -> list[Any]:
    """Build middlewares for deep-agent subagents."""
    middlewares: list[Any] = [
        RuntimeConfigMiddleware(
            extra_tools=mcp_tools,
            enable_model_override=False,
            enable_system_prompt_override=False,
            enable_tools_override=True,
        )
    ]
    if _SUMMARY_ENABLED and model is not None:
        middlewares.append(
            create_summary_offload_middleware(
                model=model,
                trigger=("tokens", _SUMMARY_TRIGGER_TOKENS),
                keep=("messages", _SUMMARY_KEEP_MESSAGES),
                summary_offload_threshold=_SUMMARY_OFFLOAD_THRESHOLD,
            )
        )
    return middlewares
