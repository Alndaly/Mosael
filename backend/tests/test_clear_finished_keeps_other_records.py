"""「清空已结束」不再顺手删掉别处的记录,删之前先给人看会删几条(UM-01 的止血)。

此前一次点击把整个工作区的任务物理删光:工作流页的执行历史和能复制 / 下载的运行产出全文
(`workflow_run_outputs` 跟着任务级联)一起没了,用量事件的 `job_id` 被置空、「谁在花钱」再也
归不到人头上。现在工作流运行和记过用量的任务整棵留着;确认框里的数和真删的数是同一份计划。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Job, ProviderUsageEvent, TaskEvent, WorkflowRunOutput
from app.domain.billing.usage import record_usage
from tests.util import fresh_client, second_client


def _job(db, workspace_id: str, *, kind: str = "render", parent: str | None = None, created_by: str | None = None) -> str:
    job = Job(workspace_id=workspace_id, kind=kind, status="succeeded", message="x", parent_job_id=parent,
              created_by=created_by)
    db.add(job)
    db.flush()
    db.add(TaskEvent(job_id=job.id, type="e", payload={}))
    return job.id


def test_工作流运行和记过用量的任务留下_其余照删_预览的数和真删的一致() -> None:
    client = fresh_client("owner")
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = second_client("mate")
    mate_id = mate.get("/api/auth/me").json()["id"]
    assert client.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": "editor"}).status_code == 200
    invitation = mate.get("/api/invitations").json()["invitations"][0]["id"]
    assert mate.post(f"/api/invitations/{invitation}/accept").status_code == 200

    with SessionLocal() as db:
        plain = _job(db, ws)
        plain_child = _job(db, ws, parent=plain)
        by_mate = _job(db, ws, created_by=mate_id)
        run = _job(db, ws, kind="workflow")
        db.add(WorkflowRunOutput(job_id=run, node_id="ask", output_key="text", value="一段很长的模型回复"))
        #: 没留下产出的那次(比如失败的)也是工作流页「执行历史」里的一行。
        failed_run = _job(db, ws, kind="workflow")
        #: 跑图的不只工作流任务(带 workflow_revision_id 的别种任务也走引擎、也留产出全文,见 workflows/authority)。
        graph_run = _job(db, ws, kind="board_recipe")
        db.add(WorkflowRunOutput(job_id=graph_run, node_id="write", output_key="text", value="画板配方写的文案"))
        paid = _job(db, ws, kind="ai_generation")
        record_usage(db, workspace_id=ws, capability="image", operation="generate", idempotency_key="paid-1",
                     job_id=paid, cost_micros=120000, cost_confidence="estimated")
        #: 花钱的是子任务:整棵留着,否则父任务删了、子任务成了看不见的孤儿。
        paid_parent = _job(db, ws)
        paid_child = _job(db, ws, kind="ai_generation", parent=paid_parent)
        record_usage(db, workspace_id=ws, capability="video", operation="generate", idempotency_key="paid-2",
                     job_id=paid_child, cost_micros=3000000, cost_confidence="estimated")
        db.commit()

    preview = client.get(f"/api/jobs/finished/preview?workspace_id={ws}")
    assert preview.status_code == 200, preview.text
    assert preview.json() == {"tasks": 2, "jobs": 3, "by_others": 1, "kept": 5}

    assert client.delete(f"/api/jobs/finished?workspace_id={ws}").json() == {"removed": 3}

    with SessionLocal() as db:
        left = {job.id for job in db.query(Job).filter(Job.workspace_id == ws)}
        assert left == {run, failed_run, graph_run, paid, paid_parent, paid_child}
        assert not {plain, plain_child, by_mate} & left
        # 运行产出还在、用量还挂在任务上(「谁在花钱」顺着它找人)。
        assert [row.value for row in db.query(WorkflowRunOutput).filter(WorkflowRunOutput.job_id == run)] == ["一段很长的模型回复"]
        assert {row.job_id for row in db.query(ProviderUsageEvent)} == {paid, paid_child}

    # 再看一次:没有可删的了,留下的还是那五条。
    assert client.get(f"/api/jobs/finished/preview?workspace_id={ws}").json() == {"tasks": 0, "jobs": 0, "by_others": 0, "kept": 5}


def test_预览和清空同一道闸_只读成员两样都不行() -> None:
    client = fresh_client("owner")
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    viewer = second_client("viewer")
    client.post(f"/api/workspaces/{ws}/invitations", json={"username": "viewer", "role": "viewer"})
    invitation = viewer.get("/api/invitations").json()["invitations"][0]["id"]
    viewer.post(f"/api/invitations/{invitation}/accept")
    with SessionLocal() as db:
        _job(db, ws)
        db.commit()

    assert viewer.get(f"/api/jobs/finished/preview?workspace_id={ws}").status_code == 403
    assert viewer.delete(f"/api/jobs/finished?workspace_id={ws}").status_code == 403
    assert client.get(f"/api/jobs/finished/preview?workspace_id={ws}").json()["tasks"] == 1
