from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.db.models import PublishAccount
from app.domain.publish import PublishDomainError
from app.domain.publish import worker as publish_worker

"""桌面发布器 worker 通道(老版契约 1:1)。

免登录鉴权:执行器是本机无 token 的 Electron 进程,后端只监听
127.0.0.1 —— 与老版相同的信任边界。
"""

router = APIRouter(tags=["publish-worker"])


class ClaimRequest(BaseModel):
    exclude_accounts: list[str] = Field(default_factory=list)


class ReportRequest(BaseModel):
    task_id: str
    status: str
    error_message: str | None = None
    screenshot_path: str | None = None


class AccountPatchRequest(BaseModel):
    account_id: str
    binding_status: str | None = None
    last_error: str | None = None
    profile_name: str | None = None


@router.post("/publish/worker/claim")
def claim(body: ClaimRequest, db: DbSession) -> dict[str, Any]:
    return {"task": publish_worker.claim_next_pending(db, body.exclude_accounts)}


@router.patch("/publish/worker/report")
def report(body: ReportRequest, db: DbSession) -> dict[str, Any]:
    try:
        task = publish_worker.report_task(
            db,
            task_id=body.task_id,
            status=body.status,
            error_message=body.error_message,
            screenshot_path=body.screenshot_path,
        )
    except PublishDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": task.id, "status": task.status}


@router.post("/publish/worker/claim-check")
def claim_check(db: DbSession) -> dict[str, Any]:
    return {"account": publish_worker.claim_check(db)}


@router.post("/publish/worker/mark-due")
def mark_due(db: DbSession) -> dict[str, Any]:
    return {"marked": publish_worker.mark_due(db)}


@router.patch("/publish/worker/account")
def patch_account(body: AccountPatchRequest, db: DbSession) -> dict[str, Any]:
    try:
        account = publish_worker.patch_account(
            db,
            account_id=body.account_id,
            binding_status=body.binding_status,
            last_error=body.last_error,
            profile_name=body.profile_name,
        )
    except PublishDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": account.id, "binding_status": account.binding_status}


@router.get("/publish/worker/account/{account_id}")
def worker_account(account_id: str, db: DbSession) -> dict[str, Any]:
    """执行器打开某账号视图前拿它的连接参数(目前只有 proxy)。"""
    account = db.get(PublishAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"id": account.id, "proxy": account.proxy}


@router.post("/publish/worker/heartbeat")
def heartbeat() -> dict[str, Any]:
    publish_worker.heartbeat()
    return {"ok": True}


@router.get("/publish/worker/status")
def status() -> dict[str, Any]:
    return {"online": publish_worker.worker_online()}
