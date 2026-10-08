from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import ScheduledTask, now
from app.core.unit_of_work import unit_of_work
from app.domain.jobs import PRUNE_BATCH, delete_task_events, expire_worker_leases, prunable_task_events
from app.domain.scheduler import SchedulerBusy, SchedulerDomainError, trigger_scheduled_task
from app.domain.scheduler.executors import notify_run_failed, sync_run_states
from app.domain.scheduler.operations import compute_next_run_at

"""
Scheduler runner (plan §13.4): a background loop that finds due tasks and triggers them.
The loop only decides *when*; what a scheduled task does lives in domain/scheduler, shared
with the run-now route and the webhook.
"""

logger = logging.getLogger(__name__)

TICK_SECONDS = 5.0

_stop_event: threading.Event | None = None


def start_scheduler_loop() -> None:
    global _stop_event
    if _stop_event is not None:
        return
    _stop_event = threading.Event()
    threading.Thread(target=_loop, args=(_stop_event,), daemon=True).start()


def stop_scheduler_loop() -> None:
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
        _stop_event = None


PRUNE_INTERVAL_SECONDS = 6 * 3600


def _loop(stop: threading.Event) -> None:
    last_prune = 0.0
    while not stop.wait(TICK_SECONDS):
        try:
            with SessionLocal() as db:
                tick(db)
            # Task-event retention (plan §12.3) piggybacks on this loop.
            if time.monotonic() - last_prune >= PRUNE_INTERVAL_SECONDS:
                last_prune = time.monotonic()
                removed = prune_events(stop)
                if removed:
                    logger.info("Task-event retention removed %d rows", removed)
        except Exception:  # the loop must survive any single bad tick
            logger.exception("Scheduler tick failed")


def prune_events(stop: threading.Event | None = None) -> int:
    """按保留规则清任务事件:先读出该删的(不占写锁),再**一批一个事务**地删。返回一共删了几条。

    此前整张表一个事务:一年的量要一分多钟,全程攥着写锁,别的写入 5 秒后失败。一批两千条是几十毫秒的事,
    批与批之间别的写入照常插进来。停机信号来了就停在批与批之间 —— 剩下的下一轮再删。
    """
    with SessionLocal() as db:
        ids = prunable_task_events(db)
    removed = 0
    for start in range(0, len(ids), PRUNE_BATCH):
        if stop is not None and stop.is_set():
            break
        with unit_of_work() as db:
            removed += delete_task_events(db, ids[start:start + PRUNE_BATCH])
    return removed


def tick(db: Session) -> list[str]:
    """One pass: sync run states, then trigger due tasks. Returns run ids created.

    这里是入口:领域函数不提交,每一步在这里提交 —— 一个任务触发失败回滚时,不带走前面已经做完的。
    """
    expire_worker_leases(db)
    sync_run_states(db)
    db.commit()

    created: list[str] = []
    due = db.scalars(
        select(ScheduledTask).where(
            ScheduledTask.enabled.is_(True),
            ScheduledTask.next_run_at.is_not(None),
            ScheduledTask.next_run_at <= now(),
        )
    ).all()
    for task in due:
        try:
            run, _job = trigger_scheduled_task(db, task)
        except SchedulerBusy:
            # No reentry: push the schedule forward and skip.
            task.next_run_at = compute_next_run_at(task.trigger_type, task.schedule, timezone=task.timezone)
            db.commit()
            continue
        except SchedulerDomainError as exc:
            # 跑不起来的任务(绑的工作流没了)不该是启用的 —— 删除时就停掉了。万一漏到这里,
            # 停掉它,别让这一个任务的异常把这一轮后面所有到点的任务一起带走。
            logger.warning("定时任务 %s 跑不起来,已停用:%s", task.id, exc)
            db.rollback()
            task.enabled = False
            task.next_run_at = None
            #: 到点的那一刻没人看着:停用要说一声,说清为什么(改好工作流再把它打开)。
            notify_run_failed(db, task, None, str(exc), disabled=True)
            db.commit()
            continue
        db.commit()
        created.append(run.id)
    return created
