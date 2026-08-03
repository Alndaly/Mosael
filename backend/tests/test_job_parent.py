"""工作流派生的子任务归到父工作流 job 下,任务中心不再与父平铺成两行。

链路:工作流引擎在跑某个子任务节点时 set_parent_job(工作流 job id);子任务创建函数
(start_publish / start_export / …)都汇聚到 create_job,后者据 contextvar 自动打上
parent_job_id。任务中心 /api/jobs?top_level=true 只列顶层任务,子任务在工作流任务详情
(/api/jobs/{id}/children)里收纳查看。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.jobs import cancel_job, create_job, reset_parent_job, set_parent_job
from tests.util import fresh_client


def _workspace() -> tuple[object, str]:
    client = fresh_client()
    return client, client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_create_job_defaults_to_top_level() -> None:
    """没有父上下文时,create_job 造的是顶层任务(parent 为 None)。"""
    _, ws = _workspace()
    with SessionLocal() as db:
        job = create_job(db, created_by=None, workspace_id=ws, kind="publish", payload={})
        db.commit()
        assert job.parent_job_id is None


def test_create_job_captures_ambient_parent() -> None:
    """set_parent_job 之后 create_job 自动挂到该父下;reset 之后恢复顶层。"""
    _, ws = _workspace()
    token = set_parent_job("wf-job-abc")
    try:
        with SessionLocal() as db:
            child = create_job(db, created_by=None, workspace_id=ws, kind="publish", payload={})
            db.commit()
            assert child.parent_job_id == "wf-job-abc"
    finally:
        reset_parent_job(token)
    with SessionLocal() as db:
        after = create_job(db, created_by=None, workspace_id=ws, kind="publish", payload={})
        db.commit()
        assert after.parent_job_id is None  # reset 后不再泄漏父上下文


def test_ambient_parent_propagates_inside_threadpool() -> None:
    """还原引擎的真实执行形态:节点在线程池 worker 里 set_parent_job,worker 内同步调用的
    create_job 必须拿到该父——contextvar 在同一线程的调用链内可见,线程间互不干扰。"""
    _, ws = _workspace()
    captured: dict[str, str | None] = {}

    def node(parent_id: str) -> None:
        token = set_parent_job(parent_id)
        try:
            with SessionLocal() as db:
                job = create_job(db, created_by=None, workspace_id=ws, kind="publish", payload={})
                db.commit()
                captured[parent_id] = job.parent_job_id
        finally:
            reset_parent_job(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(node, ["wf-1", "wf-2"]))

    assert captured == {"wf-1": "wf-1", "wf-2": "wf-2"}  # 并行节点各自归各自的父,无串扰


def test_top_level_filter_and_children_endpoint() -> None:
    """/api/jobs?top_level=true 收起子任务;默认列全部;/children 取某父的子任务。"""
    client, ws = _workspace()
    with SessionLocal() as db:
        parent = create_job(db, created_by=None, workspace_id=ws, kind="workflow", payload={})
        db.flush()
        child = create_job(db, created_by=None, workspace_id=ws, kind="publish", payload={}, parent_job_id=parent.id)
        db.commit()
        parent_id, child_id = parent.id, child.id

    top = client.get(f"/api/jobs?workspace_id={ws}&top_level=true").json()
    top_ids = {j["id"] for j in top}
    assert parent_id in top_ids and child_id not in top_ids  # 子任务不再平铺

    all_jobs = client.get(f"/api/jobs?workspace_id={ws}").json()
    all_ids = {j["id"] for j in all_jobs}
    assert parent_id in all_ids and child_id in all_ids  # 不传 top_level 仍返回全部(按 kind 过滤的视图靠它)

    children = client.get(f"/api/jobs/{parent_id}/children").json()
    assert [c["id"] for c in children] == [child_id]
    assert children[0]["parent_job_id"] == parent_id


def test_cancel_workflow_cascades_to_descendants() -> None:
    """取消工作流 → 级联取消它派生的发布子任务(及嵌套孙任务);不相干的顶层任务不受牵连。"""
    _, ws = _workspace()
    with SessionLocal() as db:
        parent = create_job(db, created_by=None, workspace_id=ws, kind="workflow", payload={})
        parent.status = "running"
        db.flush()
        child = create_job(db, created_by=None, workspace_id=ws, kind="publish", payload={}, parent_job_id=parent.id)
        child.status = "running"
        grandchild = create_job(db, created_by=None, workspace_id=ws, kind="export_sequence", payload={}, parent_job_id=child.id)
        grandchild.status = "running"
        other = create_job(db, created_by=None, workspace_id=ws, kind="workflow", payload={})  # 不相干的顶层任务
        other.status = "running"
        db.commit()
        ids = (parent.id, child.id, grandchild.id, other.id)

    with SessionLocal() as db:
        cancel_job(db, db.get(Job, ids[0]))

    with SessionLocal() as db:
        assert db.get(Job, ids[0]).status == "failed"  # 父工作流
        assert db.get(Job, ids[1]).status == "failed"  # 发布子任务被级联取消(此前会残留在跑)
        assert db.get(Job, ids[2]).status == "failed"  # 嵌套孙任务
        assert db.get(Job, ids[3]).status == "running"  # 不相干任务不动
