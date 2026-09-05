"""预览代理的**业务侧**:什么时候该生成、算不算一次任务、素材状态怎么改。

从 `app/media/proxy.py` 搬出来的。转码本身(ffmpeg 怎么调、并发几路)留在那边 —— 那是适配器
该管的;而建任务、发任务事件、把 `asset.media_info` 改成 pending/ready/failed,是业务决策。

挤在一起时,`media` 反过来 import 了 `domain.jobs`:一个只该会干活的层认识了业务。方向反了
的直接代价是 `media` 用不了 —— 想在别处只调一次转码,会把整个任务系统拖进来。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.jobs import create_job, dispatch_job, emit_job_event, run_job_guarded, say
from app.media.paths import resolve_key
from app.media.proxy import PROXY_NAME, TRANSCODE_SLOTS, build_proxy, proxy_path


def proxy_key_for(asset: Asset) -> str:
    """Storage key of the proxy sibling to the asset's own file."""
    return str(Path(asset.file_key).parent / PROXY_NAME)


def proxy_status(asset: Asset) -> str:
    """pending | ready | failed | none (not a video, or proxies disabled)."""
    return str((asset.media_info or {}).get("proxy_status") or "none")


def _set_proxy_meta(db: Session, asset_id: str, status: str, *, key: str | None = None) -> None:
    """Reassign media_info (a plain JSON column) so SQLAlchemy tracks the change."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        return
    info = dict(asset.media_info or {})
    info["proxy_status"] = status
    if key is not None:
        info["proxy_key"] = key
    elif status != "ready":
        info.pop("proxy_key", None)
    asset.media_info = info
    db.commit()


def start_proxy_job(db: Session, asset: Asset, *, created_by: str | None, force: bool = False) -> Job | None:
    """Queue proxy generation for a video asset (in-process daemon thread).

    No-op (returns None) when proxies are disabled, the asset isn't a file-backed
    video, or a proxy is already ready/in-flight (unless `force`).
    """
    if not settings.generate_proxies or asset.kind != "video" or not asset.file_key:
        return None
    if not force and proxy_status(asset) in ("ready", "pending"):
        return None
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="proxy",
        created_by=created_by,
        payload={"asset_id": asset.id, "subject": asset.name},
        message="jobMsg_proxyQueued",
    )
    info = dict(asset.media_info or {})
    info["proxy_status"] = "pending"
    info.pop("proxy_key", None)
    asset.media_info = info
    db.commit()
    # 经总线派发。此前这里是一句裸的线程创建 —— 线程没有 JOB_THREAD_NAME,
    # `wait_for_idle_jobs()` 按名字找不到它(测试里 fresh_client() 就会在它还活着时
    # drop_all),而且这个 kind 的执行模式形同虚设:注册成 external 也照样在进程内跑。
    dispatch_job(db, job, lambda: _run_proxy(job.id, asset.id))
    return job


def _run_proxy(job_id: str, asset_id: str) -> None:
    """Wait for a transcode slot BEFORE opening a database session.

    The slot used to be taken inside the session, so every queued worker sat in the semaphore
    while holding a pooled connection. The pool is 5 + 10 overflow with a 30s checkout timeout,
    so a startup backfill of 60 videos put 45 threads into that timeout — each dying with its
    job still `queued` and nothing to reconcile it. Queueing on the semaphore costs a sleeping
    thread; queueing on the connection pool costs the job.
    """
    with TRANSCODE_SLOTS:
        run_job_guarded(job_id, lambda: _proxy_body(job_id, asset_id), what="代理生成")


def _proxy_body(job_id: str, asset_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            job.status = "running"
            say(job, "jobMsg_proxyRunning")
            job.progress = 0.1
            emit_job_event(db, job.id, "job.running", {})
            db.commit()

            asset = db.get(Asset, asset_id)
            if asset is None or not asset.file_key:
                _fail(db, job_id, asset_id, "素材文件缺失")
                return
            source = resolve_key(asset.file_key)
            target = proxy_path(source.parent)
            ok = build_proxy(source, target)  # slot already held by _run_proxy
            if ok:
                key = proxy_key_for(asset)
                _set_proxy_meta(db, asset_id, "ready", key=key)
                job = db.get(Job, job_id)
                job.status = "succeeded"
                job.progress = 1.0
                say(job, "jobMsg_proxyDone")
                job.result = {"proxy_key": key}
                emit_job_event(db, job.id, "job.succeeded", {"proxy_key": key})
                db.commit()
            else:
                _fail(db, job_id, asset_id, "ffmpeg 代理转码失败")
        except Exception as exc:  # a worker thread must record failure, never die silently
            db.rollback()
            _fail(db, job_id, asset_id, str(exc)[:500])


def _fail(db: Session, job_id: str, asset_id: str, reason: str) -> None:
    _set_proxy_meta(db, asset_id, "failed")
    job = db.get(Job, job_id)
    if job is not None:
        job.status = "failed"
        say(job, "jobMsg_proxyFailed")
        job.error = reason
        emit_job_event(db, job.id, "job.failed", {"reason": reason})
        db.commit()


def reconcile_missing_proxies(db: Session) -> int:
    """Startup: (re)queue proxies for video assets without a ready one on disk.

    A backend restart orphans the daemon thread, leaving media_info stuck at
    "pending"; here we re-drive anything whose proxy file is actually missing,
    and repair the status of proxies that exist on disk but lost their flag.
    """
    if not settings.generate_proxies:
        return 0
    queued = 0
    for asset in db.scalars(select(Asset).where(Asset.kind == "video")):
        if not asset.file_key:
            continue
        directory = resolve_key(asset.file_key).parent
        if proxy_path(directory).is_file():
            if proxy_status(asset) != "ready":
                _set_proxy_meta(db, asset.id, "ready", key=proxy_key_for(asset))
            continue
        # failed 是**判定过的终态**,不是"还没跑":源文件坏的素材每次转必败,启动扫描再替它
        # 排队只会无限重试 —— dev 模式每次热重启跑一轮,两个坏素材曾这样滚出上千条失败任务。
        # 这里只救 pending 孤儿(重启害死的)和从没跑过的;想再试坏素材走手动重试(那是人的判断)。
        if proxy_status(asset) == "failed":
            continue
        if start_proxy_job(db, asset, created_by=None, force=True):  # 启动时的补齐扫描,没有操作人
            queued += 1
    return queued
