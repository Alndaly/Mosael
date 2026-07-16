from __future__ import annotations

import time

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent, Workflow
from app.domain.workflows import default_graph, interpolate, topo_order, validate_graph
from tests.util import fresh_client


def linear_graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}, "config": {"params": {"topic": "海边"}}},
            {
                "id": "search",
                "type": "kb_search",
                "name": "查资料",
                "position": {"x": 240, "y": 0},
                "config": {"query": "{{start.topic}}", "limit": 3},
            },
        ],
        "edges": [{"id": "e1", "source": "start", "target": "search"}],
    }


def test_validate_graph_rules() -> None:
    assert validate_graph(default_graph()) == []
    assert validate_graph(linear_graph()) == []

    no_start = {"nodes": [{"id": "a", "type": "llm", "config": {"prompt": "x"}}], "edges": []}
    assert any("开始节点" in e for e in validate_graph(no_start))

    cycle = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "a", "type": "llm", "config": {"prompt": "x"}},
            {"id": "b", "type": "llm", "config": {"prompt": "y"}},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "a"},
        ],
    }
    assert any("环路" in e for e in validate_graph(cycle))

    missing_required = {
        "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "l", "type": "llm", "config": {}}],
        "edges": [],
    }
    assert any("必填配置" in e for e in validate_graph(missing_required))

    bad_edge = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": [{"id": "e", "source": "start", "target": "ghost"}]}
    assert any("不存在的节点" in e for e in validate_graph(bad_edge))


def test_topo_and_interpolate() -> None:
    order = [node["id"] for node in topo_order(linear_graph())]
    assert order == ["start", "search"]

    ctx = {"start": {"topic": "海边", "count": 3}}
    assert interpolate("主题是{{start.topic}}", ctx) == "主题是海边"
    # 整串引用保留原类型
    assert interpolate("{{start.count}}", ctx) == 3
    assert interpolate({"q": "{{start.topic}}!"}, ctx) == {"q": "海边!"}


def test_workflow_crud_and_run() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    created = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "测试流", "description": "先查库", "graph": linear_graph()},
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["id"]

    listed = client.get(f"/api/workflows?workspace_id={ws['id']}").json()
    assert [w["name"] for w in listed] == ["测试流"]

    bad = client.patch(f"/api/workflows/{workflow_id}", json={"graph": {"nodes": [], "edges": []}})
    assert bad.status_code == 422

    types = client.get("/api/workflows/node-types").json()
    assert {t["type"] for t in types} >= {"start", "llm", "kb_search", "plugin_tool"}

    run = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {"topic": "山顶"}})
    assert run.status_code == 200, run.text
    job_id = run.json()["id"]

    deadline = time.monotonic() + 10
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert status == "succeeded"

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        # start 的默认参数被运行参数覆盖
        assert job.result["context"]["start"]["topic"] == "山顶"
        events = db.query(TaskEvent).filter(TaskEvent.job_id == job_id).all()
        types_seen = {event.type for event in events}
        assert "workflow.node.started" in types_seen
        assert "workflow.finished" in types_seen

    gone = client.delete(f"/api/workflows/{workflow_id}")
    assert gone.status_code == 204


def test_scheduled_task_dispatches_workflow() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "定时流", "graph": default_graph()},
    ).json()

    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": ws["id"],
            "name": "跑定时流",
            "kind": "workflow",
            "trigger_type": "manual",
            "schedule": {},
            "payload": {"workflow_id": workflow["id"], "params": {}},
        },
    )
    assert task.status_code == 200, task.text

    fired = client.post(f"/api/scheduled-tasks/{task.json()['id']}/run")
    assert fired.status_code == 200, fired.text
    job_id = fired.json()["job"]["id"]

    from app.workers.scheduler import dispatch_job_for_task  # noqa: F401 — run 路由已内联派发

    deadline = time.monotonic() + 10
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert status == "succeeded", status
