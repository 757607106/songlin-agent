import asyncio
import contextlib
import hashlib
import json
import os
import traceback
import uuid
from copy import deepcopy
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import datetime

from langchain.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.types import Command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src import config as conf
from src import knowledge_base
from src.agents import agent_manager
from src.plugins.guard import content_guard
from src.repositories.agent_config_repository import AgentConfigRepository
from src.repositories.conversation_repository import ConversationRepository
from src.services.runtime_service import runtime_service
from src.storage.postgres.manager import pg_manager
from src.utils.logging_config import logger

RUNTIME_STATUS_IDLE = "idle"
RUNTIME_STATUS_RUNNING = "running"
RUNTIME_STATUS_WAITING_FOR_HUMAN = "waiting_for_human"
RUNTIME_STATUS_COMPLETED = "completed"
RUNTIME_STATUS_ERROR = "error"
_thread_stream_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
THREAD_DISTRIBUTED_LOCK_ENABLED = os.getenv("THREAD_DISTRIBUTED_LOCK_ENABLED", "1") == "1"
THREAD_DISTRIBUTED_LOCK_NAMESPACE = os.getenv("THREAD_DISTRIBUTED_LOCK_NAMESPACE", "thread_stream")
AGENT_STREAM_NEXT_TIMEOUT_SECONDS = max(5, int(os.getenv("AGENT_STREAM_NEXT_TIMEOUT_SECONDS", "180")))
AGENT_STATE_VIEW_CACHE_TTL_SECONDS = max(0.2, float(os.getenv("AGENT_STATE_VIEW_CACHE_TTL_SECONDS", "1.5")))
_agent_state_view_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}
_agent_state_view_inflight: dict[tuple[str, str, str], asyncio.Task] = {}
_agent_state_view_lock: asyncio.Lock | None = None


def _get_agent_state_view_lock() -> asyncio.Lock:
    global _agent_state_view_lock
    if _agent_state_view_lock is None:
        _agent_state_view_lock = asyncio.Lock()
    return _agent_state_view_lock


def _extract_run_id(meta: dict | None) -> str | None:
    if not isinstance(meta, dict):
        return None
    run_id = meta.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    return None


async def _runtime_append_event(
    *,
    meta: dict | None,
    event_type: str,
    actor_type: str,
    actor_name: str,
    payload: dict | None = None,
) -> None:
    run_id = _extract_run_id(meta)
    if not run_id:
        return
    try:
        await runtime_service.append_event(
            run_id=run_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_name=actor_name,
            payload=payload or {},
        )
    except Exception as exc:
        logger.debug(f"Skip runtime event `{event_type}` for run `{run_id}`: {exc}")


async def _runtime_transition(
    *,
    meta: dict | None,
    next_status: str,
    actor_type: str,
    actor_name: str,
    reason: str | None = None,
) -> None:
    run_id = _extract_run_id(meta)
    if not run_id:
        return
    try:
        result = await runtime_service.transition_status(
            run_id=run_id,
            next_status=next_status,
            actor_type=actor_type,
            actor_name=actor_name,
            reason=reason,
        )
        if isinstance(result, dict) and result.get("error"):
            logger.debug(f"Skip runtime transition `{next_status}` for run `{run_id}`: {result['error']}")
    except Exception as exc:
        logger.debug(f"Skip runtime transition `{next_status}` for run `{run_id}`: {exc}")


async def _iterate_with_next_timeout(stream_source, timeout_seconds: int):
    pending_next = asyncio.create_task(stream_source.__anext__())
    timeout_count = 0
    try:
        while True:
            done, _ = await asyncio.wait({pending_next}, timeout=timeout_seconds)
            if not done:
                timeout_count += 1
                if timeout_count == 1 or timeout_count % 5 == 0:
                    logger.warning(
                        f"No new stream chunk for {timeout_seconds}s (x{timeout_count}); "
                        "still waiting for upstream stream source."
                    )
                continue

            timeout_count = 0
            try:
                next_item = pending_next.result()
            except StopAsyncIteration:
                break
            pending_next = asyncio.create_task(stream_source.__anext__())
            yield next_item
    finally:
        if not pending_next.done():
            pending_next.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending_next


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


def _runtime_status_metadata(
    status: str,
    *,
    has_interrupt: bool = False,
    error_message: str | None = None,
) -> dict:
    metadata = {
        "runtime_status": status,
        "status_updated_at": datetime.utcnow().isoformat() + "+00:00",
        "has_interrupt": has_interrupt,
    }
    if error_message:
        metadata["last_error_message"] = str(error_message)[:1000]
    elif status in (RUNTIME_STATUS_RUNNING, RUNTIME_STATUS_COMPLETED, RUNTIME_STATUS_IDLE):
        metadata["last_error_message"] = ""
    return metadata


async def update_thread_runtime_status(
    conv_repo: ConversationRepository,
    thread_id: str,
    status: str,
    *,
    has_interrupt: bool = False,
    error_message: str | None = None,
    extra_metadata: dict | None = None,
) -> None:
    metadata = _runtime_status_metadata(
        status,
        has_interrupt=has_interrupt,
        error_message=error_message,
    )
    if extra_metadata:
        metadata.update(extra_metadata)
    await conv_repo.update_conversation(
        thread_id=thread_id,
        metadata=metadata,
    )


def _resolve_agent_config_context(config_item) -> dict:
    raw = config_item.config_json or {}
    if isinstance(raw, dict):
        context = raw.get("context", raw)
        if isinstance(context, dict):
            return context
    return {}


def _build_dynamic_graph_kwargs(agent, input_context: dict | None) -> dict | None:
    """Build DynamicAgent get_graph kwargs from runtime context."""
    try:
        context = agent._build_runtime_context(input_context)
    except Exception as e:
        logger.warning(f"Failed to build dynamic runtime context: {e}")
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


def _build_state_files(attachments: list[dict]) -> dict:
    """将附件列表转换为 StateBackend 格式的 files 字典

    StateBackend 期望的格式:
    {
        "/attachments/file.md": {
            "content": ["line1", "line2", ...],
            "created_at": "...",
            "modified_at": "...",
        }
    }
    """
    files = {}
    for attachment in attachments:
        if attachment.get("status") != "parsed":
            continue

        file_path = attachment.get("file_path")
        markdown = attachment.get("markdown")

        if not file_path or not markdown:
            continue

        now = datetime.utcnow().isoformat() + "+00:00"
        # 将 markdown 内容按行拆分
        content_lines = markdown.split("\n")
        files[file_path] = {
            "content": content_lines,
            "created_at": attachment.get("uploaded_at", now),
            "modified_at": attachment.get("uploaded_at", now),
        }

    return files


async def _get_langgraph_messages(config_dict, graph):
    state = await graph.aget_state(config_dict)

    if not state or not state.values:
        logger.warning("No state found in LangGraph")
        return None

    return state.values.get("messages", [])


def extract_agent_state(values: dict, *, include_attachment_content: bool = False) -> dict:
    """从 LangGraph state 中提取 agent 状态"""
    if not isinstance(values, dict):
        return {}

    todos = values.get("todos")
    files = values.get("files") or {}
    if isinstance(files, dict):
        optimized_files = {}
        for path, file_data in files.items():
            if not isinstance(path, str) or not isinstance(file_data, dict):
                continue
            if include_attachment_content or not path.startswith("/attachments/"):
                optimized_files[path] = file_data
                continue
            line_count = len(file_data.get("content", [])) if isinstance(file_data.get("content"), list) else 0
            optimized_files[path] = {
                "created_at": file_data.get("created_at"),
                "modified_at": file_data.get("modified_at"),
                "line_count": line_count,
                "truncated": True,
            }
        files = optimized_files
    else:
        files = {}

    result = {
        "todos": list(todos)[:20] if todos else [],
        "files": files,
        "execution_log": list(values.get("execution_log") or [])[-50:],
        "route_history": list(values.get("route_history") or [])[-50:],
        "completed_agents": list(values.get("completed_agents") or []),
        "retry_counts": dict(values.get("retry_counts") or {}),
        "active_agent": values.get("active_agent"),
    }

    return result


def _collect_supervisor_execution_entries(update_event: dict) -> list[dict]:
    """Extract supervisor execution_log entries from a state_update event."""
    if not isinstance(update_event, dict):
        return []
    data = update_event.get("data")
    if not isinstance(data, dict):
        return []

    entries: list[dict] = []
    for node_payload in data.values():
        if not isinstance(node_payload, dict):
            continue
        execution_log = node_payload.get("execution_log")
        if not isinstance(execution_log, list):
            continue
        for entry in execution_log:
            if isinstance(entry, dict) and entry.get("type"):
                entries.append(entry)
    return entries


def _supervisor_entry_fingerprint(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)


def _map_supervisor_entry_to_runtime_event(entry_type: str) -> str:
    mapping = {
        "route": "supervisor.route",
        "communication_gate": "supervisor.handoff_blocked",
        "dependency_gate": "supervisor.dependency_blocked",
        "retry_guard_finish": "supervisor.retry_exhausted",
        "eligible_targets_empty_finish": "supervisor.no_eligible_target",
        "guard_finish": "supervisor.guard_finish",
        "global_timeout": "supervisor.global_timeout",
        "agent_failure": "subagent.failed",
        "finish": "supervisor.finish",
    }
    return mapping.get(entry_type, "supervisor.event")


async def _get_existing_message_ids(conv_repo: ConversationRepository, thread_id: str) -> set[str]:
    existing_messages = await conv_repo.get_messages_by_thread_id(thread_id)
    return {
        msg.extra_metadata["id"]
        for msg in existing_messages
        if msg.extra_metadata and "id" in msg.extra_metadata and isinstance(msg.extra_metadata["id"], str)
    }


async def _save_ai_message(conv_repo: ConversationRepository, thread_id: str, msg_dict: dict) -> None:
    content = msg_dict.get("content", "")
    tool_calls_data = msg_dict.get("tool_calls", [])

    ai_msg = await conv_repo.add_message_by_thread_id(
        thread_id=thread_id,
        role="assistant",
        content=content,
        message_type="text",
        extra_metadata=msg_dict,
    )

    if ai_msg and tool_calls_data:
        for tc in tool_calls_data:
            await conv_repo.add_tool_call(
                message_id=ai_msg.id,
                tool_name=tc.get("name", "unknown"),
                tool_input=tc.get("args", {}),
                status="pending",
                langgraph_tool_call_id=tc.get("id"),
            )


async def _save_tool_message(conv_repo: ConversationRepository, msg_dict: dict) -> None:
    tool_call_id = msg_dict.get("tool_call_id")
    content = msg_dict.get("content", "")

    if not tool_call_id:
        return

    if isinstance(content, list):
        tool_output = json.dumps(content) if content else ""
    else:
        tool_output = str(content)

    await conv_repo.update_tool_call_output(
        langgraph_tool_call_id=tool_call_id,
        tool_output=tool_output,
        status="success",
    )


async def save_partial_message(
    conv_repo: ConversationRepository,
    thread_id: str,
    full_msg=None,
    error_message: str | None = None,
    error_type: str = "interrupted",
):
    try:
        extra_metadata = {
            "error_type": error_type,
            "is_error": True,
            "error_message": error_message or f"发生错误: {error_type}",
        }
        if full_msg:
            msg_dict = full_msg.model_dump() if hasattr(full_msg, "model_dump") else {}
            content = full_msg.content if hasattr(full_msg, "content") else str(full_msg)
            extra_metadata = msg_dict | extra_metadata
        else:
            content = ""

        return await conv_repo.add_message_by_thread_id(
            thread_id=thread_id,
            role="assistant",
            content=content,
            message_type="text",
            extra_metadata=extra_metadata,
        )

    except Exception as e:
        logger.error(f"Error saving message: {e}")
        logger.error(traceback.format_exc())
        return None


async def save_messages_from_langgraph_state(
    graph,
    thread_id: str,
    conv_repo: ConversationRepository,
    config_dict: dict,
) -> None:
    try:
        messages = await _get_langgraph_messages(config_dict, graph)
        if messages is None:
            return

        existing_ids = await _get_existing_message_ids(conv_repo, thread_id)

        for msg in messages:
            msg_dict = msg.model_dump() if hasattr(msg, "model_dump") else {}
            msg_type = msg_dict.get("type", "unknown")

            if msg_type == "human" or getattr(msg, "id", None) in existing_ids:
                continue

            if msg_type == "ai":
                await _save_ai_message(conv_repo, thread_id, msg_dict)
            elif msg_type == "tool":
                await _save_tool_message(conv_repo, msg_dict)

    except Exception as e:
        logger.error(f"Error saving messages from LangGraph state: {e}")
        logger.error(traceback.format_exc())


async def check_and_handle_interrupts(
    graph,
    langgraph_config: dict,
    make_chunk,
    meta: dict,
    thread_id: str,
    on_interrupt=None,
) -> AsyncIterator[bytes]:
    try:
        state = await graph.aget_state(langgraph_config)

        if not state or not state.values:
            return

        interrupt_info = None

        if hasattr(state, "tasks") and state.tasks:
            for task in state.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_info = task.interrupts[0]
                    break

        if not interrupt_info and state.values:
            interrupt_data = state.values.get("__interrupt__")
            if interrupt_data and isinstance(interrupt_data, list) and len(interrupt_data) > 0:
                interrupt_info = interrupt_data[0]

        if interrupt_info:
            question = "是否批准以下操作？"
            operation = "需要人工审批的操作"
            allowed_decisions = ["approve", "reject", "edit"]
            if isinstance(interrupt_info, dict):
                question = interrupt_info.get("question", question)
                operation = interrupt_info.get("operation", operation)
                allowed_decisions = interrupt_info.get("allowed_decisions") or allowed_decisions
            elif hasattr(interrupt_info, "question"):
                question = getattr(interrupt_info, "question", question)
                operation = getattr(interrupt_info, "operation", operation)
                allowed_decisions = getattr(interrupt_info, "allowed_decisions", allowed_decisions)

            if not isinstance(allowed_decisions, list) or not allowed_decisions:
                allowed_decisions = ["approve", "reject", "edit"]
            else:
                allowed_decisions = [str(item).strip() for item in allowed_decisions if str(item).strip()]
                if not allowed_decisions:
                    allowed_decisions = ["approve", "reject", "edit"]

            meta["interrupt"] = {
                "question": question,
                "operation": operation,
                "thread_id": thread_id,
                "allowed_decisions": allowed_decisions,
            }
            await _runtime_transition(
                meta=meta,
                next_status="paused",
                actor_type="system",
                actor_name="chat_stream_service",
                reason=operation,
            )
            await _runtime_append_event(
                meta=meta,
                event_type="run.paused",
                actor_type="system",
                actor_name="chat_stream_service",
                payload={
                    "thread_id": thread_id,
                    "question": question,
                    "operation": operation,
                    "allowed_decisions": allowed_decisions,
                },
            )
            if on_interrupt:
                await on_interrupt(question, operation)
            yield make_chunk(
                status="human_approval_required",
                message=question,
                thread_id=thread_id,
                interrupt_info={
                    "question": question,
                    "operation": operation,
                    "allowed_decisions": allowed_decisions,
                },
                meta=meta,
            )

    except Exception as e:
        logger.error(f"Error checking interrupts: {e}")
        logger.error(traceback.format_exc())


async def stream_agent_chat(
    *,
    agent_id: str,
    query: str,
    config: dict,
    meta: dict,
    image_content: str | None,
    current_user,
    db,
) -> AsyncIterator[bytes]:
    start_time = asyncio.get_event_loop().time()

    def make_chunk(content=None, **kwargs):
        return (
            json.dumps(
                {"request_id": meta.get("request_id"), "response": content, **kwargs}, ensure_ascii=False
            ).encode("utf-8")
            + b"\n"
        )

    if image_content:
        human_message = HumanMessage(
            content=[
                {"type": "text", "text": query},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_content}"}},
            ]
        )
        message_type = "multimodal_image"
    else:
        human_message = HumanMessage(content=query)
        message_type = "text"

    init_msg = {"role": "user", "content": query, "type": "human"}
    if image_content:
        init_msg["message_type"] = "multimodal_image"
        init_msg["image_content"] = image_content
    else:
        init_msg["message_type"] = "text"

    await _runtime_append_event(
        meta=meta,
        event_type="run.dispatched",
        actor_type="system",
        actor_name="chat_stream_service",
        payload={"agent_id": agent_id, "query": query, "has_image": bool(image_content)},
    )
    yield make_chunk(status="init", meta=meta, msg=init_msg)

    if conf.enable_content_guard and await content_guard.check(query):
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="content_guard_blocked",
        )
        yield make_chunk(
            status="error", error_type="content_guard_blocked", error_message="输入内容包含敏感词", meta=meta
        )
        return

    try:
        agent = agent_manager.get_agent(agent_id)
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}, {traceback.format_exc()}")
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="agent_error",
        )
        yield make_chunk(
            status="error",
            error_type="agent_error",
            error_message=f"智能体 {agent_id} 获取失败: {str(e)}",
            meta=meta,
        )
        return

    messages = [human_message]

    user_id = str(current_user.id)
    department_id = current_user.department_id
    if not department_id:
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="no_department",
        )
        yield make_chunk(status="error", error_type="no_department", error_message="当前用户未绑定部门", meta=meta)
        return

    agent_config_id = config.get("agent_config_id")
    config_repo = AgentConfigRepository(db)
    config_item = None
    if agent_config_id is not None:
        try:
            config_item = await config_repo.get_by_id(int(agent_config_id))
        except Exception:
            logger.warning(f"Failed to fetch agent config {agent_config_id}: {traceback.format_exc()}")
            config_item = None
        if config_item is not None and (config_item.department_id != department_id or config_item.agent_id != agent_id):
            config_item = None

    if config_item is None:
        config_item = await config_repo.get_or_create_default(
            department_id=department_id, agent_id=agent_id, created_by=user_id
        )
        agent_config_id = config_item.id

    if not (thread_id := config.get("thread_id")):
        thread_id = str(uuid.uuid4())
        logger.warning(f"No thread_id provided, generated new thread_id: {thread_id}")

    agent_config = _resolve_agent_config_context(config_item)
    team_execution_mode = str(agent_config.get("multi_agent_mode") or "disabled")
    team_policy = agent_config.get("team_policy") if isinstance(agent_config, dict) else {}
    runtime_audit = (team_policy or {}).get("runtime_audit") if isinstance(team_policy, dict) else {}
    input_context = {
        "user_id": user_id,
        "thread_id": thread_id,
        "department_id": department_id,
        "agent_config_id": agent_config_id,
        "agent_config": agent_config,
    }
    dynamic_graph_kwargs = _build_dynamic_graph_kwargs(agent, input_context) if agent_id == "DynamicAgent" else None
    graph_kwargs = (
        dynamic_graph_kwargs
        if dynamic_graph_kwargs is not None
        else {"user_id": user_id, "department_id": department_id}
    )

    thread_lock = _thread_stream_locks[thread_id]
    if thread_lock.locked():
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="thread_busy",
        )
        yield make_chunk(
            status="error",
            error_type="thread_busy",
            error_message="当前会话正在执行中，请稍后重试",
            meta=meta,
        )
        return
    await thread_lock.acquire()
    distributed_lock_session = None

    try:
        distributed_lock_session, distributed_lock_acquired = await _try_acquire_distributed_thread_lock(thread_id)
        if not distributed_lock_acquired:
            await _runtime_transition(
                meta=meta,
                next_status="failed",
                actor_type="system",
                actor_name="chat_stream_service",
                reason="thread_busy",
            )
            yield make_chunk(
                status="error",
                error_type="thread_busy",
                error_message="当前会话正在执行中，请稍后重试",
                meta=meta,
            )
            return
        conv_repo = ConversationRepository(db)
        run_id = _extract_run_id(meta)
        runtime_metadata = {"current_run_id": run_id} if run_id else {}
        if agent_config_id is not None:
            runtime_metadata["agent_config_id"] = agent_config_id
        await update_thread_runtime_status(
            conv_repo,
            thread_id,
            RUNTIME_STATUS_RUNNING,
            has_interrupt=False,
            extra_metadata=runtime_metadata or None,
        )
        await _runtime_transition(
            meta=meta,
            next_status="running",
            actor_type="system",
            actor_name="chat_stream_service",
            reason=f"thread:{thread_id}",
        )
        await _runtime_append_event(
            meta=meta,
            event_type="team.execution.started",
            actor_type="system",
            actor_name=team_execution_mode,
            payload={
                "thread_id": thread_id,
                "mode": team_execution_mode,
                "runtime_audit": runtime_audit if isinstance(runtime_audit, dict) else {},
            },
        )

        try:
            await conv_repo.add_message_by_thread_id(
                thread_id=thread_id,
                role="user",
                content=query,
                message_type=message_type,
                image_content=image_content,
                extra_metadata={"raw_message": human_message.model_dump()},
            )
        except Exception as e:
            logger.error(f"Error saving user message: {e}")

        # 先构建 langgraph_config
        langgraph_config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
        state_graph = None

        # 注意：LangGraph 会自动从 checkpointer 恢复 state（包括 attachments 和 files）
        # 无需手动加载或传递

        # 根据用户权限过滤知识库
        requested_knowledge_names = input_context["agent_config"].get("knowledges")
        requested_subagents = input_context["agent_config"].get("subagents") or []
        need_kb_filter = bool(requested_knowledge_names) or any(
            isinstance(sa, dict) and sa.get("knowledges") for sa in requested_subagents
        )
        logger.info(f"Requesting knowledges: {requested_knowledge_names}")
        if need_kb_filter:
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
                input_context["agent_config"]["knowledges"] = filtered_knowledge_names

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
                        logger.warning(
                            f"用户 {user_id} 子Agent `{sa.get('name')}` 无权访问知识库: {blocked_text}, 已自动过滤"
                        )
                    sa["knowledges"] = filtered_sa_knowledges

        full_msg = None
        accumulated_content = []
        tool_state_event_count = 0
        last_tool_state_emit_at = 0.0
        pending_agent_state_task: asyncio.Task | None = None
        current_subagent = None  # 跟踪当前执行的子 Agent
        seen_supervisor_entry_fingerprints: set[str] = set()

        async def _load_agent_state_snapshot() -> dict:
            nonlocal state_graph
            started_at = asyncio.get_event_loop().time()
            if state_graph is None:
                state_graph = await agent.get_graph(**graph_kwargs)
            state = await state_graph.aget_state(langgraph_config)
            elapsed_ms = (asyncio.get_event_loop().time() - started_at) * 1000
            logger.debug(f"stream_agent_chat: refreshed agent_state snapshot in {elapsed_ms:.1f}ms")
            return extract_agent_state(getattr(state, "values", {}), include_attachment_content=False) if state else {}

        async def _emit_pending_agent_state():
            nonlocal pending_agent_state_task
            if pending_agent_state_task is None or not pending_agent_state_task.done():
                return
            task = pending_agent_state_task
            pending_agent_state_task = None
            try:
                agent_state = task.result()
            except Exception as e:
                logger.debug(f"Skipped agent_state emit due to state refresh error: {e}")
                return
            if agent_state:
                yield make_chunk(status="agent_state", agent_state=agent_state, meta=meta)

        async for msg, metadata in _iterate_with_next_timeout(
            agent.stream_messages(messages, input_context=input_context),
            AGENT_STREAM_NEXT_TIMEOUT_SECONDS,
        ):
            async for state_chunk in _emit_pending_agent_state():
                yield state_chunk

            # 检查是 updates 模式还是 messages 模式
            if isinstance(metadata, dict) and metadata.get("mode") == "updates":
                # 这是状态更新事件（包含子 Agent 步骤信息）
                update_event = msg  # msg 实际上是 update_event 字典
                if isinstance(update_event, dict) and update_event.get("type") == "state_update":
                    is_subagent = update_event.get("is_subagent", False)
                    subagent_name = update_event.get("subagent_name")
                    nodes = update_event.get("nodes", [])

                    # 发送子 Agent 状态更新事件
                    if is_subagent and nodes:
                        # 过滤内部中间件步骤，只显示有意义的节点
                        interesting_nodes = [n for n in nodes if n in ("model_request", "tools")]
                        if interesting_nodes:
                            # 跟踪子 Agent 状态变化
                            if subagent_name != current_subagent:
                                current_subagent = subagent_name
                            await _runtime_append_event(
                                meta=meta,
                                event_type="agent.spawned",
                                actor_type="subagent",
                                actor_name=subagent_name or "unknown_subagent",
                                payload={
                                    "step": interesting_nodes[0],
                                    "namespace": update_event.get("namespace", []),
                                },
                            )
                            yield make_chunk(
                                status="subagent_step",
                                subagent_name=subagent_name,
                                step=interesting_nodes[0],
                                namespace=update_event.get("namespace", []),
                                meta=meta,
                            )

                    # 记录 supervisor 执行期审计事件（路由/重试/依赖门控等）
                    for entry in _collect_supervisor_execution_entries(update_event):
                        fp = _supervisor_entry_fingerprint(entry)
                        if fp in seen_supervisor_entry_fingerprints:
                            continue
                        seen_supervisor_entry_fingerprints.add(fp)
                        event_type = _map_supervisor_entry_to_runtime_event(str(entry.get("type") or ""))
                        await _runtime_append_event(
                            meta=meta,
                            event_type=event_type,
                            actor_type="supervisor",
                            actor_name="dynamic_supervisor",
                            payload={
                                "mode": team_execution_mode,
                                "entry": entry,
                            },
                        )
                        yield make_chunk(
                            status="execution_audit",
                            audit_event_type=event_type,
                            audit_event=entry,
                            meta=meta,
                        )
                continue

            # messages 模式：原有的消息处理逻辑
            is_subagent = metadata.get("is_subagent", False) if isinstance(metadata, dict) else False
            subagent_name = metadata.get("subagent_name") if isinstance(metadata, dict) else None

            if isinstance(msg, AIMessageChunk):
                accumulated_content.append(msg.content)

                content_for_check = "".join(accumulated_content[-10:])
                if conf.enable_content_guard and await content_guard.check_with_keywords(content_for_check):
                    full_msg = AIMessage(content="".join(accumulated_content))
                    await save_partial_message(conv_repo, thread_id, full_msg, "content_guard_blocked")
                    meta["time_cost"] = asyncio.get_event_loop().time() - start_time
                    await _runtime_transition(
                        meta=meta,
                        next_status="failed",
                        actor_type="system",
                        actor_name="chat_stream_service",
                        reason="content_guard_blocked",
                    )
                    yield make_chunk(status="interrupted", message="检测到敏感内容，已中断输出", meta=meta)
                    return

                # 添加子 Agent 信息到输出
                yield make_chunk(
                    content=msg.content,
                    msg=msg.model_dump(),
                    metadata=metadata,
                    status="loading",
                    is_subagent=is_subagent,
                    subagent_name=subagent_name,
                )
            else:
                msg_dict = msg.model_dump() if hasattr(msg, "model_dump") else msg
                yield make_chunk(
                    msg=msg_dict,
                    metadata=metadata,
                    status="loading",
                    is_subagent=is_subagent,
                    subagent_name=subagent_name,
                )

                try:
                    if isinstance(msg_dict, dict) and msg_dict.get("type") == "tool":
                        await _runtime_append_event(
                            meta=meta,
                            event_type="tool.called",
                            actor_type="tool",
                            actor_name=str(msg_dict.get("name") or "unknown_tool"),
                            payload={
                                "tool_call_id": msg_dict.get("tool_call_id"),
                                "metadata": metadata if isinstance(metadata, dict) else {},
                            },
                        )
                        tool_state_event_count += 1
                        now_ts = asyncio.get_event_loop().time()
                        should_emit_state = tool_state_event_count % 3 == 0 or (now_ts - last_tool_state_emit_at) >= 1.5
                        if not should_emit_state:
                            continue
                        last_tool_state_emit_at = now_ts
                        if pending_agent_state_task is None or pending_agent_state_task.done():
                            pending_agent_state_task = asyncio.create_task(_load_agent_state_snapshot())
                except Exception as e:
                    logger.error(f"Error processing tool message: {e}")

        if not full_msg and accumulated_content:
            full_msg = AIMessage(content="".join(accumulated_content))

        async for state_chunk in _emit_pending_agent_state():
            yield state_chunk
        if pending_agent_state_task is not None and not pending_agent_state_task.done():
            pending_agent_state_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending_agent_state_task

        if conf.enable_content_guard and hasattr(full_msg, "content") and await content_guard.check(full_msg.content):
            await save_partial_message(conv_repo, thread_id, full_msg, "content_guard_blocked")
            meta["time_cost"] = asyncio.get_event_loop().time() - start_time
            await _runtime_transition(
                meta=meta,
                next_status="failed",
                actor_type="system",
                actor_name="chat_stream_service",
                reason="content_guard_blocked",
            )
            yield make_chunk(status="interrupted", message="检测到敏感内容，已中断输出", meta=meta)
            return

        if state_graph is None:
            state_graph = await agent.get_graph(**graph_kwargs)

        async def _mark_interrupt(_question, _operation):
            await update_thread_runtime_status(
                conv_repo,
                thread_id,
                RUNTIME_STATUS_WAITING_FOR_HUMAN,
                has_interrupt=True,
            )

        async for chunk in check_and_handle_interrupts(
            state_graph, langgraph_config, make_chunk, meta, thread_id, on_interrupt=_mark_interrupt
        ):
            yield chunk

        meta["time_cost"] = asyncio.get_event_loop().time() - start_time
        try:
            state = await state_graph.aget_state(langgraph_config) if state_graph else None
            agent_state = (
                extract_agent_state(getattr(state, "values", {}), include_attachment_content=False) if state else {}
            )
        except Exception:
            agent_state = {}

        if agent_state:
            yield make_chunk(status="agent_state", agent_state=agent_state, meta=meta)
            await _runtime_append_event(
                meta=meta,
                event_type="team.execution.summary",
                actor_type="system",
                actor_name=team_execution_mode,
                payload={
                    "route_count": len(agent_state.get("route_history") or []),
                    "execution_log_count": len(agent_state.get("execution_log") or []),
                    "completed_agents": list(agent_state.get("completed_agents") or []),
                    "retry_counts": dict(agent_state.get("retry_counts") or {}),
                    "active_agent": agent_state.get("active_agent"),
                },
            )

        # 先存储数据库，再返回 finished，避免前端查询时数据未落库
        await save_messages_from_langgraph_state(
            graph=state_graph,
            thread_id=thread_id,
            conv_repo=conv_repo,
            config_dict=langgraph_config,
        )
        await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_COMPLETED, has_interrupt=False)
        await _runtime_transition(
            meta=meta,
            next_status="completed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="stream_finished",
        )
        await _runtime_append_event(
            meta=meta,
            event_type="run.completed",
            actor_type="system",
            actor_name="chat_stream_service",
            payload={"thread_id": thread_id},
        )

        yield make_chunk(status="finished", meta=meta)

    except (asyncio.CancelledError, ConnectionError) as e:
        logger.warning(f"Client disconnected, cancelling stream: {e}")

        async def save_cleanup():
            nonlocal full_msg
            if not full_msg and accumulated_content:
                full_msg = AIMessage(content="".join(accumulated_content))

            async with pg_manager.get_async_session_context() as new_db:
                new_conv_repo = ConversationRepository(new_db)
                await save_partial_message(
                    new_conv_repo,
                    thread_id,
                    full_msg=full_msg,
                    error_message="对话已中断" if not full_msg else None,
                    error_type="interrupted",
                )
                await update_thread_runtime_status(new_conv_repo, thread_id, RUNTIME_STATUS_IDLE, has_interrupt=False)

        cleanup_task = asyncio.create_task(save_cleanup())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Error during cleanup save: {exc}")

        await _runtime_transition(
            meta=meta,
            next_status="cancelled",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="client_disconnected",
        )
        yield make_chunk(status="interrupted", message="对话已中断", meta=meta)

    except Exception as e:
        logger.error(f"Error streaming messages: {e}, {traceback.format_exc()}")

        error_msg = f"Error streaming messages: {e}"
        error_type = "unexpected_error"

        if not full_msg and accumulated_content:
            full_msg = AIMessage(content="".join(accumulated_content))

        async with pg_manager.get_async_session_context() as new_db:
            new_conv_repo = ConversationRepository(new_db)
            await save_partial_message(
                new_conv_repo,
                thread_id,
                full_msg=full_msg,
                error_message=error_msg,
                error_type=error_type,
            )
            await update_thread_runtime_status(
                new_conv_repo,
                thread_id,
                RUNTIME_STATUS_ERROR,
                has_interrupt=False,
                error_message=error_msg,
            )

        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason=error_type,
        )
        await _runtime_append_event(
            meta=meta,
            event_type="run.failed",
            actor_type="system",
            actor_name="chat_stream_service",
            payload={"error_type": error_type, "error_message": error_msg},
        )
        yield make_chunk(status="error", error_type=error_type, error_message=error_msg, meta=meta)
    finally:
        pending_agent_state_task = locals().get("pending_agent_state_task")
        if pending_agent_state_task is not None and not pending_agent_state_task.done():
            pending_agent_state_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending_agent_state_task
        await _release_distributed_thread_lock(distributed_lock_session, thread_id)
        if thread_lock.locked():
            thread_lock.release()


async def stream_agent_resume(
    *,
    agent_id: str,
    thread_id: str,
    resume_payload: bool | dict,
    meta: dict,
    config: dict,
    current_user,
    db,
) -> AsyncIterator[bytes]:
    start_time = asyncio.get_event_loop().time()

    def make_resume_chunk(content=None, **kwargs):
        return (
            json.dumps(
                {"request_id": meta.get("request_id"), "response": content, **kwargs}, ensure_ascii=False
            ).encode("utf-8")
            + b"\n"
        )

    thread_lock = _thread_stream_locks[thread_id]
    if thread_lock.locked():
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="thread_busy",
        )
        yield make_resume_chunk(
            status="error",
            error_type="thread_busy",
            error_message="当前会话正在执行中，请稍后重试",
            meta=meta,
        )
        return
    await thread_lock.acquire()
    distributed_lock_session = None

    try:
        distributed_lock_session, distributed_lock_acquired = await _try_acquire_distributed_thread_lock(thread_id)
        if not distributed_lock_acquired:
            await _runtime_transition(
                meta=meta,
                next_status="failed",
                actor_type="system",
                actor_name="chat_stream_service.resume",
                reason="thread_busy",
            )
            yield make_resume_chunk(
                status="error",
                error_type="thread_busy",
                error_message="当前会话正在执行中，请稍后重试",
                meta=meta,
            )
            return
        agent = agent_manager.get_agent(agent_id)
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}, {traceback.format_exc()}")
        yield (
            f'{{"request_id": "{meta.get("request_id")}", "message": '
            f'"Error getting agent {agent_id}: {e}", "status": "error"}}\n'
        )
        return

    init_msg = {"type": "system", "content": f"Resume with decision: {meta.get('decision', 'approve')}"}
    await _runtime_transition(
        meta=meta,
        next_status="resuming",
        actor_type="user",
        actor_name=str(current_user.id),
        reason=f"decision:{meta.get('decision')}",
    )
    await _runtime_append_event(
        meta=meta,
        event_type="run.resumed",
        actor_type="user",
        actor_name=str(current_user.id),
        payload={"decision": meta.get("decision"), "thread_id": thread_id},
    )
    yield make_resume_chunk(status="init", meta=meta, msg=init_msg)

    resume_command = Command(resume=resume_payload)
    user_id = str(current_user.id)
    department_id = current_user.department_id
    if not department_id:
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="no_department",
        )
        yield make_resume_chunk(
            status="error", error_type="no_department", error_message="当前用户未绑定部门", meta=meta
        )
        return

    agent_config_id = (config or {}).get("agent_config_id")
    config_repo = AgentConfigRepository(db)
    config_item = None
    if agent_config_id is not None:
        try:
            config_item = await config_repo.get_by_id(int(agent_config_id))
        except Exception:
            logger.warning(f"Failed to fetch agent config {agent_config_id}: {traceback.format_exc()}")
            config_item = None
        if config_item is not None and (config_item.department_id != department_id or config_item.agent_id != agent_id):
            config_item = None

    if config_item is None:
        config_item = await config_repo.get_or_create_default(
            department_id=department_id, agent_id=agent_id, created_by=user_id
        )
        agent_config_id = config_item.id

    input_context = {
        "user_id": user_id,
        "thread_id": thread_id,
        "department_id": department_id,
        "agent_config_id": agent_config_id,
        "agent_config": _resolve_agent_config_context(config_item),
    }
    context = agent._build_runtime_context(input_context)
    dynamic_graph_kwargs = _build_dynamic_graph_kwargs(agent, input_context) if agent_id == "DynamicAgent" else None
    graph_kwargs = (
        dynamic_graph_kwargs
        if dynamic_graph_kwargs is not None
        else {"user_id": user_id, "department_id": department_id}
    )
    graph = await agent.get_graph(**graph_kwargs)

    stream_source = graph.astream(
        resume_command,
        context=context,
        config={"configurable": {"thread_id": thread_id, "user_id": user_id}},
        stream_mode="messages",
    )
    conv_repo = ConversationRepository(db)
    run_id = _extract_run_id(meta)
    runtime_metadata = {"current_run_id": run_id} if run_id else {}
    if agent_config_id is not None:
        runtime_metadata["agent_config_id"] = agent_config_id
    await update_thread_runtime_status(
        conv_repo,
        thread_id,
        RUNTIME_STATUS_RUNNING,
        has_interrupt=False,
        extra_metadata=runtime_metadata or None,
    )
    await _runtime_transition(
        meta=meta,
        next_status="running",
        actor_type="system",
        actor_name="chat_stream_service.resume",
        reason="resume_stream_started",
    )

    try:
        async for msg, metadata in _iterate_with_next_timeout(stream_source, AGENT_STREAM_NEXT_TIMEOUT_SECONDS):
            msg_dict = msg.model_dump()
            if "id" not in msg_dict:
                msg_dict["id"] = str(uuid.uuid4())
            if isinstance(msg_dict, dict) and msg_dict.get("type") == "tool":
                await _runtime_append_event(
                    meta=meta,
                    event_type="tool.called",
                    actor_type="tool",
                    actor_name=str(msg_dict.get("name") or "unknown_tool"),
                    payload={
                        "tool_call_id": msg_dict.get("tool_call_id"),
                        "resume": True,
                        "metadata": metadata if isinstance(metadata, dict) else {},
                    },
                )

            yield make_resume_chunk(
                content=getattr(msg, "content", ""), msg=msg_dict, metadata=metadata, status="loading"
            )

        langgraph_config = {"configurable": {"thread_id": thread_id, "user_id": str(current_user.id)}}

        async def _mark_interrupt(_question, _operation):
            await update_thread_runtime_status(
                conv_repo,
                thread_id,
                RUNTIME_STATUS_WAITING_FOR_HUMAN,
                has_interrupt=True,
            )

        async for chunk in check_and_handle_interrupts(
            graph, langgraph_config, make_resume_chunk, meta, thread_id, on_interrupt=_mark_interrupt
        ):
            yield chunk

        meta["time_cost"] = asyncio.get_event_loop().time() - start_time

        # 先存储数据库，再返回 finished，避免前端查询时数据未落库
        await save_messages_from_langgraph_state(
            graph=graph,
            thread_id=thread_id,
            conv_repo=conv_repo,
            config_dict=langgraph_config,
        )
        await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_COMPLETED, has_interrupt=False)
        await _runtime_transition(
            meta=meta,
            next_status="completed",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="resume_finished",
        )

        yield make_resume_chunk(status="finished", meta=meta)

    except (asyncio.CancelledError, ConnectionError) as e:
        logger.warning(f"Client disconnected during resume: {e}")

        async with pg_manager.get_async_session_context() as new_db:
            new_conv_repo = ConversationRepository(new_db)
            await save_partial_message(
                new_conv_repo, thread_id, error_message="对话恢复已中断", error_type="resume_interrupted"
            )
            await update_thread_runtime_status(new_conv_repo, thread_id, RUNTIME_STATUS_IDLE, has_interrupt=False)

        await _runtime_transition(
            meta=meta,
            next_status="cancelled",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="resume_interrupted",
        )
        yield make_resume_chunk(status="interrupted", message="对话恢复已中断", meta=meta)

    except Exception as e:
        logger.error(f"Error during resume: {e}, {traceback.format_exc()}")

        async with pg_manager.get_async_session_context() as new_db:
            new_conv_repo = ConversationRepository(new_db)
            await save_partial_message(
                new_conv_repo, thread_id, error_message=f"Error during resume: {e}", error_type="resume_error"
            )
            await update_thread_runtime_status(
                new_conv_repo,
                thread_id,
                RUNTIME_STATUS_ERROR,
                has_interrupt=False,
                error_message=f"Error during resume: {e}",
            )

        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="resume_error",
        )
        yield make_resume_chunk(message=f"Error during resume: {e}", status="error")
    finally:
        await _release_distributed_thread_lock(distributed_lock_session, thread_id)
        if thread_lock.locked():
            thread_lock.release()


async def get_agent_state_view(
    *,
    agent_id: str,
    thread_id: str,
    current_user_id: str,
    db,
) -> dict:
    cache_key = (agent_id, thread_id, str(current_user_id))
    now_ts = asyncio.get_event_loop().time()
    cache_lock = _get_agent_state_view_lock()

    async with cache_lock:
        cached = _agent_state_view_cache.get(cache_key)
        if cached is not None:
            expires_at, payload = cached
            if now_ts <= expires_at:
                return deepcopy(payload)

        inflight = _agent_state_view_inflight.get(cache_key)
        if inflight is None or inflight.done():
            inflight = asyncio.create_task(
                _compute_agent_state_view(
                    agent_id=agent_id,
                    thread_id=thread_id,
                    current_user_id=current_user_id,
                    db=db,
                )
            )
            _agent_state_view_inflight[cache_key] = inflight

    try:
        payload = await inflight
    except Exception:
        async with cache_lock:
            if _agent_state_view_inflight.get(cache_key) is inflight:
                _agent_state_view_inflight.pop(cache_key, None)
        raise

    async with cache_lock:
        _agent_state_view_cache[cache_key] = (
            asyncio.get_event_loop().time() + AGENT_STATE_VIEW_CACHE_TTL_SECONDS,
            payload,
        )
        if _agent_state_view_inflight.get(cache_key) is inflight:
            _agent_state_view_inflight.pop(cache_key, None)
        if len(_agent_state_view_cache) > 2048:
            _agent_state_view_cache.clear()

    return deepcopy(payload)


async def _compute_agent_state_view(
    *,
    agent_id: str,
    thread_id: str,
    current_user_id: str,
    db,
) -> dict:
    if not agent_manager.get_agent(agent_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

    conv_repo = ConversationRepository(db)
    conversation = await conv_repo.get_conversation_by_thread_id(thread_id)
    if not conversation or conversation.user_id != str(current_user_id) or conversation.status == "deleted":
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="对话线程不存在")

    agent = agent_manager.get_agent(agent_id)
    graph = None
    if agent_id == "DynamicAgent":
        input_context = {
            "user_id": str(current_user_id),
            "thread_id": thread_id,
        }
        config_id_value = (conversation.extra_metadata or {}).get("agent_config_id")
        if config_id_value not in (None, ""):
            try:
                config_id = int(config_id_value)
                config_repo = AgentConfigRepository(db)
                config_item = await config_repo.get_by_id(config_id)
                if config_item is not None and config_item.agent_id == agent_id:
                    input_context["agent_config_id"] = config_item.id
                    input_context["agent_config"] = _resolve_agent_config_context(config_item)
            except Exception:
                logger.warning(f"Failed to resolve dynamic config from thread metadata: {traceback.format_exc()}")

        dynamic_graph_kwargs = _build_dynamic_graph_kwargs(agent, input_context)
        if dynamic_graph_kwargs is not None:
            graph = await agent.get_graph(**dynamic_graph_kwargs)

    if graph is None:
        graph = await agent.get_graph(user_id=str(current_user_id))
    langgraph_config = {"configurable": {"user_id": str(current_user_id), "thread_id": thread_id}}
    state_fetch_started_at = asyncio.get_event_loop().time()
    state = await graph.aget_state(langgraph_config)
    state_fetch_ms = (asyncio.get_event_loop().time() - state_fetch_started_at) * 1000
    logger.info(f"[get_agent_state_view] fetched graph state in {state_fetch_ms:.1f}ms for thread {thread_id}")
    agent_state = extract_agent_state(getattr(state, "values", {})) if state else {}

    # 如果 state 中没有 files，从附件构建
    # 这确保了上传附件后立即可以在文件列表中看到文件
    if not agent_state.get("files") or agent_state["files"] == {}:
        try:
            attachments = await conv_repo.get_attachments_by_thread_id(thread_id)
            logger.info(f"[get_agent_state_view] found {len(attachments)} attachments in DB")
            if attachments:
                first_status = attachments[0].get("status")
                first_has_markdown = bool(attachments[0].get("markdown"))
                logger.info(
                    f"[get_agent_state_view] first attachment status: {first_status}, "
                    f"has markdown: {first_has_markdown}"
                )
                files = _build_state_files(attachments)
                agent_state["files"] = files
                logger.info(f"[get_agent_state_view] Built files from attachments: {len(files)} files")
        except Exception as e:
            logger.warning(f"Failed to fetch attachments for thread {thread_id}: {e}")

    return {"agent_state": agent_state}
