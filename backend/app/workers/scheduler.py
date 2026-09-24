from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import ScheduledTask, now
from app.domain.jobs import expire_worker_leases, prune_task_events
from app.domain.scheduler import SchedulerBusy, SchedulerDomainError, trigger_scheduled_task
from app.domain.scheduler.executors import sync_run_states
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
                    removed = prune_task_events(db)
                    if removed:
                        logger.info("Task-event retention removed %d rows", removed)
        except Exception:  # the loop must survive any single bad tick
            logger.exception("Scheduler tick failed")


def tick(db: Session) -> list[str]:
    """One pass: sync run states, then trigger due tasks. Returns run ids created."""
    expire_worker_leases(db)
    sync_run_states(db)

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
            db.commit()
            continue
        created.append(run.id)
    return created
