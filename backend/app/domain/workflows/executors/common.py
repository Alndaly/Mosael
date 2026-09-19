"""执行器共用的小工具:子 job 轮询、宽容的输入解析。"""

from __future__ import annotations

import time
from typing import Any

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.workflows import WorkflowDomainError

CHILD_POLL_SECONDS = 2.0


def wait_for_job(job_id: str) -> Job:
    """轮询子 job 到终态(用独立会话,避免长事务)。

    **没有"等太久就放弃"这一条。** 此前有(通用 15 分钟,字幕配音按条数放宽),而放弃等待并不会
    让子任务停下 —— 它照样在生成、照样扣费,只是做完之后没人要了。付过账:三条 Seedance 在第
    300 秒被判超时,火山那边 6 分钟后全部生成成功、全部扣费,成片无人认领。

    结束只有两种:子任务落终态,或者用户取消 —— 取消工作流会级联到它的所有子孙任务(见
    jobs.cancel_job),子任务随之落终态,这里就自然返回了。子任务各自有自己的上限(生成任务的
    轮询上限防的是"供应商永远不回话",见 contracts.generation.POLL_TIMEOUT_SECONDS)。
    """
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
