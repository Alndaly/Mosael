"""迁移 migrate-translation-engines-are-providers(ADR 0032 第三步):翻译节点存着的 `google | ai` 改成提供方 id。

`google` → `builtin:google`,`ai` → `builtin:chat`,**照原样点名**(不清成按默认:以后他把默认定成收费插件,这些节点不该
悄悄跟着换);空的不动;工作流(含循环体里的)和画板都改;再跑一次什么都不动。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import _migrate_translation_engines_are_providers, migration_plan
from app.db.models import Board, Workflow
from tests.util import fresh_client


def test_迁移登记在计划里() -> None:
    assert "migrate-translation-engines-are-providers" in {step.name for step in migration_plan().steps}


def test_翻译节点的引擎名改成提供方_点名照留_再跑一次不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {"nodes": [
        {"id": "a", "type": "translate", "config": {"text": "hi", "engine": "google"}},
        {"id": "b", "type": "translate_lines", "config": {"texts": "x", "engine": "ai", "profile_id": "p1"}},
        {"id": "c", "type": "translate", "config": {"text": "hi"}},
        {"id": "d", "type": "transcribe_asset", "config": {"engine": "google"}},
        {"id": "loop", "type": "loop_foreach", "config": {"body": {"nodes": [
            {"id": "e", "type": "translate", "config": {"engine": "ai"}}], "edges": []}}},
    ], "edges": []}
    canvas = {"items": [
        {"id": "n", "kind": "note", "form": {"abilities": {"node:translate": {"config": {"engine": "google"}}}}},
    ], "edges": []}
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="wf", graph=graph)
        board = Board(workspace_id=ws, name="b", canvas=canvas)
        db.add_all([workflow, board])
        db.commit()
        workflow_id, board_id = workflow.id, board.id

    _migrate_translation_engines_are_providers()
    _migrate_translation_engines_are_providers()

    with SessionLocal() as db:
        nodes = {node["id"]: node["config"] for node in db.get(Workflow, workflow_id).graph["nodes"]}
        assert nodes["a"]["engine"] == "builtin:google"
        assert nodes["b"]["engine"] == "builtin:chat" and nodes["b"]["profile_id"] == "p1"
        assert "engine" not in nodes["c"], "没点名的不动"
        assert nodes["d"]["engine"] == "google", "别的节点不碰"
        assert nodes["loop"]["body"]["nodes"][0]["config"]["engine"] == "builtin:chat"
        ability = db.get(Board, board_id).canvas["items"][0]["form"]["abilities"]["node:translate"]
        assert ability["config"]["engine"] == "builtin:google"
