from __future__ import annotations

import json

from src.services.runtime_service import runtime_service
from src.utils.logging_config import logger


def resolve_stream_event(chunk: dict) -> str:
    if not isinstance(chunk, dict):
        return "stream.unknown"

    explicit_event = str(chunk.get("event") or "").strip()
    if explicit_event:
        return explicit_event

    status = str(chunk.get("status") or "").strip()
    if not status:
        return "stream.unknown"

    if status == "execution_audit":
        return str(chunk.get("audit_event_type") or "execution.audit")
    if status == "subagent_step":
        return "worker.progress"
    if status == "agent_state":
        return "state.snapshot"
    if status == "human_approval_required":
        return "interrupt.requested"
    if status == "init":
        return "run.started"
    if status == "finished":
        return "run.completed"
    if status == "interrupted":
        return "run.interrupted"
    if status == "error":
        return "run.failed"
    if status == "loading":
        msg = chunk.get("msg")
        if isinstance(msg, dict) and str(msg.get("type") or "").strip() == "tool":
            return "tool.completed"
        return "message.chunk"
    return f"stream.{status}"


def encode_stream_chunk(*, meta: dict | None, content=None, **kwargs) -> bytes:
    chunk = {
        "request_id": (meta or {}).get("request_id") if isinstance(meta, dict) else None,
        "response": content,
        **kwargs,
    }
    if "event" not in chunk or not str(chunk.get("event") or "").strip():
        chunk["event"] = resolve_stream_event(chunk)
    return json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n"


def make_stream_chunk_factory(meta: dict | None):
    def _make_chunk(content=None, **kwargs):
        return encode_stream_chunk(meta=meta, content=content, **kwargs)

    return _make_chunk


def init_chunk(*, meta: dict | None, msg: dict) -> bytes:
    return encode_stream_chunk(meta=meta, status="init", msg=msg)


def loading_chunk(
    *,
    meta: dict | None,
    content=None,
    msg: dict | None = None,
    metadata: dict | None = None,
    is_subagent: bool | None = None,
    subagent_name: str | None = None,
) -> bytes:
    payload = {
        "status": "loading",
        "msg": msg,
        "metadata": metadata,
    }
    if is_subagent is not None:
        payload["is_subagent"] = is_subagent
    if subagent_name is not None:
        payload["subagent_name"] = subagent_name
    return encode_stream_chunk(meta=meta, content=content, **payload)


def error_chunk(
    *,
    meta: dict | None,
    error_type: str,
    error_message: str,
    message: str | None = None,
) -> bytes:
    return encode_stream_chunk(
        meta=meta,
        status="error",
        error_type=error_type,
        error_message=error_message,
        message=message,
    )


def interrupted_chunk(*, meta: dict | None, message: str) -> bytes:
    return encode_stream_chunk(meta=meta, status="interrupted", message=message)


def finished_chunk(*, meta: dict | None) -> bytes:
    return encode_stream_chunk(meta=meta, status="finished")


def agent_state_chunk(*, meta: dict | None, agent_state: dict) -> bytes:
    return encode_stream_chunk(meta=meta, status="agent_state", agent_state=agent_state)


def subagent_step_chunk(
    *,
    meta: dict | None,
    subagent_name: str,
    step: str,
    namespace: list | None = None,
) -> bytes:
    return encode_stream_chunk(
        meta=meta,
        status="subagent_step",
        subagent_name=subagent_name,
        step=step,
        namespace=namespace or [],
    )


def execution_audit_chunk(
    *,
    meta: dict | None,
    audit_event_type: str,
    audit_event: dict,
) -> bytes:
    return encode_stream_chunk(
        meta=meta,
        status="execution_audit",
        audit_event_type=audit_event_type,
        audit_event=audit_event,
        event=audit_event_type,
    )


def human_approval_required_chunk(
    *,
    meta: dict | None,
    message: str,
    thread_id: str,
    interrupt_info: dict,
) -> bytes:
    return encode_stream_chunk(
        meta=meta,
        status="human_approval_required",
        message=message,
        thread_id=thread_id,
        interrupt_info=interrupt_info,
        event="interrupt.requested",
    )


def extract_run_id(meta: dict | None) -> str | None:
    if not isinstance(meta, dict):
        return None
    run_id = meta.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    return None


async def runtime_append_event(
    *,
    meta: dict | None,
    event_type: str,
    actor_type: str,
    actor_name: str,
    payload: dict | None = None,
) -> None:
    run_id = extract_run_id(meta)
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


async def runtime_transition(
    *,
    meta: dict | None,
    next_status: str,
    actor_type: str,
    actor_name: str,
    reason: str | None = None,
) -> None:
    run_id = extract_run_id(meta)
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


async def runtime_sync_run_mode(*, meta: dict | None, mode: str) -> None:
    run_id = extract_run_id(meta)
    normalized_mode = str(mode or "").strip()
    if not run_id or not normalized_mode:
        return
    try:
        await runtime_service.update_run_fields(run_id, mode=normalized_mode)
    except Exception as exc:
        logger.debug(f"Skip runtime mode sync for run `{run_id}`: {exc}")


async def runtime_is_cancel_requested(*, meta: dict | None) -> bool:
    run_id = extract_run_id(meta)
    if not run_id:
        return False
    try:
        run = await runtime_service.get_run(run_id)
    except Exception as exc:
        logger.debug(f"Skip runtime cancel check for run `{run_id}`: {exc}")
        return False
    if not run:
        return False
    return bool(run.get("cancel_requested")) or str(run.get("status") or "") == "cancelled"


def extract_agent_state(values: dict, *, include_attachment_content: bool = False) -> dict:
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

    return {
        "todos": list(todos)[:20] if todos else [],
        "files": files,
        "execution_log": list(values.get("execution_log") or [])[-50:],
        "route_history": list(values.get("route_history") or [])[-50:],
        "route_log": list(values.get("route_log") or [])[-50:],
        "completed_agents": list(values.get("completed_agents") or []),
        "retry_counts": dict(values.get("retry_counts") or {}),
        "active_agent": values.get("active_agent"),
        "active_worker": values.get("active_worker"),
        "stage_outputs": dict(values.get("stage_outputs") or {}),
    }


def collect_supervisor_execution_entries(update_event: dict) -> list[dict]:
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


def supervisor_entry_fingerprint(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)


def map_supervisor_entry_to_runtime_event(entry_type: str) -> str:
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


def collect_worker_route_entries(agent_state: dict, *, emitted_count: int = 0) -> tuple[list[dict], int]:
    if not isinstance(agent_state, dict):
        return [], emitted_count

    route_log = agent_state.get("route_log")
    if not isinstance(route_log, list):
        return [], emitted_count

    entries: list[dict] = []
    start_index = max(0, int(emitted_count))
    for index, worker_name in enumerate(route_log[start_index:], start=start_index):
        if not isinstance(worker_name, str) or not worker_name.strip():
            continue
        entries.append(
            {
                "type": "worker_route",
                "worker": worker_name.strip(),
                "index": index,
            }
        )
    return entries, len(route_log)
