"""桌面发布器 worker 协议(老版 mibu-video /api/publish/worker 契约 1:1)。

执行器是本机 Electron 进程:认领 pending 的浏览器平台任务、驱动
账号内嵌视图完成上传、回报状态;账号登录态巡检同理。后端是唯一
事实源,worker 无状态。同账号任务必须串行(共享一个登录视图),
所以 claim 支持 exclude_accounts。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Job, PublishAccount, PublishTask, TaskEvent, now
from app.domain.notifications import notify
from app.domain.publish import (
    BINDING_STATUSES,
    PUBLISH_PLATFORMS,
    TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    PublishDomainError,
)
from app.media.paths import resolve_key

# 登录态复检间隔:bound/login_required 的账号超过该时长未查就该复检。
BINDING_RECHECK_HOURS = 3

_last_heartbeat: float | None = None


def heartbeat() -> None:
    global _last_heartbeat
    _last_heartbeat = time.monotonic()


def worker_online() -> bool:
    return _last_heartbeat is not None and (time.monotonic() - _last_heartbeat) < 30


def _browser_platforms() -> list[str]:
    return [key for key, meta in PUBLISH_PLATFORMS.items() if meta.get("executor") == "browser"]


def claim_next_pending(db: Session, exclude_accounts: list[str]) -> dict[str, Any] | None:
    """认领最老的一条 pending 浏览器任务并翻成 running。

    单进程 SQLite 后端 + 单个 worker:同事务内 select→update 即原子。
    """
    stmt = (
        select(PublishTask, PublishAccount)
        .join(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(
            PublishTask.status == "pending",
            PublishAccount.platform.in_(_browser_platforms()),
            PublishAccount.enabled.is_(True),
        )
        .order_by(PublishTask.created_at)
    )
    if exclude_accounts:
        stmt = stmt.where(PublishTask.account_id.not_in(exclude_accounts))
    row = db.execute(stmt.limit(1)).first()
    if row is None:
        return None
    task, account = row
    asset = db.get(Asset, task.asset_id)
    if asset is None or not asset.file_key:
        task.status = "failed"
        task.error_message = "素材文件缺失"
        _sync_job(db, task)
        db.commit()
        return None

    task.status = "running"
    if task.job_id:
        job = db.get(Job, task.job_id)
        if job is not None:
            job.status = "running"
            job.message = f"桌面发布器执行中: {task.title or asset.name}"
    db.commit()
    return {
        "id": task.id,
        "account_id": account.id,
        "account_name": account.name,
        "platform": account.platform,
        "video_path": str(resolve_key(asset.file_key)),
        "title": task.title,
        "tags": list(task.tags or []),
        "description": task.description,
        "short_title": task.short_title,
        "dry_run": False,
        "status": task.status,
    }


def report_task(
    db: Session,
    *,
    task_id: str,
    status: str,
    error_message: str | None = None,
    screenshot_path: str | None = None,
) -> PublishTask:
    if status not in TASK_STATUSES:
        raise PublishDomainError(f"未知任务状态: {status}")
    task = db.get(PublishTask, task_id)
    if task is None:
        raise PublishDomainError("任务不存在")
    if task.status == "cancelled":
        # 已取消的任务不给后到的 worker 回报复活(老版规则)。
        return task
    previous = task.status
    task.status = status
    task.error_message = error_message
    task.screenshot_path = screenshot_path
    _sync_job(db, task)
    if status != previous:
        _notify_status(db, task)
    db.commit()
    db.refresh(task)
    return task


# 状态跃迁 → 通知文案;running/pending 之类的中间态不打扰。
_NOTIFY_TITLES = {
    "success": "发布成功",
    "prepared": "发布已就绪(待手动确认)",
    "failed": "发布失败",
    "login_required": "发布需要重新登录",
    "waiting_manual": "发布等待人工处理",
    "permission_required": "发布权限不足",
    "blocked": "发布被平台拦截",
}


def _notify_status(db: Session, task: PublishTask) -> None:
    title = _NOTIFY_TITLES.get(task.status)
    if title is None:
        return
    account = db.get(PublishAccount, task.account_id)
    notify(
        db,
        task.workspace_id,
        type="publish",
        title=f"{title}: {task.title}",
        body=task.error_message or "",
        link="#/publish",
        payload={"task_id": task.id, "platform": account.platform if account else "", "status": task.status},
    )


def _sync_job(db: Session, task: PublishTask) -> None:
    """把任务富状态映射到任务总线 job(供任务中心/工作流等待方消费)。"""
    if not task.job_id:
        return
    job = db.get(Job, task.job_id)
    if job is None:
        return
    if task.status in ("success", "prepared"):
        job.status = "succeeded"
        job.progress = 1.0
        job.message = f"发布完成: {task.title}"
        job.result = {"platform_status": task.status}
        db.add(TaskEvent(job_id=job.id, type="publish.finished", payload={"status": task.status}))
    elif task.status in ("failed", "cancelled"):
        job.status = "failed"
        job.error = task.error_message or task.status
        job.message = "发布失败" if task.status == "failed" else "发布已取消"
        db.add(TaskEvent(job_id=job.id, type="publish.failed", payload={"status": task.status, "error": job.error}))
    else:
        job.status = "running"
        job.message = f"发布 {task.status}: {task.title}"
        db.add(TaskEvent(job_id=job.id, type="publish.status", payload={"status": task.status}))


def claim_check(db: Session) -> dict[str, Any] | None:
    """认领一个该复检登录态的账号(unknown,或 bound/login_required 且太久没查)。"""
    cutoff = now() - timedelta(hours=BINDING_RECHECK_HOURS)
    stmt = (
        select(PublishAccount)
        .where(
            PublishAccount.platform.in_(_browser_platforms()),
            PublishAccount.enabled.is_(True),
        )
        .order_by(PublishAccount.last_checked_at.asc().nulls_first())
    )
    stale_checking = now() - timedelta(minutes=10)
    for account in db.scalars(stmt):
        due = (
            account.binding_status == "unknown"
            or (
                account.binding_status in ("bound", "login_required")
                and (account.last_checked_at is None or account.last_checked_at < cutoff)
            )
            # 自愈:复检中途执行器崩溃/出错会把账号永远留在 checking(不在任何
            # 认领条件里)。超过 10 分钟的 checking 视为悬挂,重新认领。
            or (
                account.binding_status == "checking"
                and (account.last_checked_at is None or account.last_checked_at < stale_checking)
            )
        )
        if due:
            previous = account.binding_status
            account.binding_status = "checking"
            account.last_checked_at = now()
            db.commit()
            return {
                "account_id": account.id,
                "platform": account.platform,
                "name": account.name,
                "binding_status": previous,
            }
    return None


def mark_due(db: Session) -> int:
    """全量巡检:清空 last_checked_at,让每个浏览器账号都进入待复检(worker 开机时调)。"""
    accounts = db.scalars(
        select(PublishAccount).where(PublishAccount.platform.in_(_browser_platforms()))
    ).all()
    for account in accounts:
        account.last_checked_at = None
    db.commit()
    return len(accounts)


def patch_account(
    db: Session,
    *,
    account_id: str,
    binding_status: str | None = None,
    last_error: str | None = None,
    profile_name: str | None = None,
) -> PublishAccount:
    account = db.get(PublishAccount, account_id)
    if account is None:
        raise PublishDomainError("账号不存在")
    if binding_status is not None:
        if binding_status not in BINDING_STATUSES:
            raise PublishDomainError(f"未知登录态: {binding_status}")
        account.binding_status = binding_status
        account.last_checked_at = now()
    account.last_error = last_error
    if profile_name is not None:
        account.profile_name = profile_name[:120]
    db.commit()
    db.refresh(account)
    return account
