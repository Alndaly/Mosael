"""任务结束时要说**跑了多久**。

"这个任务慢"是最常见的一类反馈,而排查它需要的第一个数字就是耗时。此前 succeeded/failed
两行都只有 id 和 kind:要知道一个转写跑了三分钟还是三十秒,只能去数据库里减两个时间戳。

它几乎是白捡的:Job 上本来就有 created_at,而这一行本来就要写。
"""

from __future__ import annotations

import logging
import time

from app.core.db import SessionLocal
from app.domain.jobs import create_job, finish_job
from tests.util import fresh_client


def _a_job(db, workspace_id: str):
    return create_job(db, workspace_id=workspace_id, kind="transcribe", payload={}, created_by=None)


def test_a_finished_job_says_how_long_it_took(caplog) -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        job = _a_job(db, workspace_id)
        db.commit()
        time.sleep(0.05)
        with caplog.at_level(logging.INFO, logger="app.domain.jobs"):
            finish_job(db, job, status="succeeded")

    line = "\n".join(r.getMessage() for r in caplog.records if "succeeded" in r.getMessage())
    assert line, "成功那一行没了"
    assert "s)" in line or "ms" in line, f"没说跑了多久:{line}"


def test_a_failed_job_says_it_too(caplog) -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        job = _a_job(db, workspace_id)
        db.commit()
        with caplog.at_level(logging.INFO, logger="app.domain.jobs"):
            finish_job(db, job, status="failed", error="炸了")

    line = "\n".join(r.getMessage() for r in caplog.records if "failed" in r.getMessage())
    assert "炸了" in line
    assert "s)" in line or "ms" in line, f"失败也要说跑了多久:{line}"
