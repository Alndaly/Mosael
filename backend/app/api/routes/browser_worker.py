"""浏览器自动化 worker 通道:claim / report / heartbeat。

与发布/通用 job worker 同一信任边界:X-Mosael-Worker-Key(本机 0600 文件),在 main.py 挂载处统一
加依赖。Electron 的浏览器 worker 拉取 queued 动作、执行、回报;后端从不反向连接执行器。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbSession
from app.domain.browser import claim_next_action, report_action

router = APIRouter(tags=["browser-worker"])

# worker_id → last_seen(进程内即可)。
_HEARTBEATS: dict[str, float] = {}


class ClaimRequest(BaseModel):
    worker: str = ""


class ReportRequest(BaseModel):
    action_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    last_url: str | None = None


class HeartbeatRequest(BaseModel):
    worker: str = ""


@router.post("/browser/worker/claim")
def claim(body: ClaimRequest, db: DbSession) -> dict[str, Any]:
    action = claim_next_action(db, worker=body.worker)
    return {"action": action}


@router.patch("/browser/worker/report")
def report(body: ReportRequest, db: DbSession) -> dict[str, Any]:
    try:
        act = report_action(
            db,
            body.action_id,
            status=body.status,
            result=body.result,
            error=body.error,
            last_url=body.last_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": act.id, "status": act.status}


@router.post("/browser/worker/heartbeat")
def heartbeat(body: HeartbeatRequest) -> dict[str, Any]:
    _HEARTBEATS[body.worker or "browser"] = time.time()
    return {"ok": True}
