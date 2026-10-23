"""工作流发布节点补 `content_kind` 的那条迁移。

执行器不再写「没填就当 video」这种回退(见 executors/subjobs 的注释),所以这条迁移必须真的
把已经存下来的图补对:既验搬对了,也验再跑一次什么都不做。
"""

from __future__ import annotations

from app.db.migrations import _migrate_workflow_publish_nodes_get_content_kind
from app.db.models import Workflow
from app.core.db import SessionLocal
from tests.util import fresh_client


def _store(workspace_id: str, graph: dict) -> str:
    with SessionLocal() as db:
        workflow = Workflow(
            workspace_id=workspace_id,
            name="publish graph",
            graph=graph,
            revision=1,
        )
        db.add(workflow)
        db.commit()
        return workflow.id


def _graph_of(workflow_id: str) -> dict:
    """图在库里是 JSON 列:走 ORM 取回来就是 dict。"""
    with SessionLocal() as db:
        workflow = db.get(Workflow, workflow_id)
        assert workflow is not None
        return dict(workflow.graph)


def test_publish_nodes_get_the_default_shape_and_rerun_is_a_noop() -> None:
    workspace_id = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {
        "nodes": [
            {"id": "n1", "type": "publish", "config": {"account_id": "a1", "asset_id": "as1"}},
            {"id": "n2", "type": "publish", "config": {"account_id": "a2", "content_kind": "image-text"}},
            {"id": "n3", "type": "llm", "config": {"prompt": "hi"}},
        ],
        "edges": [],
    }
    workflow_id = _store(workspace_id, graph)

    _migrate_workflow_publish_nodes_get_content_kind()
    migrated = _graph_of(workflow_id)
    nodes = {node["id"]: node for node in migrated["nodes"]}
    assert nodes["n1"]["config"]["content_kind"] == "video"
    #: 已经写了形状的节点一个字都不动。
    assert nodes["n2"]["config"]["content_kind"] == "image-text"
    #: 别的节点不受影响。
    assert "content_kind" not in nodes["n3"]["config"]

    #: 第二次跑什么都不做(幂等)。
    _migrate_workflow_publish_nodes_get_content_kind()
    assert _graph_of(workflow_id) == migrated
