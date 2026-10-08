"""任务列表有上限、每一行不带 `result`(BA-10)。

此前 `GET /api/jobs` 整表全拉、每行带着结果:维护者库里 578 个顶层任务 2.4 MB(工作流的 `result` 是整次运行的上下文,
一条几十到几百 KB),有任务在跑时任务中心每 1.5 秒拉一遍 —— 而列表一处都不读结果。现在给最近的 `limit` 条,
**加上全部还在跑的**(一个跑了一整夜的任务排在两百条之后,也得看得见进度、停得下它);结果只在详情里给。
"""

from __future__ import annotations

from datetime import timedelta

from app.core.db import SessionLocal
from app.db.models import Job, now
from tests.util import fresh_client


def _jobs(workspace: str) -> tuple[str, list[str]]:
    """(很早以前起的、还在跑的那一个, 之后结束的五个 —— 新的在前)。每个都带一份大结果。"""
    big = {"context": {"text": "很长的一段" * 2000}}
    started = now() - timedelta(days=30)
    with SessionLocal() as db:
        running = Job(workspace_id=workspace, kind="workflow", status="running", payload={"subject": "一整夜"},
                      result=big, created_at=started)
        db.add(running)
        finished = []
        for index in range(5):
            job = Job(workspace_id=workspace, kind="workflow", status="succeeded", payload={"subject": f"第 {index} 个"},
                      result=big, created_at=started + timedelta(days=1, minutes=index))
            db.add(job)
            finished.append(job)
        db.commit()
        return running.id, [job.id for job in reversed(finished)]


def test_最近的几条加上全部还在跑的_新的在前() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    running, finished = _jobs(workspace)

    listed = client.get(f"/api/jobs?workspace_id={workspace}&limit=3").json()

    assert [row["id"] for row in listed] == [*finished[:3], running], "很早以前起、还在跑的那一个也要在"


def test_列表里每一行不带结果_详情里有() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    running, _finished = _jobs(workspace)

    listed = client.get(f"/api/jobs?workspace_id={workspace}&top_level=true")
    assert all("result" not in row for row in listed.json())
    assert all(row["payload"].get("subject") for row in listed.json()), "收拢、跳转要用的载荷照旧在"
    assert len(listed.content) < 10_000, f"六个任务 {len(listed.content)} 字节:结果又跟着列表出来了"
    assert client.get(f"/api/jobs/{running}").json()["result"]["context"]["text"].startswith("很长的一段")


def test_默认上限两百条() -> None:
    from app.domain.job_center.use_cases import LIST_LIMIT

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add_all(
            Job(workspace_id=workspace, kind="proxy", status="failed", payload={}, result={},
                created_at=now() - timedelta(minutes=index))
            for index in range(LIST_LIMIT + 5)
        )
        db.commit()
    assert len(client.get(f"/api/jobs?workspace_id={workspace}").json()) == LIST_LIMIT == 200
