import asyncio
import contextlib
import hashlib
import json
import os
import traceback
import uuid
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
) -> None:
    await conv_repo.update_conversation(
        thread_id=thread_id,
        metadata=_runtime_status_metadata(
            status,
            has_interrupt=has_interrupt,
            error_message=error_message,
        ),
    )


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
    }

    return result


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
            if isinstance(interrupt_info, dict):
                question = interrupt_info.get("question", question)
                operation = interrupt_info.get("operation", operation)
            elif hasattr(interrupt_info, "question"):
                question = getattr(interrupt_info, "question", question)
                operation = getattr(interrupt_info, "operation", operation)

            meta["interrupt"] = {
                "question": question,
                "operation": operation,
                "thread_id": thread_id,
            }
            if on_interrupt:
                await on_interrupt(question, operation)
            yield make_chunk(status="interrupted", message=question, meta=meta)

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

    yield make_chunk(status="init", meta=meta, msg=init_msg)

    if conf.enable_content_guard and await content_guard.check(query):
        yield make_chunk(
            status="error", error_type="content_guard_blocked", error_message="输入内容包含敏感词", meta=meta
        )
        return

    try:
        agent = agent_manager.get_agent(agent_id)
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}, {traceback.format_exc()}")
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

    agent_config = (config_item.config_json or {}).get("context", {})
    input_context = {
        "user_id": user_id,
        "thread_id": thread_id,
        "department_id": department_id,
        "agent_config_id": agent_config_id,
        "agent_config": agent_config,
    }

    thread_lock = _thread_stream_locks[thread_id]
    if thread_lock.locked():
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
            yield make_chunk(
                status="error",
                error_type="thread_busy",
                error_message="当前会话正在执行中，请稍后重试",
                meta=meta,
            )
            return
        conv_repo = ConversationRepository(db)
        await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_RUNNING, has_interrupt=False)

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
        logger.info(f"Requesting knowledges: {requested_knowledge_names}")
        if requested_knowledge_names and isinstance(requested_knowledge_names, list) and requested_knowledge_names:
            user_info = {"role": "user", "department_id": department_id}
            accessible_databases = await knowledge_base.get_databases_by_user(user_info)
            accessible_kb_names = {
                db.get("name")
                for db in accessible_databases.get("databases", [])
                if isinstance(db, dict) and db.get("name")
            }
            logger.info(f"Accessible knowledges: {accessible_kb_names}")

            filtered_knowledge_names = [kb for kb in requested_knowledge_names if kb in accessible_kb_names]
            blocked_knowledge_names = [kb for kb in requested_knowledge_names if kb not in accessible_kb_names]
            if blocked_knowledge_names:
                logger.warning(f"用户 {user_id} 无权访问知识库: {blocked_knowledge_names}, 已自动过滤")
            input_context["agent_config"]["knowledges"] = filtered_knowledge_names

        full_msg = None
        accumulated_content = []
        tool_state_event_count = 0
        last_tool_state_emit_at = 0.0
        async for msg, metadata in _iterate_with_next_timeout(
            agent.stream_messages(messages, input_context=input_context),
            AGENT_STREAM_NEXT_TIMEOUT_SECONDS,
        ):
            if isinstance(msg, AIMessageChunk):
                accumulated_content.append(msg.content)

                content_for_check = "".join(accumulated_content[-10:])
                if conf.enable_content_guard and await content_guard.check_with_keywords(content_for_check):
                    full_msg = AIMessage(content="".join(accumulated_content))
                    await save_partial_message(conv_repo, thread_id, full_msg, "content_guard_blocked")
                    meta["time_cost"] = asyncio.get_event_loop().time() - start_time
                    yield make_chunk(status="interrupted", message="检测到敏感内容，已中断输出", meta=meta)
                    return

                yield make_chunk(content=msg.content, msg=msg.model_dump(), metadata=metadata, status="loading")
            else:
                msg_dict = msg.model_dump()
                yield make_chunk(msg=msg_dict, metadata=metadata, status="loading")

                try:
                    if msg_dict.get("type") == "tool":
                        tool_state_event_count += 1
                        now_ts = asyncio.get_event_loop().time()
                        should_emit_state = tool_state_event_count % 3 == 0 or (now_ts - last_tool_state_emit_at) >= 1.5
                        if not should_emit_state:
                            continue
                        last_tool_state_emit_at = now_ts
                        if state_graph is None:
                            state_graph = await agent.get_graph()
                        state = await state_graph.aget_state(langgraph_config)
                        agent_state = (
                            extract_agent_state(getattr(state, "values", {}), include_attachment_content=False)
                            if state
                            else {}
                        )
                        if agent_state:
                            yield make_chunk(status="agent_state", agent_state=agent_state, meta=meta)
                except Exception as e:
                    logger.error(f"Error processing tool message: {e}")

        if not full_msg and accumulated_content:
            full_msg = AIMessage(content="".join(accumulated_content))

        if conf.enable_content_guard and hasattr(full_msg, "content") and await content_guard.check(full_msg.content):
            await save_partial_message(conv_repo, thread_id, full_msg, "content_guard_blocked")
            meta["time_cost"] = asyncio.get_event_loop().time() - start_time
            yield make_chunk(status="interrupted", message="检测到敏感内容，已中断输出", meta=meta)
            return

        if state_graph is None:
            state_graph = await agent.get_graph()

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

        # 先存储数据库，再返回 finished，避免前端查询时数据未落库
        await save_messages_from_langgraph_state(
            graph=state_graph,
            thread_id=thread_id,
            conv_repo=conv_repo,
            config_dict=langgraph_config,
        )
        await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_COMPLETED, has_interrupt=False)

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

        yield make_chunk(status="error", error_type=error_type, error_message=error_msg, meta=meta)
    finally:
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
    yield make_resume_chunk(status="init", meta=meta, msg=init_msg)

    resume_command = Command(resume=resume_payload)
    user_id = str(current_user.id)
    department_id = current_user.department_id
    if not department_id:
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
        "agent_config": (config_item.config_json or {}).get("context", config_item.config_json or {}),
    }
    context = agent._build_runtime_context(input_context)
    graph = await agent.get_graph()

    stream_source = graph.astream(
        resume_command,
        context=context,
        config={"configurable": {"thread_id": thread_id, "user_id": user_id}},
        stream_mode="messages",
    )
    conv_repo = ConversationRepository(db)
    await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_RUNNING, has_interrupt=False)

    try:
        async for msg, metadata in _iterate_with_next_timeout(stream_source, AGENT_STREAM_NEXT_TIMEOUT_SECONDS):
            msg_dict = msg.model_dump()
            if "id" not in msg_dict:
                msg_dict["id"] = str(uuid.uuid4())

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

        yield make_resume_chunk(status="finished", meta=meta)

    except (asyncio.CancelledError, ConnectionError) as e:
        logger.warning(f"Client disconnected during resume: {e}")

        async with pg_manager.get_async_session_context() as new_db:
            new_conv_repo = ConversationRepository(new_db)
            await save_partial_message(
                new_conv_repo, thread_id, error_message="对话恢复已中断", error_type="resume_interrupted"
            )
            await update_thread_runtime_status(new_conv_repo, thread_id, RUNTIME_STATUS_IDLE, has_interrupt=False)

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
    if not agent_manager.get_agent(agent_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"智能体 {agent_id} 不存在")

    conv_repo = ConversationRepository(db)
    conversation = await conv_repo.get_conversation_by_thread_id(thread_id)
    if not conversation or conversation.user_id != str(current_user_id) or conversation.status == "deleted":
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="对话线程不存在")

    agent = agent_manager.get_agent(agent_id)
    graph = await agent.get_graph()
    langgraph_config = {"configurable": {"user_id": str(current_user_id), "thread_id": thread_id}}
    state = await graph.aget_state(langgraph_config)
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
