import asyncio
import hashlib
import os
import time
from collections import defaultdict, deque
from datetime import timedelta

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select, text
from starlette.middleware.base import BaseHTTPMiddleware

from server.routers import router
from src.storage.postgres.manager import pg_manager
from src.storage.postgres.models_business import LoginRateLimitAttempt
from src.utils.datetime_utils import utc_now_naive
from server.utils.lifespan import lifespan
from server.utils.auth_middleware import is_public_path
from server.utils.common_utils import setup_logging
from server.utils.access_log_middleware import AccessLogMiddleware

# 设置日志配置
setup_logging()


def _read_positive_int_env(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _read_bool_env(var_name: str, default: bool = True) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_rate_limit_endpoints(raw_paths: str) -> set[tuple[str, str]]:
    endpoints: set[tuple[str, str]] = set()
    for path in raw_paths.split(","):
        normalized = (path.strip().rstrip("/") or "/") if path.strip() else ""
        if normalized:
            endpoints.add((normalized, "POST"))
    return endpoints or {("/api/auth/token", "POST")}


RATE_LIMIT_MAX_ATTEMPTS = _read_positive_int_env("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 10)
RATE_LIMIT_WINDOW_SECONDS = _read_positive_int_env("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 60)
RATE_LIMIT_ENDPOINTS = _build_rate_limit_endpoints(os.getenv("LOGIN_RATE_LIMIT_ENDPOINTS", "/api/auth/token"))
RATE_LIMIT_USE_DB = _read_bool_env("LOGIN_RATE_LIMIT_USE_DB", True)
RATE_LIMIT_LOCK_NAMESPACE = os.getenv("LOGIN_RATE_LIMIT_LOCK_NAMESPACE", "rate_limit")

# In-memory login attempt tracker to reduce brute-force exposure per worker
_login_attempts: defaultdict[str, deque[float]] = defaultdict(deque)
_attempt_lock = asyncio.Lock()

app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api")

# CORS 设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _extract_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _advisory_lock_key(resource: str) -> int:
    digest = hashlib.blake2b(resource.encode(), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


async def _reserve_memory_login_attempt(client_ip: str) -> tuple[bool, int]:
    now = time.monotonic()
    async with _attempt_lock:
        attempt_history = _login_attempts[client_ip]
        while attempt_history and now - attempt_history[0] > RATE_LIMIT_WINDOW_SECONDS:
            attempt_history.popleft()
        if len(attempt_history) >= RATE_LIMIT_MAX_ATTEMPTS:
            retry_after = int(max(1, RATE_LIMIT_WINDOW_SECONDS - (now - attempt_history[0])))
            return False, retry_after
        attempt_history.append(now)
    return True, 0


async def _clear_memory_login_attempt(client_ip: str) -> None:
    async with _attempt_lock:
        _login_attempts.pop(client_ip, None)


async def _reserve_db_login_attempt(client_ip: str, endpoint: str) -> tuple[bool, int]:
    lock_key = _advisory_lock_key(f"{RATE_LIMIT_LOCK_NAMESPACE}:{endpoint}:{client_ip}")
    now = utc_now_naive()
    cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
    async with pg_manager.get_async_session_context() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
        await session.execute(
            delete(LoginRateLimitAttempt).where(
                LoginRateLimitAttempt.client_ip == client_ip,
                LoginRateLimitAttempt.endpoint == endpoint,
                LoginRateLimitAttempt.attempted_at < cutoff,
            )
        )
        count_result = await session.execute(
            select(func.count(LoginRateLimitAttempt.id)).where(
                LoginRateLimitAttempt.client_ip == client_ip,
                LoginRateLimitAttempt.endpoint == endpoint,
            )
        )
        current_attempts = int(count_result.scalar() or 0)
        if current_attempts >= RATE_LIMIT_MAX_ATTEMPTS:
            oldest_result = await session.execute(
                select(func.min(LoginRateLimitAttempt.attempted_at)).where(
                    LoginRateLimitAttempt.client_ip == client_ip,
                    LoginRateLimitAttempt.endpoint == endpoint,
                )
            )
            oldest_attempt = oldest_result.scalar()
            retry_after = RATE_LIMIT_WINDOW_SECONDS
            if oldest_attempt is not None:
                elapsed = (now - oldest_attempt).total_seconds()
                retry_after = int(max(1, RATE_LIMIT_WINDOW_SECONDS - elapsed))
            return False, retry_after
        session.add(LoginRateLimitAttempt(client_ip=client_ip, endpoint=endpoint))
    return True, 0


async def _clear_db_login_attempt(client_ip: str, endpoint: str) -> None:
    async with pg_manager.get_async_session_context() as session:
        await session.execute(
            delete(LoginRateLimitAttempt).where(
                LoginRateLimitAttempt.client_ip == client_ip,
                LoginRateLimitAttempt.endpoint == endpoint,
            )
        )


class LoginRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        normalized_path = request.url.path.rstrip("/") or "/"
        request_signature = (normalized_path, request.method.upper())

        if request_signature in RATE_LIMIT_ENDPOINTS:
            client_ip = _extract_client_ip(request)
            endpoint = normalized_path
            if RATE_LIMIT_USE_DB and pg_manager.is_postgresql:
                allowed, retry_after = await _reserve_db_login_attempt(client_ip, endpoint)
            else:
                allowed, retry_after = await _reserve_memory_login_attempt(client_ip)
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "登录尝试过于频繁，请稍后再试"},
                    headers={"Retry-After": str(retry_after)},
                )

            response = await call_next(request)

            if response.status_code < 400:
                if RATE_LIMIT_USE_DB and pg_manager.is_postgresql:
                    await _clear_db_login_attempt(client_ip, endpoint)
                else:
                    await _clear_memory_login_attempt(client_ip)

            return response

        return await call_next(request)


# 鉴权中间件
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 获取请求路径
        path = request.url.path

        # 检查是否为公开路径，公开路径无需身份验证
        if is_public_path(path):
            return await call_next(request)

        if not path.startswith("/api"):
            # 非API路径，可能是前端路由或静态资源
            return await call_next(request)

        # # 提取Authorization头
        # auth_header = request.headers.get("Authorization")
        # if not auth_header or not auth_header.startswith("Bearer "):
        #     return JSONResponse(
        #         status_code=status.HTTP_401_UNAUTHORIZED,
        #         content={"detail": f"请先登录。Path: {path}"},
        #         headers={"WWW-Authenticate": "Bearer"}
        #     )

        # # 获取token
        # token = auth_header.split("Bearer ")[1]

        # # 添加token到请求状态，后续路由可以直接使用
        # request.state.token = token

        # 继续处理请求
        return await call_next(request)


# 添加访问日志中间件（记录请求处理时间）
app.add_middleware(AccessLogMiddleware)

# 添加鉴权中间件
app.add_middleware(LoginRateLimitMiddleware)
app.add_middleware(AuthMiddleware)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050, workers=10, reload=True)
