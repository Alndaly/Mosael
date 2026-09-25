"""迁移 migrate-condition-edges-use-source-handle:边上没人读的 `branch` 键改写成 `source_handle`。

全片生成模板曾给五条条件边写 `"branch": "true"`。它们能按「真」那一支跑,只是因为没写 handle
的条件边缺省就是真;画布上没有真 / 假的标记。从那份模板装出来的工作流在这里一次改好。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_condition_edges_use_source_handle
from app.db.models import Workflow, WorkflowRevision
from app.domain.workflows.revisions import current_workflow_revision
from tests.util import fresh_client


def _legacy_graph() -> dict:
    body = {
        "nodes": [
            {"id": "has_voice", "type": "condition", "config": {"left": "{{input.voice_id}}", "op": "not_empty"}},
            {"id": "narrate", "type": "template", "config": {"template": "x"}},
        ],
        "edges": [{"id": "gate", "source": "has_voice", "target": "narrate", "branch": "true"}],
    }
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "check", "type": "condition", "config": {"left": "a", "op": "not_empty"}},
            {"id": "yes", "type": "template", "config": {"template": "y"}},
            {"id": "shots", "type": "loop_foreach", "config": {"items": "[]", "body": body}},
        ],
        "edges": [
            {"id": "s_check", "source": "start", "target": "check", "branch": "true"},
            {"id": "check_yes", "source": "check", "target": "yes", "branch": "true"},
            {"id": "check_shots", "source": "check", "target": "shots", "source_handle": "false", "branch": "true"},
        ],
    }


def _stored(workflow_id: str) -> dict:
    with engine.begin() as connection:
        return json.loads(
            connection.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}).scalar_one()
        )


def test_branch_键搬进_source_handle_修订跟着对上_重跑什么都不做() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow_id = client.post("/api/workflows", json={"workspace_id": workspace, "name": "legacy"}).json()["id"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE workflows SET graph = :graph WHERE id = :id"),
            {"graph": json.dumps(_legacy_graph(), ensure_ascii=False), "id": workflow_id},
        )

    _migrate_condition_edges_use_source_handle()

    graph = _stored(workflow_id)
    edges = {edge["id"]: edge for edge in graph["edges"]}
    assert all("branch" not in edge for edge in edges.values())
    #: 从 start 出发的不是分支节点 —— 只删掉那个键,不凭空加 handle。
    assert "source_handle" not in edges["s_check"]
    assert edges["check_yes"]["source_handle"] == "true"
    #: 已经写了 handle 的不改。
    assert edges["check_shots"]["source_handle"] == "false"
    body = next(node for node in graph["nodes"] if node["id"] == "shots")["config"]["body"]
    assert body["edges"] == [{"id": "gate", "source": "has_voice", "target": "narrate", "source_handle": "true"}]

    #: 图变了,修订也得对上 —— 否则这条工作流跑不起来(摘要不符)。
    with SessionLocal() as db:
        workflow = db.get(Workflow, workflow_id)
        assert current_workflow_revision(db, workflow).graph == graph
        revisions = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count()

    _migrate_condition_edges_use_source_handle()
    assert _stored(workflow_id) == graph
    with SessionLocal() as db:
        assert db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count() == revisions
