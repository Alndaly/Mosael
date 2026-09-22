"""执行器共用的小工具:子 job 轮询、宽容的输入解析。"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.workflows import WorkflowDomainError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CHILD_POLL_SECONDS = 2.0


def wait_for_job(job_id: str, *, release: "Session | None" = None) -> Job:
    """轮询子 job 到终态(用独立会话,避免长事务)。

    **`release` 是调用方自己的会话:等待期间把它连同引擎的连接预算一起交还。**

    一个只是在等的节点不该占着连接。不还的话,引擎那份预算(engine.NODE_CONNECTIONS)会
    被一群等着的父节点占满,而它们等的正是子图里那些**取不到预算**的节点 —— 死锁,而且表现
    是"工作流卡住不动",看不出和连接池有关。父会话在等待期间也确实没有任何用处:这里轮询
    用的是自己开的独立会话。

    `Session.close()` 之后再用它会自动重新取一条连接,所以调用方在这个函数返回之后照常使用。

    **没有"等太久就放弃"这一条。** 此前有(通用 15 分钟,字幕配音按条数放宽),而放弃等待并不会
    让子任务停下 —— 它照样在生成、照样扣费,只是做完之后没人要了。付过账:三条 Seedance 在第
    300 秒被判超时,火山那边 6 分钟后全部生成成功、全部扣费,成片无人认领。

    结束只有两种:子任务落终态,或者用户取消 —— 取消工作流会级联到它的所有子孙任务(见
    jobs.cancel_job),子任务随之落终态,这里就自然返回了。子任务各自有自己的上限(生成任务的
    轮询上限防的是"供应商永远不回话",见 contracts.generation.POLL_TIMEOUT_SECONDS)。
    """
    if release is not None:
        release.commit()
        release.close()
    with _budget_released(release is not None):
        return _poll(job_id)


@contextmanager
def _budget_released(active: bool):
    """等待期间把引擎的连接预算还回去,等完再拿回来。"""
    from app.domain.workflows.engine import NODE_CONNECTIONS

    if not active:
        yield
        return
    NODE_CONNECTIONS.release()
    try:
        yield
    finally:
        NODE_CONNECTIONS.acquire()


def _poll(job_id: str) -> Job:
    while True:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                raise WorkflowDomainError("wfErr_childMissing")
            if job.status == "succeeded":
                db.expunge(job)
                return job
            if job.status == "failed":
                raise WorkflowDomainError("wfErr_childFailed", params={"reason": job.error or job.message})
        time.sleep(CHILD_POLL_SECONDS)


def id_list(value: Any) -> list[str]:
    """Accept either a comma-separated string or a real list.

    Both reach here legitimately: a hand-typed config gives a string, while `{{查询.ids}}`
    resolves to the list asset_query produced. Treating the list case as a string would
    stringify it and match nothing, with no error to show for it.
    """
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").replace("，", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def truthy(value: Any) -> bool:
    """Loop-condition truthiness: real bools/None as-is; strings "false"/"0"/"" (any case) are False."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "no", "none")
    return bool(value)
