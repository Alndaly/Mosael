"""老库里的当前工作流图在升级时成为可追溯的 revision 1。"""

from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.core.db import engine
from app.db.migrations import _migrate_workflow_revisions
from app.db.models import WorkflowRevision
from app.domain.workflows.revisions import graph_digest
from tests.util import fresh_client


def _legacy_workflow() -> tuple[str, dict]:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "Old"}).json()
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": []}
    workflow = client.post(
        "/api/workflows",
        json={"workspace_id": workspace["id"], "name": "Old workflow", "graph": graph},
    ).json()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE workflow_revisions"))
        connection.execute(text("ALTER TABLE workflows DROP COLUMN graph_hash"))
        connection.execute(text("ALTER TABLE workflows DROP COLUMN revision"))
    engine.dispose()
    WorkflowRevision.__table__.create(bind=engine, checkfirst=True)
    return workflow["id"], graph


def test_existing_workflows_receive_a_stable_initial_revision() -> None:
    workflow_id, graph = _legacy_workflow()

    _migrate_workflow_revisions()

    columns = {column["name"] for column in inspect(engine).get_columns("workflows")}
    assert {"revision", "graph_hash"} <= columns
    with engine.begin() as connection:
        workflow = connection.execute(
            text("SELECT revision, graph_hash FROM workflows WHERE id = :id"),
            {"id": workflow_id},
        ).one()
        revision = connection.execute(
            text(
                "SELECT revision, graph, graph_hash, source FROM workflow_revisions "
                "WHERE workflow_id = :id"
            ),
            {"id": workflow_id},
        ).one()
    assert workflow.revision == revision.revision == 1
    assert workflow.graph_hash == revision.graph_hash == graph_digest(graph)
    assert json.loads(revision.graph) == graph
    assert revision.source == "migration"

    _migrate_workflow_revisions()
    with engine.begin() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM workflow_revisions WHERE workflow_id = :id"),
            {"id": workflow_id},
        ).scalar_one()
    assert count == 1


def test_reentrant_migration_preserves_and_repairs_the_current_revision() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "Current revision"}).json()
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": []}
    workflow = client.post(
        "/api/workflows",
        json={
            "workspace_id": workspace["id"],
            "name": "Edited workflow",
            "graph": graph,
        },
    ).json()
    for version in (2, 3):
        graph = {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "config": {"params": {"version": version}},
                }
            ],
            "edges": [],
        }
        response = client.patch(
            f"/api/workflows/{workflow['id']}", json={"graph": graph}
        )
        assert response.status_code == 200
        workflow = response.json()
    assert workflow["revision"] == 3

    # 正常重启不能把已经编辑到 v3 的工作流迁回 v1。
    _migrate_workflow_revisions()
    with engine.begin() as connection:
        current = connection.execute(
            text("SELECT revision, graph_hash FROM workflows WHERE id = :id"),
            {"id": workflow["id"]},
        ).one()
        count = connection.execute(
            text("SELECT count(*) FROM workflow_revisions WHERE workflow_id = :id"),
            {"id": workflow["id"]},
        ).scalar_one()
    assert current.revision == 3
    assert current.graph_hash == graph_digest(graph)
    assert count == 3

    # 旧版迁移曾只破坏当前指针而保留全部历史；下次启动应按最新快照自动修复。
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE workflows SET revision = 1 WHERE id = :id"),
            {"id": workflow["id"]},
        )
    _migrate_workflow_revisions()
    with engine.begin() as connection:
        repaired = connection.execute(
            text("SELECT revision, graph_hash FROM workflows WHERE id = :id"),
            {"id": workflow["id"]},
        ).one()
        repaired_count = connection.execute(
            text("SELECT count(*) FROM workflow_revisions WHERE workflow_id = :id"),
            {"id": workflow["id"]},
        ).scalar_one()
    assert repaired.revision == 3
    assert repaired.graph_hash == graph_digest(graph)
    assert repaired_count == 3

    # 修好指针后，恢复会从 v3 追加 v4，而不会撞上已存在的 v2。
    restored = client.post(f"/api/workflows/{workflow['id']}/revisions/1/restore")
    assert restored.status_code == 200
    assert restored.json()["revision"] == 4
