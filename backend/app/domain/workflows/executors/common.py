"""执行器共用的小工具:子 job 轮询、宽容的输入解析。"""

from __future__ import annotations

import time
from typing import Any

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.workflows import WorkflowDomainError

CHILD_JOB_TIMEOUT_SECONDS = 15 * 60
CHILD_POLL_SECONDS = 2.0


def wait_for_job(job_id: str) -> Job:
    """轮询子 job 到终态(用独立会话,避免长事务)。"""
    deadline = time.monotonic() + CHILD_JOB_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                raise WorkflowDomainError("子任务不存在")
            if job.status == "succeeded":
                db.expunge(job)
                return job
            if job.status == "failed":
                raise WorkflowDomainError(f"子任务失败: {job.error or job.message}")
        time.sleep(CHILD_POLL_SECONDS)
    raise WorkflowDomainError("子任务超时")


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
