from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from server.utils.auth_middleware import get_required_user
from src.services.runtime_service import runtime_service
from src.storage.postgres.models_business import User

runtime = APIRouter(prefix="/runtime", tags=["runtime"])


class CreateRunRuntimeOptions(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=10)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)


class CreateRunRequest(BaseModel):
    agent_id: str
    thread_id: str
    mode: str = "hybrid"
    input: dict[str, Any] = Field(default_factory=dict)
    runtime_options: CreateRunRuntimeOptions = Field(default_factory=CreateRunRuntimeOptions)
    request_id: str | None = None
    scope: str | None = None


class RetryRunRequest(BaseModel):
    from_step: str | None = None
    reason: str | None = None


class ResumeRunRequest(BaseModel):
    reason: str | None = None


@runtime.post("/runs")
async def create_run(
    body: CreateRunRequest,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    current_user: User = Depends(get_required_user),
):
    if not x_idempotency_key:
        raise HTTPException(status_code=400, detail="Missing X-Idempotency-Key header")
    result = await runtime_service.create_run(
        agent_id=body.agent_id,
        thread_id=body.thread_id,
        mode=body.mode,
        input_payload=body.input | {"timeout_seconds": body.runtime_options.timeout_seconds},
        idempotency_key=x_idempotency_key,
        request_id=body.request_id,
        max_attempts=body.runtime_options.max_attempts,
        created_by=str(current_user.id),
        scope=body.scope,
    )
    return {
        "run_id": result["run"]["run_id"],
        "status": result["run"]["status"],
        "is_replay": result["is_replay"],
    }


@runtime.get("/runs")
async def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_required_user),
):
    payload = await runtime_service.list_runs(status=status, limit=limit)
    return payload


@runtime.get("/runs/{run_id}")
async def get_run(run_id: str, current_user: User = Depends(get_required_user)):
    run = await runtime_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("created_by") not in {str(current_user.id), None} and current_user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="No permission to access this run")
    return run


@runtime.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    event_type: str | None = Query(default=None),
    actor_type: str | None = Query(default=None),
    actor_name: str | None = Query(default=None),
    current_user: User = Depends(get_required_user),
):
    run = await runtime_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("created_by") not in {str(current_user.id), None} and current_user.role not in {"admin", "superadmin"}:
        raise HTTPException(status_code=403, detail="No permission to access this run")
    normalized_actor_name = actor_name.strip() if actor_name else None
    return await runtime_service.list_events(
        run_id,
        cursor=cursor,
        limit=limit,
        event_type=event_type,
        actor_type=actor_type,
        actor_name=normalized_actor_name or None,
    )


@runtime.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, current_user: User = Depends(get_required_user)):
    result = await runtime_service.transition_status(
        run_id=run_id,
        next_status="cancelled",
        actor_type="user",
        actor_name=str(current_user.id),
        reason="cancel requested",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return {"run_id": run_id, "status": "cancelled"}


@runtime.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, body: ResumeRunRequest, current_user: User = Depends(get_required_user)):
    result = await runtime_service.transition_status(
        run_id=run_id,
        next_status="resuming",
        actor_type="user",
        actor_name=str(current_user.id),
        reason=body.reason or "resume requested",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return {"run_id": run_id, "status": "resuming"}


@runtime.post("/runs/{run_id}/retry")
async def retry_run(run_id: str, body: RetryRunRequest, current_user: User = Depends(get_required_user)):
    result = await runtime_service.transition_status(
        run_id=run_id,
        next_status="queued",
        actor_type="user",
        actor_name=str(current_user.id),
        reason=body.reason or "retry requested",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    await runtime_service.append_event(
        run_id=run_id,
        event_type="supervisor.retry",
        actor_type="user",
        actor_name=str(current_user.id),
        payload={"from_step": body.from_step, "reason": body.reason},
    )
    return {"run_id": run_id, "status": "queued"}
