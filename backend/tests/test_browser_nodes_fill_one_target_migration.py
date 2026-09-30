"""「点击」的选择器 / 文字、「等待」的元素 / 网址 / 文字改成只能填一样:多填的老节点,只留执行器此前实际用的那一样。"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import _migrate_browser_nodes_fill_one_target
from app.db.models import Workflow, WorkflowRevision
from tests.util import fresh_client


def _client_and_workspaces(count: int):
    client = fresh_client()
    return client, [client.post("/api/workspaces", json={"name": f"W{i}"}).json()["id"] for i in range(count)]


def _workflow(client, ws: str, graph: dict) -> str:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": "流程", "graph": graph}).json()["id"]


def _graph_of(workflow_id: str) -> dict:
    with SessionLocal() as db:
        return db.get(Workflow, workflow_id).graph


def _config(graph: dict, node_id: str) -> dict:
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node["config"]
        for value in node["config"].values():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                try:
                    return _config(value, node_id)
                except KeyError:
                    pass
    raise KeyError(node_id)


def test_多填的点击目标和等待条件_只留执行器此前实际用的那一样() -> None:
    client, (ws,) = _client_and_workspaces(1)
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "c", "type": "browser_click", "config": {"session": "s", "selector": "#go", "text": "去"}},
            {"id": "w", "type": "browser_wait", "config": {"session": "s", "url_contains": "/done", "text": "完成"}},
            {"id": "ok", "type": "browser_wait", "config": {"session": "s", "text": "完成"}},
            {"id": "loop", "type": "loop_foreach", "config": {"items": "[]", "body": {"nodes": [
                {"id": "inner", "type": "browser_click", "config": {"session": "s", "selector": "#a", "text": "b"}},
            ], "edges": []}}},
        ],
        "edges": [],
    }
    workflow_id = _workflow(client, ws, graph)

    _migrate_browser_nodes_fill_one_target()

    after = _graph_of(workflow_id)
    assert _config(after, "c") == {"session": "s", "selector": "#go"}
    assert _config(after, "w") == {"session": "s", "url_contains": "/done"}
    assert _config(after, "ok") == {"session": "s", "text": "完成"}
    assert _config(after, "inner") == {"session": "s", "selector": "#a"}
    with SessionLocal() as db:
        latest = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).order_by(WorkflowRevision.revision.desc()).first()
        assert latest.revision == 2 and latest.source == "migration"

    _migrate_browser_nodes_fill_one_target()  # 再跑什么都不改
    with SessionLocal() as db:
        assert db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count() == 2
