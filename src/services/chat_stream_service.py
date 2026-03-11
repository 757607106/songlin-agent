import asyncio
import contextlib
import os
import traceback
import uuid
from copy import deepcopy
from collections.abc import AsyncIterator

from langchain.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

from src import config as conf
from src.agent_platform.constants import AGENT_PLATFORM_AGENT_ID
from src.agents import agent_manager
from src.plugins.guard import content_guard
from src.repositories.agent_config_repository import AgentConfigRepository
from src.repositories.conversation_repository import ConversationRepository
from src.services.chat_stream_event_adapter import (
    agent_state_chunk,
    collect_supervisor_execution_entries as _collect_supervisor_execution_entries,
    collect_worker_route_entries as _collect_worker_route_entries,
    error_chunk,
    execution_audit_chunk,
    finished_chunk,
    init_chunk,
    interrupted_chunk,
    loading_chunk,
    make_stream_chunk_factory,
    subagent_step_chunk,
    extract_agent_state,
    extract_run_id as _extract_run_id,
    map_supervisor_entry_to_runtime_event as _map_supervisor_entry_to_runtime_event,
    runtime_append_event as _runtime_append_event,
    runtime_is_cancel_requested as _runtime_is_cancel_requested,
    runtime_sync_run_mode as _runtime_sync_run_mode,
    runtime_transition as _runtime_transition,
    supervisor_entry_fingerprint as _supervisor_entry_fingerprint,
)
from src.services.chat_stream_interrupt_service import check_and_handle_interrupts
from src.services.chat_stream_persistence import (
    save_messages_from_langgraph_state,
    save_partial_assistant_message,
    save_partial_message,
    update_thread_runtime_status,
)
from src.services.chat_stream_run_coordinator import (
    MissingDepartmentError,
    RunCoordinator,
    ThreadBusyError,
    build_dynamic_graph_kwargs as _build_dynamic_graph_kwargs,
    reserve_thread_slot,
    resolve_runtime_agent_config as _resolve_runtime_agent_config,
)
from src.storage.postgres.manager import pg_manager
from src.utils.logging_config import logger

RUNTIME_STATUS_IDLE = "idle"
RUNTIME_STATUS_RUNNING = "running"
RUNTIME_STATUS_WAITING_FOR_HUMAN = "waiting_for_human"
RUNTIME_STATUS_COMPLETED = "completed"
RUNTIME_STATUS_ERROR = "error"
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
    make_chunk = make_stream_chunk_factory(meta)

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
    yield init_chunk(meta=meta, msg=init_msg)

    if conf.enable_content_guard and await content_guard.check(query):
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="content_guard_blocked",
        )
        yield error_chunk(meta=meta, error_type="content_guard_blocked", error_message="输入内容包含敏感词")
        return

    run_coordinator = RunCoordinator(db)
    try:
        prepared_run = await run_coordinator.prepare_chat_run(
            agent_id=agent_id,
            config=config,
            current_user=current_user,
        )
    except MissingDepartmentError:
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="no_department",
        )
        yield error_chunk(meta=meta, error_type="no_department", error_message="当前用户未绑定部门")
        return
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}, {traceback.format_exc()}")
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="agent_error",
        )
        yield error_chunk(
            meta=meta,
            error_type="agent_error",
            error_message=f"智能体 {agent_id} 获取失败: {str(e)}",
        )
        return

    agent = prepared_run.agent
    messages = [human_message]
    user_id = prepared_run.user_id
    department_id = prepared_run.department_id
    thread_id = prepared_run.thread_id
    agent_config_id = prepared_run.agent_config_id
    agent_config = prepared_run.agent_config
    team_execution_mode = prepared_run.team_execution_mode
    runtime_audit = prepared_run.runtime_audit
    input_context = prepared_run.input_context
    graph_kwargs = prepared_run.graph_kwargs
    await _runtime_sync_run_mode(meta=meta, mode=team_execution_mode)
    full_msg = None
    accumulated_content: list[str] = []
    pending_agent_state_task: asyncio.Task | None = None

    try:
        async with reserve_thread_slot(thread_id):
            conv_repo = ConversationRepository(db)
            partial_saved_on_cancel = False
            excluded_ai_names = set(prepared_run.excluded_ai_names)

            async def _save_cancel_partial(conv_repo_target: ConversationRepository):
                nonlocal full_msg, partial_saved_on_cancel
                if partial_saved_on_cancel:
                    return
                if not full_msg and accumulated_content:
                    full_msg = AIMessage(content="".join(accumulated_content))
                content = full_msg.content if hasattr(full_msg, "content") and full_msg else ""
                if not str(content or "").strip():
                    return
                await save_partial_assistant_message(
                    conv_repo_target,
                    thread_id,
                    str(content),
                    stop_reason="cancel_requested",
                )
                partial_saved_on_cancel = True

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
            if await _runtime_is_cancel_requested(meta=meta):
                await _save_cancel_partial(conv_repo)
                await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_IDLE, has_interrupt=False)
                yield interrupted_chunk(meta=meta, message="运行已取消")
                return

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

            langgraph_config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
            state_graph = None

            requested_subagents = input_context["agent_config"].get("subagents") or []
            excluded_ai_names = {
                str(sa.get("name")).strip()
                for sa in requested_subagents
                if isinstance(sa, dict) and str(sa.get("name") or "").strip()
            }

            tool_state_event_count = 0
            last_tool_state_emit_at = 0.0
            current_subagent = None
            seen_supervisor_entry_fingerprints: set[str] = set()
            emitted_worker_route_count = 0
            last_cancel_check_ts = 0.0

            async def _load_agent_state_snapshot() -> dict:
                nonlocal state_graph
                started_at = asyncio.get_event_loop().time()
                if state_graph is None:
                    state_graph = await agent.get_graph(**graph_kwargs)
                state = await state_graph.aget_state(langgraph_config)
                elapsed_ms = (asyncio.get_event_loop().time() - started_at) * 1000
                logger.debug(f"stream_agent_chat: refreshed agent_state snapshot in {elapsed_ms:.1f}ms")
                if not state:
                    return {}
                return extract_agent_state(getattr(state, "values", {}), include_attachment_content=False)

            async def _emit_pending_agent_state():
                nonlocal pending_agent_state_task, emitted_worker_route_count
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
                    route_entries, emitted_worker_route_count = _collect_worker_route_entries(
                        agent_state, emitted_count=emitted_worker_route_count
                    )
                    for entry in route_entries:
                        await _runtime_append_event(
                            meta=meta,
                            event_type="worker.route",
                            actor_type="worker",
                            actor_name=str(entry.get("worker") or "unknown_worker"),
                            payload={
                                "mode": team_execution_mode,
                                "entry": entry,
                                "active_worker": agent_state.get("active_worker"),
                            },
                        )
                        yield execution_audit_chunk(meta=meta, audit_event_type="worker.route", audit_event=entry)
                    yield agent_state_chunk(meta=meta, agent_state=agent_state)

            async for msg, metadata in _iterate_with_next_timeout(
                agent.stream_messages(messages, input_context=input_context),
                AGENT_STREAM_NEXT_TIMEOUT_SECONDS,
            ):
                now_ts = asyncio.get_event_loop().time()
                if now_ts - last_cancel_check_ts >= 1.0:
                    last_cancel_check_ts = now_ts
                    if await _runtime_is_cancel_requested(meta=meta):
                        await _save_cancel_partial(conv_repo)
                        await update_thread_runtime_status(
                            conv_repo,
                            thread_id,
                            RUNTIME_STATUS_IDLE,
                            has_interrupt=False,
                        )
                        yield interrupted_chunk(meta=meta, message="运行已取消")
                        return
                async for state_chunk in _emit_pending_agent_state():
                    yield state_chunk

                if isinstance(metadata, dict) and metadata.get("mode") == "updates":
                    update_event = msg
                    if isinstance(update_event, dict) and update_event.get("type") == "state_update":
                        is_subagent = update_event.get("is_subagent", False)
                        subagent_name = update_event.get("subagent_name")
                        nodes = update_event.get("nodes", [])

                        if is_subagent and nodes:
                            interesting_nodes = [n for n in nodes if n in ("model_request", "tools")]
                            if interesting_nodes:
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
                                yield subagent_step_chunk(
                                    meta=meta,
                                    subagent_name=subagent_name,
                                    step=interesting_nodes[0],
                                    namespace=update_event.get("namespace", []),
                                )

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
                            yield execution_audit_chunk(meta=meta, audit_event_type=event_type, audit_event=entry)
                    continue

                is_subagent = metadata.get("is_subagent", False) if isinstance(metadata, dict) else False
                subagent_name = metadata.get("subagent_name") if isinstance(metadata, dict) else None

                if isinstance(msg, AIMessageChunk):
                    if is_subagent:
                        continue
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
                        yield interrupted_chunk(meta=meta, message="检测到敏感内容，已中断输出")
                        return

                    yield loading_chunk(
                        meta=meta,
                        content=msg.content,
                        msg=msg.model_dump(),
                        metadata=metadata,
                        is_subagent=is_subagent,
                        subagent_name=subagent_name,
                    )
                else:
                    msg_dict = msg.model_dump() if hasattr(msg, "model_dump") else msg
                    yield loading_chunk(
                        meta=meta,
                        msg=msg_dict,
                        metadata=metadata,
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
                            should_emit_state = (
                                tool_state_event_count % 3 == 0 or (now_ts - last_tool_state_emit_at) >= 1.5
                            )
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
            if await _runtime_is_cancel_requested(meta=meta):
                await _save_cancel_partial(conv_repo)
                await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_IDLE, has_interrupt=False)
                yield interrupted_chunk(meta=meta, message="运行已取消")
                return

            if (
                conf.enable_content_guard
                and hasattr(full_msg, "content")
                and await content_guard.check(full_msg.content)
            ):
                await save_partial_message(conv_repo, thread_id, full_msg, "content_guard_blocked")
                meta["time_cost"] = asyncio.get_event_loop().time() - start_time
                await _runtime_transition(
                    meta=meta,
                    next_status="failed",
                    actor_type="system",
                    actor_name="chat_stream_service",
                    reason="content_guard_blocked",
                )
                yield interrupted_chunk(meta=meta, message="检测到敏感内容，已中断输出")
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
                yield agent_state_chunk(meta=meta, agent_state=agent_state)
                await _runtime_append_event(
                    meta=meta,
                    event_type="team.execution.summary",
                    actor_type="system",
                    actor_name=team_execution_mode,
                    payload={
                        "route_count": len(agent_state.get("route_history") or []),
                        "worker_route_count": len(agent_state.get("route_log") or []),
                        "execution_log_count": len(agent_state.get("execution_log") or []),
                        "completed_agents": list(agent_state.get("completed_agents") or []),
                        "retry_counts": dict(agent_state.get("retry_counts") or {}),
                        "active_agent": agent_state.get("active_agent"),
                        "active_worker": agent_state.get("active_worker"),
                    },
                )

            await save_messages_from_langgraph_state(
                graph=state_graph,
                thread_id=thread_id,
                conv_repo=conv_repo,
                config_dict=langgraph_config,
                excluded_ai_names=excluded_ai_names,
            )
            await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_COMPLETED, has_interrupt=False)
            await _runtime_transition(
                meta=meta,
                next_status="completed",
                actor_type="system",
                actor_name="chat_stream_service",
                reason="stream_finished",
            )

            yield finished_chunk(meta=meta)

    except ThreadBusyError:
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service",
            reason="thread_busy",
        )
        yield error_chunk(meta=meta, error_type="thread_busy", error_message="当前会话正在执行中，请稍后重试")
        return

    except GraphBubbleUp:
        logger.info("LangGraph interrupt bubbled up during stream; falling back to interrupt handler.")
        conv_repo_local = locals().get("conv_repo")
        if conv_repo_local is None:
            raise

        state_graph_local = locals().get("state_graph")
        langgraph_config_local = locals().get("langgraph_config")
        if langgraph_config_local is None:
            raise
        if state_graph_local is None:
            state_graph_local = await agent.get_graph(**graph_kwargs)

        async def _mark_interrupt(_question, _operation):
            await update_thread_runtime_status(
                conv_repo_local,
                thread_id,
                RUNTIME_STATUS_WAITING_FOR_HUMAN,
                has_interrupt=True,
            )

        has_interrupt_chunk = False
        async for chunk in check_and_handle_interrupts(
            state_graph_local,
            langgraph_config_local,
            make_chunk,
            meta,
            thread_id,
            on_interrupt=_mark_interrupt,
        ):
            has_interrupt_chunk = True
            yield chunk
        if has_interrupt_chunk:
            return
        raise

    except (asyncio.CancelledError, ConnectionError) as e:
        logger.warning(f"Client disconnected, cancelling stream: {e}")
        cancel_requested = await _runtime_is_cancel_requested(meta=meta)

        async def save_cleanup():
            nonlocal full_msg
            if not full_msg and accumulated_content:
                full_msg = AIMessage(content="".join(accumulated_content))

            async with pg_manager.get_async_session_context() as new_db:
                new_conv_repo = ConversationRepository(new_db)
                if not cancel_requested:
                    await save_partial_message(
                        new_conv_repo,
                        thread_id,
                        full_msg=full_msg,
                        error_message="对话已中断" if not full_msg else None,
                        error_type="interrupted",
                    )
                else:
                    await _save_cancel_partial(new_conv_repo)
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
            reason="cancel_requested" if cancel_requested else "client_disconnected",
        )
        yield interrupted_chunk(meta=meta, message="运行已取消" if cancel_requested else "对话已中断")

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
        yield error_chunk(meta=meta, error_type=error_type, error_message=error_msg)
    finally:
        pending_agent_state_task = locals().get("pending_agent_state_task")
        if pending_agent_state_task is not None and not pending_agent_state_task.done():
            pending_agent_state_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending_agent_state_task


async def stream_agent_resume(
    *,
    agent_id: str,
    thread_id: str,
    resume_payload: dict,
    meta: dict,
    config: dict,
    current_user,
    db,
) -> AsyncIterator[bytes]:
    start_time = asyncio.get_event_loop().time()
    make_resume_chunk = make_stream_chunk_factory(meta)

    run_coordinator = RunCoordinator(db)

    try:
        prepared_run = await run_coordinator.prepare_resume_run(
            agent_id=agent_id,
            thread_id=thread_id,
            config=config,
            current_user=current_user,
        )
    except MissingDepartmentError:
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="no_department",
        )
        yield error_chunk(meta=meta, error_type="no_department", error_message="当前用户未绑定部门")
        return
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}, {traceback.format_exc()}")
        yield error_chunk(
            meta=meta,
            error_type="agent_error",
            error_message=f"Error getting agent {agent_id}: {e}",
        )
        return

    agent = prepared_run.agent

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
    yield execution_audit_chunk(
        meta=meta,
        audit_event_type="interrupt.resumed",
        audit_event={
            "type": "interrupt_resumed",
            "decision": meta.get("decision"),
            "thread_id": thread_id,
        },
    )
    yield init_chunk(meta=meta, msg=init_msg)

    resume_command = Command(resume=resume_payload)
    user_id = prepared_run.user_id
    agent_config_id = prepared_run.agent_config_id
    agent_config_context = prepared_run.agent_config
    team_execution_mode = prepared_run.team_execution_mode
    excluded_ai_names = set(prepared_run.excluded_ai_names)
    context = prepared_run.context
    graph_kwargs = prepared_run.graph_kwargs
    graph = await agent.get_graph(**graph_kwargs)

    langgraph_config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    is_dynamic_supervisor_mode = (
        agent_id == AGENT_PLATFORM_AGENT_ID
        and team_execution_mode == "supervisor"
        and bool(agent_config_context.get("subagents"))
    )
    stream_kwargs = {
        "config": langgraph_config,
        "stream_mode": "messages",
    }
    if not is_dynamic_supervisor_mode:
        stream_kwargs["context"] = context
    stream_source = graph.astream(resume_command, **stream_kwargs)
    conv_repo = ConversationRepository(db)
    full_msg = None
    accumulated_content: list[str] = []
    partial_saved_on_cancel = False

    async def _save_resume_cancel_partial(conv_repo_target: ConversationRepository):
        nonlocal full_msg, partial_saved_on_cancel
        if partial_saved_on_cancel:
            return
        if not full_msg and accumulated_content:
            full_msg = AIMessage(content="".join(accumulated_content))
        content = full_msg.content if hasattr(full_msg, "content") and full_msg else ""
        if not str(content or "").strip():
            return
        await save_partial_assistant_message(
            conv_repo_target,
            thread_id,
            str(content),
            stop_reason="cancel_requested",
        )
        partial_saved_on_cancel = True

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
        async with reserve_thread_slot(thread_id):
            async for msg, metadata in _iterate_with_next_timeout(stream_source, AGENT_STREAM_NEXT_TIMEOUT_SECONDS):
                msg_dict = msg.model_dump()
                if "id" not in msg_dict:
                    msg_dict["id"] = str(uuid.uuid4())
                msg_name = str(msg_dict.get("name") or "").strip() if isinstance(msg_dict, dict) else ""
                msg_content = msg_dict.get("content") if isinstance(msg_dict, dict) else ""
                if isinstance(msg_content, str) and msg_content and msg_name not in excluded_ai_names:
                    accumulated_content.append(msg_content)
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

                yield loading_chunk(
                    meta=meta,
                    content=getattr(msg, "content", ""),
                    msg=msg_dict,
                    metadata=metadata,
                )

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

            await save_messages_from_langgraph_state(
                graph=graph,
                thread_id=thread_id,
                conv_repo=conv_repo,
                config_dict=langgraph_config,
                excluded_ai_names=excluded_ai_names,
            )
            await update_thread_runtime_status(conv_repo, thread_id, RUNTIME_STATUS_COMPLETED, has_interrupt=False)
            await _runtime_transition(
                meta=meta,
                next_status="completed",
                actor_type="system",
                actor_name="chat_stream_service.resume",
                reason="resume_finished",
            )

            yield finished_chunk(meta=meta)

    except ThreadBusyError:
        await _runtime_transition(
            meta=meta,
            next_status="failed",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="thread_busy",
        )
        yield error_chunk(meta=meta, error_type="thread_busy", error_message="当前会话正在执行中，请稍后重试")
        return

    except GraphBubbleUp:
        logger.info("LangGraph interrupt bubbled up during resume; falling back to interrupt handler.")

        async def _mark_interrupt(_question, _operation):
            await update_thread_runtime_status(
                conv_repo,
                thread_id,
                RUNTIME_STATUS_WAITING_FOR_HUMAN,
                has_interrupt=True,
            )

        has_interrupt_chunk = False
        async for chunk in check_and_handle_interrupts(
            graph,
            langgraph_config,
            make_resume_chunk,
            meta,
            thread_id,
            on_interrupt=_mark_interrupt,
        ):
            has_interrupt_chunk = True
            yield chunk
        if has_interrupt_chunk:
            return
        raise

    except (asyncio.CancelledError, ConnectionError) as e:
        logger.warning(f"Client disconnected during resume: {e}")
        cancel_requested = await _runtime_is_cancel_requested(meta=meta)

        async with pg_manager.get_async_session_context() as new_db:
            new_conv_repo = ConversationRepository(new_db)
            if not cancel_requested:
                await save_partial_message(
                    new_conv_repo, thread_id, error_message="对话恢复已中断", error_type="resume_interrupted"
                )
            else:
                await _save_resume_cancel_partial(new_conv_repo)
            await update_thread_runtime_status(new_conv_repo, thread_id, RUNTIME_STATUS_IDLE, has_interrupt=False)

        await _runtime_transition(
            meta=meta,
            next_status="cancelled",
            actor_type="system",
            actor_name="chat_stream_service.resume",
            reason="cancel_requested" if cancel_requested else "resume_interrupted",
        )
        yield interrupted_chunk(meta=meta, message="运行已取消" if cancel_requested else "对话恢复已中断")

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
        yield error_chunk(meta=meta, error_type="resume_error", error_message=f"Error during resume: {e}")


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
    if agent_id == AGENT_PLATFORM_AGENT_ID:
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
                    input_context["agent_config"] = _resolve_runtime_agent_config(agent_id, config_item)
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

    return {"agent_state": agent_state}
