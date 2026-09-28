"""迁移 migrate-transcription-engines-are-providers(ADR 0032 第三步):转写节点存着的引擎名改成能力表的提供方 id。

`auto` / 空 → 清掉(按运行者的默认);`funasr` / `whisperx` → `builtin:<引擎>`。工作流(含循环体里的)和画板上的能力
设置、生成器表单都改;认不出的值(插件连接 id)原样留着;再跑一次什么都不动。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_transcription_engines_are_providers, migration_plan
from app.db.models import Board, Workflow
from tests.util import fresh_client


def test_迁移登记在计划里() -> None:
    assert "migrate-transcription-engines-are-providers" in {step.name for step in migration_plan().steps}


def test_工作流和画板里的转写引擎名改成提供方_再跑一次不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {"nodes": [
        {"id": "a", "type": "transcribe_asset", "config": {"asset_id": "x", "engine": "auto"}},
        {"id": "b", "type": "transcribe_asset", "config": {"asset_id": "x", "engine": "whisperx"}},
        {"id": "c", "type": "transcribe_asset", "config": {"asset_id": "x", "engine": "c0ffee-plugin-connection"}},
        {"id": "d", "type": "denoise_audio", "config": {"asset_id": "x", "engine": "auto"}},
        {"id": "loop", "type": "loop_foreach", "config": {"body": {"nodes": [
            {"id": "e", "type": "transcribe_asset", "config": {"engine": "funasr"}}], "edges": []}}},
    ], "edges": []}
    canvas = {"items": [
        {"id": "v", "kind": "video", "form": {"abilities": {"node:transcribe_asset": {"config": {"engine": "auto"}}}}},
        {"id": "p", "kind": "text", "form": {"producer": "node:transcribe_asset", "config": {"engine": "funasr"}}},
    ], "edges": []}
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="wf", graph=graph)
        board = Board(workspace_id=ws, name="b", canvas=canvas)
        db.add_all([workflow, board])
        db.commit()
        workflow_id, board_id = workflow.id, board.id

    _migrate_transcription_engines_are_providers()

    with SessionLocal() as db:
        nodes = {node["id"]: node["config"] for node in db.get(Workflow, workflow_id).graph["nodes"]}
        assert "engine" not in nodes["a"] and nodes["a"]["asset_id"] == "x"
        assert nodes["b"]["engine"] == "builtin:whisperx"
        assert nodes["c"]["engine"] == "c0ffee-plugin-connection", "插件连接 id 原样留着"
        assert nodes["d"]["engine"] == "auto", "别的节点不碰"
        assert nodes["loop"]["body"]["nodes"][0]["config"]["engine"] == "builtin:funasr", "循环体里的也改"
        items = {item["id"]: item for item in db.get(Board, board_id).canvas["items"]}
        assert "engine" not in items["v"]["form"]["abilities"]["node:transcribe_asset"]["config"]
        assert items["p"]["form"]["config"]["engine"] == "builtin:funasr"

    with engine.connect() as conn:
        before = conn.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}).scalar()
    _migrate_transcription_engines_are_providers()
    with engine.connect() as conn:
        after = conn.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}).scalar()
    assert json.loads(before) == json.loads(after) if isinstance(before, str) else before == after
