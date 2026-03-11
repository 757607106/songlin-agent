from __future__ import annotations

import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YUXI_SKIP_APP_INIT", "1")

from server.routers.chat_router import (  # noqa: E402
    AGENT_PLATFORM_AGENT_ID,
    _ensure_supported_agent_config,
    _is_agent_platform_config_json,
    _supports_agent_config_record,
)


def test_agent_platform_config_contract_accepts_only_v2():
    assert _is_agent_platform_config_json({"version": "agent_platform_v2"}) is True
    assert _is_agent_platform_config_json({"version": "legacy"}) is False
    assert _is_agent_platform_config_json({"context": {}}) is False
    assert _is_agent_platform_config_json(None) is False

    assert _supports_agent_config_record(AGENT_PLATFORM_AGENT_ID, {"version": "agent_platform_v2"}) is True
    assert _supports_agent_config_record(AGENT_PLATFORM_AGENT_ID, {"context": {}}) is False
    assert _supports_agent_config_record("SqlReporterAgent", {"context": {}}) is True


def test_agent_platform_config_contract_rejects_legacy_payload():
    with pytest.raises(HTTPException) as exc_info:
        _ensure_supported_agent_config(AGENT_PLATFORM_AGENT_ID, {"context": {"multi_agent_mode": "supervisor"}})

    assert exc_info.value.status_code == 422
