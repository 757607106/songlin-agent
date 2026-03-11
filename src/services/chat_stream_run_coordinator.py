from __future__ import annotations

import asyncio
import hashlib
import os
import traceback
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src import knowledge_base
from src.agent_platform.constants import AGENT_PLATFORM_AGENT_ID
from src.agent_platform.runtime.adapter import build_dynamic_context_from_platform_config
from src.agents import agent_manager
from src.repositories.agent_config_repository import AgentConfigRepository
from src.storage.postgres.manager import pg_manager
from src.utils.logging_config import logger

THREAD_DISTRIBUTED_LOCK_ENABLED = os.getenv("THREAD_DISTRIBUTED_LOCK_ENABLED", "1") == "1"
THREAD_DISTRIBUTED_LOCK_NAMESPACE = os.getenv("THREAD_DISTRIBUTED_LOCK_NAMESPACE", "thread_stream")
_thread_stream_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class ThreadBusyError(RuntimeError):
    pass


class MissingDepartmentError(RuntimeError):
    pass


@dataclass(slots=True)
class PreparedAgentRun:
    agent: object
    user_id: str
    department_id: int
    thread_id: str
    agent_config_id: int | None
    agent_config: dict
    team_execution_mode: str
    runtime_audit: dict
    input_context: dict
    graph_kwargs: dict
    excluded_ai_names: set[str]
    context: object | None = None


def resolve_agent_config_context(config_item) -> dict:
    raw = config_item.config_json or {}
    if isinstance(raw, dict):
        context = raw.get("context", raw)
        if isinstance(context, dict):
            return context
    return {}


def resolve_runtime_agent_config(agent_id: str, config_item) -> dict:
    if agent_id == AGENT_PLATFORM_AGENT_ID:
        raw = config_item.config_json or {}
        if isinstance(raw, dict):
            return build_dynamic_context_from_platform_config(raw)
        return {}
    return resolve_agent_config_context(config_item)


def resolve_execution_mode(agent_id: str, config_item) -> str:
    if agent_id == AGENT_PLATFORM_AGENT_ID:
        raw = config_item.config_json or {}
        spec = raw.get("spec") if isinstance(raw, dict) else None
        if isinstance(spec, dict):
            return str(spec.get("execution_mode") or "single")
        return "single"
    context = resolve_agent_config_context(config_item)
    return str(context.get("multi_agent_mode") or "disabled")


def build_dynamic_graph_kwargs(agent, input_context: dict | None) -> dict | None:
    try:
        context = agent._build_runtime_context(input_context)
    except Exception as exc:
        logger.warning(f"Failed to build dynamic runtime context: {exc}")
        return None

    return {
        "model": context.model,
        "system_prompt": context.system_prompt,
        "multi_agent_mode": context.multi_agent_mode,
        "team_goal": context.team_goal,
        "task_scope": context.task_scope,
        "communication_protocol": context.communication_protocol,
        "max_parallel_tasks": context.max_parallel_tasks,
        "allow_cross_agent_comm": context.allow_cross_agent_comm,
        "subagents": context.subagents,
        "supervisor_system_prompt": context.supervisor_system_prompt,
        "tools": context.tools,
        "knowledges": context.knowledges,
        "mcps": context.mcps,
    }


async def apply_accessible_knowledge_scope(
    agent_config: dict,
    *,
    user_id: str,
    department_id: int,
) -> None:
    if not isinstance(agent_config, dict):
        return

    requested_knowledge_names = agent_config.get("knowledges")
    requested_subagents = agent_config.get("subagents") or []
    need_kb_filter = bool(requested_knowledge_names) or any(
        isinstance(sa, dict) and sa.get("knowledges") for sa in requested_subagents
    )
    if not need_kb_filter:
        return

    logger.info(f"Requesting knowledges: {requested_knowledge_names}")
    user_info = {"role": "user", "department_id": department_id}
    accessible_databases = await knowledge_base.get_databases_by_user(user_info)
    accessible_kb_names = {
        db.get("name")
        for db in accessible_databases.get("databases", [])
        if isinstance(db, dict) and db.get("name")
    }
    logger.info(f"Accessible knowledges: {accessible_kb_names}")

    if requested_knowledge_names and isinstance(requested_knowledge_names, list):
        filtered_knowledge_names = [kb for kb in requested_knowledge_names if kb in accessible_kb_names]
        blocked_knowledge_names = [kb for kb in requested_knowledge_names if kb not in accessible_kb_names]
        if blocked_knowledge_names:
            logger.warning(f"用户 {user_id} 无权访问知识库: {blocked_knowledge_names}, 已自动过滤")
        agent_config["knowledges"] = filtered_knowledge_names

    if isinstance(requested_subagents, list):
        for sa in requested_subagents:
            if not isinstance(sa, dict):
                continue
            sa_knowledges = sa.get("knowledges")
            if not sa_knowledges or not isinstance(sa_knowledges, list):
                continue
            filtered_sa_knowledges = [kb for kb in sa_knowledges if kb in accessible_kb_names]
            blocked_sa_knowledges = [kb for kb in sa_knowledges if kb not in accessible_kb_names]
            if blocked_sa_knowledges:
                blocked_text = ", ".join(blocked_sa_knowledges)
                logger.warning(f"用户 {user_id} 子Agent `{sa.get('name')}` 无权访问知识库: {blocked_text}, 已自动过滤")
            sa["knowledges"] = filtered_sa_knowledges


def _advisory_lock_key(namespace: str, resource_id: str) -> int:
    digest = hashlib.blake2b(f"{namespace}:{resource_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


async def _try_acquire_distributed_thread_lock(thread_id: str) -> tuple[AsyncSession | None, bool]:
    if not THREAD_DISTRIBUTED_LOCK_ENABLED or not pg_manager.is_postgresql:
        return None, True
    lock_session = await pg_manager.get_async_session()
    lock_key = _advisory_lock_key(THREAD_DISTRIBUTED_LOCK_NAMESPACE, thread_id)
    try:
        result = await lock_session.execute(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key})
        acquired = bool(result.scalar())
        if not acquired:
            await lock_session.close()
            return None, False
        return lock_session, True
    except Exception as exc:
        logger.warning(f"Failed to acquire distributed lock for thread {thread_id}: {exc}")
        await lock_session.close()
        return None, True


async def _release_distributed_thread_lock(lock_session: AsyncSession | None, thread_id: str) -> None:
    if lock_session is None:
        return
    lock_key = _advisory_lock_key(THREAD_DISTRIBUTED_LOCK_NAMESPACE, thread_id)
    try:
        await lock_session.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})
    except Exception as exc:
        logger.warning(f"Failed to release distributed lock for thread {thread_id}: {exc}")
    finally:
        await lock_session.close()


@asynccontextmanager
async def reserve_thread_slot(thread_id: str):
    thread_lock = _thread_stream_locks[thread_id]
    if thread_lock.locked():
        raise ThreadBusyError(thread_id)

    await thread_lock.acquire()
    distributed_lock_session = None
    try:
        distributed_lock_session, distributed_lock_acquired = await _try_acquire_distributed_thread_lock(thread_id)
        if not distributed_lock_acquired:
            raise ThreadBusyError(thread_id)
        yield
    finally:
        await _release_distributed_thread_lock(distributed_lock_session, thread_id)
        if thread_lock.locked():
            thread_lock.release()


class RunCoordinator:
    def __init__(self, db):
        self.db = db

    async def prepare_chat_run(
        self,
        *,
        agent_id: str,
        config: dict,
        current_user,
    ) -> PreparedAgentRun:
        thread_id = str((config or {}).get("thread_id") or "").strip()
        if not thread_id:
            thread_id = str(uuid.uuid4())
            logger.warning(f"No thread_id provided, generated new thread_id: {thread_id}")
        return await self._prepare_run(
            agent_id=agent_id,
            config=config,
            current_user=current_user,
            thread_id=thread_id,
            include_runtime_context=False,
        )

    async def prepare_resume_run(
        self,
        *,
        agent_id: str,
        thread_id: str,
        config: dict,
        current_user,
    ) -> PreparedAgentRun:
        return await self._prepare_run(
            agent_id=agent_id,
            config=config,
            current_user=current_user,
            thread_id=thread_id,
            include_runtime_context=True,
        )

    async def _prepare_run(
        self,
        *,
        agent_id: str,
        config: dict,
        current_user,
        thread_id: str,
        include_runtime_context: bool,
    ) -> PreparedAgentRun:
        agent = agent_manager.get_agent(agent_id)
        user_id = str(current_user.id)
        department_id = current_user.department_id
        if not department_id:
            raise MissingDepartmentError("当前用户未绑定部门")

        config_repo = AgentConfigRepository(self.db)
        config_item = None
        agent_config_id = (config or {}).get("agent_config_id")
        if agent_config_id is not None:
            try:
                config_item = await config_repo.get_by_id(int(agent_config_id))
            except Exception:
                logger.warning(f"Failed to fetch agent config {agent_config_id}: {traceback.format_exc()}")
                config_item = None
            if config_item is not None and (
                config_item.department_id != department_id or config_item.agent_id != agent_id
            ):
                config_item = None

        if config_item is None:
            config_item = await config_repo.get_or_create_default(
                department_id=department_id, agent_id=agent_id, created_by=user_id
            )
            agent_config_id = config_item.id

        agent_config = resolve_runtime_agent_config(agent_id, config_item)
        team_execution_mode = resolve_execution_mode(agent_id, config_item)
        team_policy = agent_config.get("team_policy") if isinstance(agent_config, dict) else {}
        runtime_audit = (team_policy or {}).get("runtime_audit") if isinstance(team_policy, dict) else {}
        input_context = {
            "user_id": user_id,
            "thread_id": thread_id,
            "department_id": department_id,
            "agent_config_id": agent_config_id,
            "agent_config": agent_config,
        }
        await apply_accessible_knowledge_scope(
            agent_config,
            user_id=user_id,
            department_id=department_id,
        )
        dynamic_graph_kwargs = (
            build_dynamic_graph_kwargs(agent, input_context)
            if agent_id == AGENT_PLATFORM_AGENT_ID
            else None
        )
        graph_kwargs = (
            dynamic_graph_kwargs
            if dynamic_graph_kwargs is not None
            else {"user_id": user_id, "department_id": department_id}
        )
        context = agent._build_runtime_context(input_context) if include_runtime_context else None
        excluded_ai_names = {
            str(sa.get("name")).strip()
            for sa in (agent_config.get("subagents") or [])
            if isinstance(sa, dict) and str(sa.get("name") or "").strip()
        }
        return PreparedAgentRun(
            agent=agent,
            user_id=user_id,
            department_id=department_id,
            thread_id=thread_id,
            agent_config_id=agent_config_id,
            agent_config=agent_config,
            team_execution_mode=team_execution_mode,
            runtime_audit=runtime_audit if isinstance(runtime_audit, dict) else {},
            input_context=input_context,
            graph_kwargs=graph_kwargs,
            excluded_ai_names=excluded_ai_names,
            context=context,
        )
