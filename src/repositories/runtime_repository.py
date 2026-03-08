from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from src.storage.postgres.manager import pg_manager
from src.storage.postgres.models_business import AgentRun, IdempotencyRecord, RunEvent


class RuntimeRepository:
    async def create_run(self, run_data: dict[str, Any]) -> AgentRun:
        async with pg_manager.get_async_session_context() as session:
            record = AgentRun(**run_data)
            session.add(record)
            return record

    async def get_run(self, run_id: str) -> AgentRun | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(AgentRun).where(AgentRun.run_id == run_id))
            return result.scalar_one_or_none()

    async def update_run(self, run_id: str, **fields: Any) -> AgentRun | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(AgentRun).where(AgentRun.run_id == run_id))
            record = result.scalar_one_or_none()
            if record is None:
                return None
            for key, value in fields.items():
                setattr(record, key, value)
            return record

    async def list_runs(self, *, status: str | None = None, limit: int = 100) -> list[AgentRun]:
        async with pg_manager.get_async_session_context() as session:
            stmt = select(AgentRun)
            if status:
                stmt = stmt.where(AgentRun.status == status)
            stmt = stmt.order_by(AgentRun.created_at.desc()).limit(max(limit, 0))
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_next_event_seq(self, run_id: str) -> int:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id))
            max_seq = result.scalar_one_or_none()
            return int(max_seq or 0) + 1

    async def add_event(self, event_data: dict[str, Any]) -> RunEvent:
        async with pg_manager.get_async_session_context() as session:
            record = RunEvent(**event_data)
            session.add(record)
            return record

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
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idem_key == idem_key,
                )
            )
            return result.scalar_one_or_none()

    async def upsert_idempotency_record(self, scope: str, idem_key: str, data: dict[str, Any]) -> IdempotencyRecord:
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
