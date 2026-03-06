from __future__ import annotations

import sys
import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

main = importlib.import_module("server.main")


def test_read_positive_int_env(monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "0")
    assert main._read_positive_int_env("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 10) == 1
    monkeypatch.setenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "25")
    assert main._read_positive_int_env("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 10) == 25
    monkeypatch.setenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "invalid")
    assert main._read_positive_int_env("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 10) == 10


def test_build_rate_limit_endpoints():
    endpoints = main._build_rate_limit_endpoints("/api/auth/token,/api/auth/refresh/")
    assert ("/api/auth/token", "POST") in endpoints
    assert ("/api/auth/refresh", "POST") in endpoints
    assert main._build_rate_limit_endpoints(" , ") == {("/api/auth/token", "POST")}


@pytest.mark.asyncio
async def test_memory_rate_limit_reserve_and_clear(monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(main, "RATE_LIMIT_WINDOW_SECONDS", 60)
    main._login_attempts.clear()

    allowed_1, retry_1 = await main._reserve_memory_login_attempt("127.0.0.1")
    allowed_2, retry_2 = await main._reserve_memory_login_attempt("127.0.0.1")
    allowed_3, retry_3 = await main._reserve_memory_login_attempt("127.0.0.1")

    assert allowed_1 is True and retry_1 == 0
    assert allowed_2 is True and retry_2 == 0
    assert allowed_3 is False and retry_3 >= 1

    await main._clear_memory_login_attempt("127.0.0.1")
    allowed_4, retry_4 = await main._reserve_memory_login_attempt("127.0.0.1")
    assert allowed_4 is True and retry_4 == 0
