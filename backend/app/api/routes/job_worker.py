"""通用 job worker 通道:claim / report / heartbeat。

发布器验证过的拉取协议,推广到任意 external kind(见 app/domain/jobs.py 的执行模式
接缝)。鉴权与发布 worker 相同:X-Mosael-Worker-Key(本地文件信任边界),在 main.py
挂载处统一加依赖。publish 因历史契约仍走 /api/publish/worker/*。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.db.models import Job
from app.domain.jobs import claim_next_job, external_kinds, renew_worker_leases, report_job

router = APIRouter(tags=["job-worker"])

# worker_id → {last_seen, kinds};进程内即可(worker 在线状态本就随后端进程存在)。
_HEARTBEATS: dict[str, dict[str, Any]] = {}


class ClaimRequest(BaseModel):
    worker: str = Field(default="", max_length=64)
    kinds: list[str] = Field(default_factory=list)


class ReportRequest(BaseModel):
    job_id: str
    status: str
    lease_token: str | None = Field(default=None, max_length=64)
    progress: float | None = None
    message: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None


class LeaseClaim(BaseModel):
    job_id: str
    lease_token: str = Field(min_length=1, max_length=64)


class HeartbeatRequest(BaseModel):
    claims: list[LeaseClaim] = Field(default_factory=list, max_length=1000)
    worker: str = Field(max_length=64)
    kinds: list[str] = Field(default_factory=list)


@router.post("/jobs/worker/claim")
def claim(body: ClaimRequest, db: DbSession) -> dict[str, Any]:
    job = claim_next_job(db, kinds=body.kinds or None, worker=body.worker)
    if job is None:
        return {"job": None}
    return {
        "job": {
            "id": job.id,
            "kind": job.kind,
            "workspace_id": job.workspace_id,
            "payload": job.payload or {},
            "lease_token": job.lease_token,
            "lease_expires_at": job.lease_expires_at.isoformat() + "Z",
        }
    }


@router.patch("/jobs/worker/report")
def report(body: ReportRequest, db: DbSession) -> dict[str, Any]:
    job = db.get(Job, body.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 不存在")
    try:
        job = report_job(
            db,
            job,
            status=body.status,
            lease_token=body.lease_token,
            progress=body.progress,
            message=body.message,
            error=body.error,
            result=body.result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": job.id, "status": job.status, "progress": job.progress}


@router.post("/jobs/worker/heartbeat")
def heartbeat(body: HeartbeatRequest, db: DbSession) -> dict[str, Any]:
    _HEARTBEATS[body.worker] = {"last_seen": time.time(), "kinds": list(body.kinds)}
    renewed = renew_worker_leases(db, worker=body.worker, claims=[claim.model_dump() for claim in body.claims])
    return {"ok": True, "external_kinds": list(external_kinds()), "renewed": renewed}
