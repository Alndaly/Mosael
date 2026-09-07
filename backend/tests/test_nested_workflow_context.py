from unittest.mock import Mock

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Job, User, Workflow
from app.domain.jobs import cancel_job, create_job, current_actor, current_parent_job_id
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def setup_graph():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    leaf = {"nodes": [{"id": "leaf", "type": "output", "config": {}}], "edges": []}
    body = {"nodes": [{"id": "nested", "type": "subgraph", "config": {"body": leaf}}], "edges": []}
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "loop", "type": "loop_foreach", "config": {"items": [1, 2, 3], "body": body}}], "edges": [{"id": "edge", "source": "start", "target": "loop"}]}
    with SessionLocal() as db:
        user = db.scalar(select(User))
        workflow = Workflow(workspace_id=ws, name="nested", graph=graph)
        db.add(workflow)
        parent = create_job(db, workspace_id=ws, created_by=user.id, kind="workflow", payload={})
        parent.status = "running"
        db.commit()
        return graph, workflow.id, parent.id, user.id


def test_nested_threadpools_preserve_parent_and_actor(monkeypatch):
    graph, wf_id, parent_id, actor_id = setup_graph()
    children = []
    def leaf(db, wf, config):
        child = create_job(db, workspace_id=wf.workspace_id, kind="test", created_by=current_actor(db), payload={})
        children.append((child.parent_job_id, child.created_by, current_parent_job_id()))
        db.commit()
        return {}
    monkeypatch.setattr("app.domain.workflows.engine.get_executor", lambda kind: leaf if kind == "output" else get_executor(kind))
    with SessionLocal() as db:
        _, cancelled = execute_graph(graph, wf_id=wf_id, job=db.get(Job, parent_id), db=db)
    assert not cancelled
    assert children == [(parent_id, actor_id, parent_id)] * 3
    assert current_parent_job_id() is None


def test_nested_loop_stops_after_parent_is_cancelled(monkeypatch):
    graph, wf_id, parent_id, _ = setup_graph()
    def leaf(db, wf, config):
        parent = db.get(Job, parent_id)
        if parent.status == "running":
            cancel_job(db, parent)
        return {}
    handler = Mock(side_effect=leaf)
    monkeypatch.setattr("app.domain.workflows.engine.get_executor", lambda kind: handler if kind == "output" else get_executor(kind))
    with SessionLocal() as db:
        try:
            _, cancelled = execute_graph(graph, wf_id=wf_id, job=db.get(Job, parent_id), db=db)
            assert cancelled
        except WorkflowDomainError as exc:
            assert "取消" in str(exc)
    assert handler.call_count == 1
    with SessionLocal() as db:
        assert db.get(Job, parent_id).error == "已取消"
