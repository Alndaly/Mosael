from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent
from app.db.models import now as models_now

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("succeeded", "failed")

# Children (ffmpeg, ASR/TTS workers) belonging to a running job, so cancelling can actually
# stop the work. Without this, cancel only flipped a database row: ffmpeg ran to completion,
# burning CPU the user had asked to stop, and then the worker overwrote the cancellation with
# "succeeded" — the cancelled export reappeared in the library as if nothing had happened.
_CHILDREN: dict[str, Any] = {}
_CHILDREN_LOCK = threading.Lock()


def register_job_child(job_id: str, child: Any) -> None:
    """Associate a killable child (anything with .kill()) with a job for its lifetime."""
    with _CHILDREN_LOCK:
        _CHILDREN[job_id] = child


def unregister_job_child(job_id: str) -> None:
    with _CHILDREN_LOCK:
        _CHILDREN.pop(job_id, None)


def kill_job_child(job_id: str) -> bool:
    """Stop the child of a running job, if one is registered. True if something was killed."""
    with _CHILDREN_LOCK:
        child = _CHILDREN.get(job_id)
    if child is None:
        return False
    child.kill()
    return True


# Admission control for work that is heavy in CPU, GPU or memory. There was none: ten
# simultaneous exports meant ten x264 encoders plus up to eighty concurrent ffprobes, and ten
# transcribes meant ten torch interpreters — near-certain OOM on a laptop. Acquire a slot
# BEFORE opening a database session, never while holding one; see _run_proxy for what the other
# order costs. A sleeping thread is cheap, a pinned connection is not.
RENDER_SLOTS = threading.Semaphore(2)
ASR_SLOTS = threading.Semaphore(1)      # torch/funasr: one model in memory at a time
TTS_SLOTS = threading.Semaphore(1)
GENERATION_SLOTS = threading.Semaphore(4)  # mostly waiting on a remote API


def run_job_guarded(job_id: str, body: Callable[[], None], *, what: str = "job") -> None:
    """Run a worker body so that no failure can leave the job silently queued.

    Every worker began with `db.get(Job, job_id)` OUTSIDE its try. That is the call that checks
    a connection out of the pool, so when the pool was exhausted it raised, the daemon thread
    died, and the row stayed `queued` with no error — forever, since reconcile only runs at
    startup. A backfill of 60 videos produced 45 such jobs.

    Anything the body does not handle is recorded on the job here instead.
    """
    try:
        body()
    except Exception as exc:  # noqa: BLE001 — a worker thread must never die silently
        logger.exception("%s worker crashed (job=%s)", what, job_id)
        try:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job is not None and job.status not in TERMINAL_STATUSES:
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    job.message = f"{what} 失败"
                    db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"stage": "worker"}))
                    db.commit()
        except Exception:  # noqa: BLE001 — the DB is what failed; nothing left to try
            logger.exception("could not record the failure of %s %s", what, job_id)


def finish_job(db: Session, job: Job, **fields: Any) -> bool:
    """Write a terminal state unless the job already reached one.

    Workers held a Job loaded at the start of the run and assigned to it at the end, so a
    cancellation landing in between was silently clobbered. Re-read first and skip the write if
    the job is already settled; the caller uses the return value to skip the rest of its
    success path too (registering an export as an asset, emitting job.succeeded).
    """
    db.refresh(job)
    if job.status in TERMINAL_STATUSES:
        return False
    for key, value in fields.items():
        setattr(job, key, value)
    status = fields.get("status")
    if status == "failed":
        logger.warning("job %s [%s] failed: %s", job.id, job.kind, fields.get("error") or fields.get("message") or "")
    elif status == "succeeded":
        logger.info("job %s [%s] succeeded", job.id, job.kind)
    return True
# Retention (plan §12.3): active jobs keep every event; terminal jobs keep the
# most recent few; terminal jobs older than the window lose all detail events.
TERMINAL_KEEP_EVENTS = 5
EVENT_RETENTION_DAYS = 30


# ---------- 执行模式接缝 ----------
#
# 每种 job kind 声明由谁执行,两个适配器:
#
# - "in_process"(默认):领域模块 spawn 守护线程,进程死任务亡——重启时 reconcile 判失败。
# - "external":外部 worker 经 claim/report 协议(/api/jobs/worker/*,worker key 鉴权)驱动,
#   任务跨后端重启存活。发布器是第一个外部 worker;任何计算类 kind(render/transcribe…)
#   都可以经 MIBU_EXTERNAL_JOB_KINDS 或 register_external_kind() 翻成 external,
#   由团队服务器旁的独立 worker 机器认领——这是"多机"的接缝,不是新架构。
#
# publish 由 publish 领域自己注册(app/domain/publish/__init__.py);
# 任务总线不点名任何具体领域。
_EXECUTION_MODES: dict[str, str] = {}


def register_external_kind(kind: str) -> None:
    _EXECUTION_MODES[kind] = "external"


def execution_mode(kind: str) -> str:
    return _EXECUTION_MODES.get(kind, "in_process")


def external_kinds() -> tuple[str, ...]:
    return tuple(sorted(k for k, mode in _EXECUTION_MODES.items() if mode == "external"))


def dispatch_job(db: Session, job: Job, thread_target: Callable[[], None]) -> bool:
    """按 kind 的执行模式派发一个刚创建的 job。

    in_process → 立刻 spawn 守护线程(现状不变);external → 什么都不做,留在
    queued 等外部 worker 认领。领域模块只描述「怎么跑」(thread_target),
    「由谁跑」是总线的决定——这样把一个 kind 挪到外部 worker 不需要改领域代码。
    Returns True when a thread was started in-process.
    """
    if execution_mode(job.kind) == "external":
        job.message = "等待执行器认领"
        db.add(TaskEvent(job_id=job.id, type="job.awaiting_worker", payload={}))
        db.commit()
        logger.info("job %s [%s] queued for external worker", job.id, job.kind)
        return False
    db.commit()
    threading.Thread(target=thread_target, daemon=True).start()
    logger.info("job %s [%s] dispatched in-process", job.id, job.kind)
    return True


def emit_job_event(db: Session, job_id: str, type: str, payload: dict[str, Any] | None = None) -> None:
    """在任务总线上发一条事件(不 commit,跟随调用方事务)。

    TaskEvent 行只在总线创建——领域模块经这里发事件,而不是自己 `db.add(TaskEvent(...))`
    (数据归属规约,见 ownership.py)。这也是未来把「job 终态 → 站内通知」做成事件
    消费者的挂点。
    """
    db.add(TaskEvent(job_id=job_id, type=type, payload=payload or {}))


def create_job(
    db: Session,
    *,
    workspace_id: str,
    kind: str,
    payload: dict[str, Any],
    message: str = "Queued",
) -> Job:
    job = Job(workspace_id=workspace_id, kind=kind, payload=payload, message=message)
    db.add(job)
    db.flush()
    db.add(TaskEvent(job_id=job.id, type="job.queued", payload={"message": message}))
    logger.info("job %s [%s] created (workspace=%s)", job.id, kind, workspace_id)
    return job


def reconcile_orphaned_jobs(db: Session) -> int:
    """Fail in-process jobs left `queued`/`running` by a backend restart.

    Their daemon-thread workers cannot survive the process, so they would
    otherwise sit frozen at their last progress forever. Publish jobs are exempt
    (external worker). Returns the number of jobs reconciled.
    """
    stale = db.scalars(
        select(Job)
        .where(Job.status.in_(("queued", "running")))
        .where(Job.kind.notin_(external_kinds()))
    ).all()
    for job in stale:
        job.status = "failed"
        job.message = "已中断"
        job.error = "后端重启导致任务中断,请重新发起"
        db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"reason": "backend_restart"}))
    if stale:
        db.commit()
    return len(stale)


def cancel_job(db: Session, job: Job) -> Job:
    """用户主动取消:job 落终态,发布任务同步撤单,工作流/批量在节点边界停下。

    线程内正在执行的节点无法安全掐断;engine/batch 每个节点边界都会重读 job
    状态,看到已取消就不再继续——"停止中断"语义是节点粒度的。
    """
    if job.status not in ("queued", "running"):
        raise ValueError("任务已结束,无法取消")
    job.status = "failed"
    job.error = "已取消"
    job.message = "已取消"
    db.add(TaskEvent(job_id=job.id, type="job.cancelled", payload={}))
    # Stop the actual work, not just the row describing it.
    killed = kill_job_child(job.id)
    if killed:
        db.add(TaskEvent(job_id=job.id, type="job.child_killed", payload={}))

    if job.kind == "publish":
        from app.db.models import PublishTask

        task = db.scalar(select(PublishTask).where(PublishTask.job_id == job.id))
        if task is not None and task.status not in ("success", "prepared", "failed", "cancelled"):
            task.status = "cancelled"
    db.commit()
    db.refresh(job)
    logger.info("job %s [%s] cancelled by user (child_killed=%s)", job.id, job.kind, killed)
    return job


# ---------- 通用 worker 协议(claim / report) ----------
#
# 发布器验证过的拉取模式,推广给所有 external kind:worker 主动认领(CAS 原子翻
# running)、富状态回报、后端从不反向连接 worker。publish 因历史契约仍走
# /api/publish/worker/*(任务粒度是 PublishTask);其余 external kind 走这里。

CLAIMABLE_STATUSES = ("queued",)


def claim_next_job(db: Session, *, kinds: list[str] | None = None, worker: str = "") -> Job | None:
    """认领最老的一条可认领 job 并原子翻成 running。

    只允许认领 external 模式的 kind——in_process 的 kind 已有线程在跑,被外部
    worker 抢走会双跑。CAS(status 仍是 queued 才更新)保证并发认领不重复。
    """
    allowed = set(external_kinds())
    if kinds:
        allowed &= set(kinds)
    if not allowed:
        return None
    while True:
        job = db.scalars(
            select(Job)
            .where(Job.status.in_(CLAIMABLE_STATUSES), Job.kind.in_(sorted(allowed)))
            .order_by(Job.created_at)
            .limit(1)
        ).first()
        if job is None:
            return None
        claimed = db.execute(
            Job.__table__.update()
            .where(Job.id == job.id, Job.status.in_(CLAIMABLE_STATUSES))
            .values(status="running", message="执行器已认领")
        ).rowcount
        if claimed:
            db.add(TaskEvent(job_id=job.id, type="job.claimed", payload={"worker": worker}))
            db.commit()
            db.refresh(job)
            logger.info("job %s [%s] claimed by worker=%s", job.id, job.kind, worker or "?")
            return job
        db.rollback()  # 另一个 worker 抢先了;重试下一条


def report_job(
    db: Session,
    job: Job,
    *,
    status: str,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> Job:
    """外部 worker 回报:running 更新进度,succeeded/failed 落终态。

    与发布器同一条规则:已终态(含用户取消)的 job 不给后到的回报复活——
    worker 是在为一个已经不存在的意图干活,结果只能丢弃。
    """
    if status not in ("running", "succeeded", "failed"):
        raise ValueError(f"未知回报状态: {status}")
    db.refresh(job)
    if job.status in TERMINAL_STATUSES:
        return job
    if status == "running":
        if progress is not None:
            job.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            job.message = message
        db.add(TaskEvent(job_id=job.id, type="job.progress", payload={"progress": job.progress}))
    else:
        job.status = status
        if message is not None:
            job.message = message
        if status == "failed":
            job.error = (error or message or "worker 报告失败")[:500]
            logger.warning("job %s [%s] failed (external worker): %s", job.id, job.kind, job.error)
        else:
            job.progress = 1.0
            if result is not None:
                job.result = result
            logger.info("job %s [%s] succeeded (external worker)", job.id, job.kind)
        db.add(TaskEvent(job_id=job.id, type=f"job.{status}", payload={}))
    db.commit()
    db.refresh(job)
    return job


def prune_task_events(db: Session, *, now: datetime | None = None) -> int:
    """Apply the retention rules to task_events. Returns rows deleted."""
    reference = now or models_now()  # utcnow() is deprecated; models_now is the same naive UTC
    cutoff = reference - timedelta(days=EVENT_RETENTION_DAYS)
    removed = 0

    terminal_jobs = db.scalars(select(Job).where(Job.status.in_(TERMINAL_STATUSES))).all()
    for job in terminal_jobs:
        if job.updated_at < cutoff:
            result = db.execute(delete(TaskEvent).where(TaskEvent.job_id == job.id))
            removed += result.rowcount or 0
            continue
        keep_ids = list(
            db.scalars(
                select(TaskEvent.id)
                .where(TaskEvent.job_id == job.id)
                .order_by(TaskEvent.created_at.desc())
                .limit(TERMINAL_KEEP_EVENTS)
            )
        )
        result = db.execute(
            delete(TaskEvent).where(TaskEvent.job_id == job.id, TaskEvent.id.not_in(keep_ids))
        )
        removed += result.rowcount or 0
    db.commit()
    return removed


def clear_finished_jobs(db: Session, workspace_id: str) -> int:
    """Remove terminal jobs (their events cascade). Returns jobs deleted."""
    jobs = db.scalars(
        select(Job).where(Job.workspace_id == workspace_id, Job.status.in_(TERMINAL_STATUSES))
    ).all()
    for job in jobs:
        db.execute(delete(TaskEvent).where(TaskEvent.job_id == job.id))
        db.delete(job)
    db.commit()
    return len(jobs)
