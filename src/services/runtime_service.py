from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from src.repositories.runtime_repository import RuntimeRepository
from src.utils.datetime_utils import utc_now_naive
from src.utils.logging_config import logger

TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
RUN_STATUS_FLOW = {
    "queued": {"dispatching", "running", "failed", "cancelled"},
    "dispatching": {"running", "failed", "cancelled"},
    "running": {"pausing", "paused", "completed", "failed", "cancelled"},
    "pausing": {"paused", "failed", "cancelled"},
    "paused": {"resuming", "cancelled"},
    "resuming": {"running", "failed", "cancelled"},
    "completed": set(),
    "failed": {"queued", "dispatching", "running"},
    "cancelled": set(),
}


class RuntimeService:
    def __init__(self):
        self._repo = RuntimeRepository()

    @staticmethod
    def _request_hash(payload: dict[str, Any]) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def create_run(
        self,
        *,
        agent_id: str,
        thread_id: str,
        mode: str,
        input_payload: dict[str, Any],
        idempotency_key: str,
        request_id: str | None,
        max_attempts: int,
        created_by: str,
        scope: str | None = None,
    ) -> dict[str, Any]:
        scope_key = scope or thread_id
        request_hash = self._request_hash(
            {
                "agent_id": agent_id,
                "thread_id": thread_id,
                "mode": mode,
                "input_payload": input_payload,
                "max_attempts": max_attempts,
                "created_by": created_by,
            }
        )
        existing = await self._repo.get_idempotency_record(scope_key, idempotency_key)
        if existing and existing.request_hash == request_hash and existing.run_id:
            existed_run = await self._repo.get_run(existing.run_id)
            if existed_run:
                return {
                    "run": existed_run.to_dict(),
                    "is_replay": True,
                }
        run_id = uuid.uuid4().hex
        now = utc_now_naive()
        record = await self._repo.create_run(
            {
                "run_id": run_id,
                "thread_id": thread_id,
                "request_id": request_id,
                "idempotency_key": idempotency_key,
                "mode": mode,
                "agent_id": agent_id,
                "status": "queued",
                "input_payload": input_payload,
                "max_attempts": max(1, int(max_attempts or 1)),
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            }
        )
        await self._repo.upsert_idempotency_record(
            scope_key,
            idempotency_key,
            {
                "request_hash": request_hash,
                "run_id": run_id,
                "response_payload": {"run_id": run_id, "status": "queued"},
                "created_at": now,
            },
        )
        await self.append_event(
            run_id=run_id,
            event_type="run.created",
            actor_type="system",
            actor_name="runtime_service",
            payload={"status": "queued"},
        )
        logger.info("Runtime run created run_id={} agent_id={} thread_id={}", run_id, agent_id, thread_id)
        return {"run": record.to_dict(), "is_replay": False}

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        record = await self._repo.get_run(run_id)
        if not record:
            return None
        return record.to_dict()

    async def list_runs(self, *, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        records = await self._repo.list_runs(status=status, limit=limit)
        return {"runs": [item.to_dict() for item in records], "total": len(records)}

    async def append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        actor_type: str,
        actor_name: str | None = None,
        payload: dict[str, Any] | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> dict[str, Any]:
        record = await self._repo.add_event(
            {
                "run_id": run_id,
                "event_type": event_type,
                "actor_type": actor_type,
                "actor_name": actor_name,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "event_payload": payload or {},
                "event_ts": utc_now_naive(),
            }
        )
        return record.to_dict()

    async def update_run_fields(self, run_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return await self.get_run(run_id)
        fields["updated_at"] = utc_now_naive()
        updated = await self._repo.update_run(run_id, **fields)
        if not updated:
            return None
        return updated.to_dict()

    async def list_events(
        self,
        run_id: str,
        *,
        cursor: int = 0,
        limit: int = 200,
        event_type: str | None = None,
        actor_type: str | None = None,
        actor_name: str | None = None,
    ) -> dict[str, Any]:
        records = await self._repo.list_events(
            run_id,
            cursor=cursor,
            limit=limit,
            event_type=event_type,
            actor_type=actor_type,
            actor_name=actor_name,
        )
        next_cursor = cursor
        if records:
            next_cursor = int(records[-1].seq)
        return {"items": [item.to_dict() for item in records], "next_cursor": next_cursor}

    async def transition_status(
        self,
        *,
        run_id: str,
        next_status: str,
        actor_type: str,
        actor_name: str,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        run = await self._repo.get_run(run_id)
        if run is None:
            return None
        if next_status not in RUN_STATUS_FLOW.get(run.status, set()):
            return {"error": f"Invalid status transition: {run.status} -> {next_status}"}
        now = utc_now_naive()
        fields: dict[str, Any] = {"status": next_status, "updated_at": now}
        if next_status == "running" and run.started_at is None:
            fields["started_at"] = now
        if next_status in TERMINAL_RUN_STATUSES:
            fields["finished_at"] = now
        if next_status == "cancelled":
            fields["cancel_requested"] = True
        if next_status == "resuming":
            fields["cancel_requested"] = False
            fields["paused_reason"] = None
        if next_status == "paused":
            fields["paused_reason"] = reason or "paused by user"
        updated = await self._repo.update_run(run_id, **fields)
        if not updated:
            return None
        await self.append_event(
            run_id=run_id,
            event_type=f"run.{next_status}",
            actor_type=actor_type,
            actor_name=actor_name,
            payload={"reason": reason} if reason else {},
        )
        return updated.to_dict()


runtime_service = RuntimeService()
