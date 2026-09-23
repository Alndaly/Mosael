from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.db.models import PublishAccount, PublishTask
from app.domain.publish import PublishDomainError
from app.domain.publish import worker as publish_worker

"""桌面发布器 worker 通道(老版契约 1:1)。

鉴权:执行器是本机无用户会话的 Electron 进程,凭启动时下发的共享密钥
(X-Mosael-Worker-Key)通过 require_worker_key 校验 —— 只监听
127.0.0.1 挡不住浏览器跨域 POST,密钥才是边界。见 app/core/worker_key.py;
依赖在 main.py 挂路由时统一注入。
"""

router = APIRouter(tags=["publish-worker"])


class ClaimRequest(BaseModel):
    exclude_accounts: list[str] = Field(default_factory=list)
    #: 执行器的稳定身份(跨重启不变)。多执行器下用它分辨任务归属 —— 见
    #: publish/worker.reclaim_orphaned_running。
    #:
    #: **必填。** 此前它可空,读路径那边配一条「为空 = 老执行器不报身份」的兼容分支 ——
    #: 而执行器就在这个仓库里、跟后端**同一个安装包**发布,`readWorkerId()`
    #: (electron/publish/publishBackend.ts)永远返回一个非空 id(环境变量 → 落盘的文件 →
    #: 现生成一个 uuid)。所以那条分支在这个产品里永远走不到,它只是给"两个执行器会互相把
    #: 对方的任务判成孤儿"这个已经想清楚的问题留了一个**假的例外口**。
    #:
    #: 一旦接受"给同包发布的客户端留版本分支"这个理由,worker 协议以后每加一个字段都会再长一条。
    worker: str = Field(min_length=1, max_length=64)


class ReportRequest(BaseModel):
    task_id: str
    status: str
    error_message: str | None = None
    screenshot_path: str | None = None
    #: 发成功时读到的那条作品:{post_id, url, ids}。逐项收窄在 domain/publish/post.py。
    post: dict[str, Any] | None = None


class AccountPatchRequest(BaseModel):
    account_id: str
    binding_status: str | None = None
    last_error: str | None = None


@router.post("/publish/worker/claim")
def claim(body: ClaimRequest, db: DbSession) -> dict[str, Any]:
    return {"task": publish_worker.claim_next_pending(db, body.exclude_accounts, worker=body.worker)}


@router.get("/publish/worker/task/{task_id}")
def task_status(task_id: str, db: DbSession) -> dict[str, Any]:
    task = db.get(PublishTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"id": task.id, "status": task.status}


@router.patch("/publish/worker/report")
def report(body: ReportRequest, db: DbSession) -> dict[str, Any]:
    try:
        task = publish_worker.report_task(
            db,
            task_id=body.task_id,
            status=body.status,
            error_message=body.error_message,
            screenshot_path=body.screenshot_path,
            post=body.post,
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
