from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select

from src.storage.postgres.manager import pg_manager
from src.storage.postgres.models_business import AgentRun, IdempotencyRecord, RunEvent


def _ensure_pg_manager_initialized() -> None:
    if not pg_manager._initialized:
        pg_manager.initialize()


class RuntimeRepository:
    async def create_run(self, run_data: dict[str, Any]) -> AgentRun:
        _ensure_pg_manager_initialized()
        async with pg_manager.get_async_session_context() as session:
            record = AgentRun(**run_data)
            session.add(record)
            return record

    async def get_run(self, run_id: str) -> AgentRun | None:
        _ensure_pg_manager_initialized()
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(AgentRun).where(AgentRun.run_id == run_id))
            return result.scalar_one_or_none()

    async def update_run(self, run_id: str, **fields: Any) -> AgentRun | None:
        _ensure_pg_manager_initialized()
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(AgentRun).where(AgentRun.run_id == run_id))
            record = result.scalar_one_or_none()
            if record is None:
                return None
            for key, value in fields.items():
                setattr(record, key, value)
            return record

    async def list_runs(self, *, status: str | None = None, limit: int = 100) -> list[AgentRun]:
        _ensure_pg_manager_initialized()
        async with pg_manager.get_async_session_context() as session:
            stmt = select(AgentRun)
            if status:
                stmt = stmt.where(AgentRun.status == status)
            stmt = stmt.order_by(AgentRun.created_at.desc()).limit(max(limit, 0))
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def add_event(self, event_data: dict[str, Any]) -> RunEvent:
        _ensure_pg_manager_initialized()
        run_id = str(event_data.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id is required for add_event")

        explicit_seq = event_data.get("seq")
        max_retries = 5
        for attempt in range(max_retries):
            async with pg_manager.get_async_session_context() as session:
                try:
                    # Serialize per-run sequence allocation when database supports row locking.
                    await session.execute(select(AgentRun.run_id).where(AgentRun.run_id == run_id).with_for_update())
                    if explicit_seq is None:
                        result = await session.execute(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id))
                        seq = int(result.scalar_one_or_none() or 0) + 1
                    else:
                        seq = int(explicit_seq)
                    payload = dict(event_data)
                    payload["seq"] = seq
                    record = RunEvent(**payload)
                    session.add(record)
                    await session.flush()
                    return record
                except IntegrityError:
                    await session.rollback()
                    if attempt >= max_retries - 1:
                        raise
        raise RuntimeError(f"failed to add event for run_id={run_id}")

    async def list_events(
        self,
        run_id: str,
        *,
        cursor: int = 0,
        limit: int = 200,
        event_type: str | None = None,
        actor_type: str | None = None,
        actor_name: str | None = None,
    ) -> list[RunEvent]:
        _ensure_pg_manager_initialized()
        async with pg_manager.get_async_session_context() as session:
            stmt = select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > max(0, cursor))
            if event_type:
                stmt = stmt.where(RunEvent.event_type == event_type)
            if actor_type:
                stmt = stmt.where(RunEvent.actor_type == actor_type)
            if actor_name:
                stmt = stmt.where(RunEvent.actor_name.ilike(f"%{actor_name}%"))
            stmt = stmt.order_by(RunEvent.seq.asc()).limit(max(limit, 0))
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_idempotency_record(self, scope: str, idem_key: str) -> IdempotencyRecord | None:
        _ensure_pg_manager_initialized()
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idem_key == idem_key,
                )
            )
            return result.scalar_one_or_none()

    async def upsert_idempotency_record(self, scope: str, idem_key: str, data: dict[str, Any]) -> IdempotencyRecord:
        _ensure_pg_manager_initialized()
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idem_key == idem_key,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                record = IdempotencyRecord(scope=scope, idem_key=idem_key, **data)
                session.add(record)
                return record
            for key, value in data.items():
                setattr(record, key, value)
            return record
