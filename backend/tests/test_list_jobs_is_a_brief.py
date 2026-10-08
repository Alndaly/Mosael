"""智能体列任务拿到的是一份简报,不是整份任务(智能体那一路 AGENT-12)。

现场(维护者库,只读聚合):工作流任务的载荷 + 结果平均 36 KB、最大 420 KB;一次 `list_jobs`(默认 20 条)回了 893 KB,
约 25 万 token —— 这一轮之后的每一次模型请求都整段重发,窗口小的模型直接装不下,1M 窗口的模型照单全收、照单付钱。
智能体问「好了吗」要的是:是什么、到哪一步、出错没有、产出了哪些东西的 id;细节用 get_job 看那一个。
"""

from __future__ import annotations

import json

import mcp_server
from app.core.db import SessionLocal
from app.domain import jobs as jobs_domain
from tests.util import fresh_client, user_id


def test_列任务是简报_大载荷大结果不跟着回来_产出的id在() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    huge = {"nodes": [{"id": str(index), "widgets": ["x" * 200] * 10} for index in range(200)]}
    with SessionLocal() as db:
        job = jobs_domain.create_job(
            db, workspace_id=workspace, kind="workflow", created_by=user_id(),
            payload={"subject": "出海流程", "graph": huge},
        )
        job.result = {"asset_ids": ["a1", "a2"], "transcript_id": "t1", "context": huge, "output": huge}
        job.status = "succeeded"
        db.commit()
        job_id = job.id

    with mcp_server.calling_as(user_id=user_id(), requested_by="test"):
        listed = mcp_server.list_jobs(workspace_id=workspace)
    assert len(json.dumps(listed, ensure_ascii=False)) < 2_000, "列任务回来的还是整份载荷 / 结果"
    brief = next(one for one in listed if one["id"] == job_id)
    assert brief["status"] == "succeeded" and brief["kind"] == "workflow"
    assert brief["subject"] == "出海流程"
    assert brief["produced"] == {"asset_ids": ["a1", "a2"], "transcript_id": "t1"}
    assert brief["details"] == "get_job", "说清还有细节、去哪看"
    assert "payload" not in brief and "result" not in brief
