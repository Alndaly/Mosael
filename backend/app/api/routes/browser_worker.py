"""浏览器自动化 worker 通道:claim / report / heartbeat。

与发布/通用 job worker 同一信任边界:X-Mosael-Worker-Key(本机 0600 文件),在 main.py 挂载处统一
加依赖。Electron 的浏览器 worker 拉取 queued 动作、执行、回报;后端从不反向连接执行器。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbSession
from app.domain.browser import claim_next_action, report_action

router = APIRouter(tags=["browser-worker"])


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
    """执行器报「我还在」。

    **这里不记任何东西。** 曾经有一个 `_HEARTBEATS` 字典写进去 —— 全仓零个读者,而它按
    worker 名字无限长。租约续期走的是任务行上的 lease,不看这个字典;而"执行器在不在"
    这个问题在发布那条链上由 `domain/publish/worker.worker_online()` 回答(有人读)。
    留着这条路由是因为执行器确实会打它,而 404 会被它当成后端出问题。
    """
    _ = body
    return {"ok": True}
