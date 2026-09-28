"""迁移 migrate-audio-engines-are-providers(ADR 0032 第二步):降噪、分离节点存着的引擎名改成能力表的提供方 id。

`auto` / 空 → 清掉(按运行者的默认);本机引擎名 → `builtin:<引擎>`。工作流(含循环体里的)和画板上的能力设置都改;
认不出的值(插件连接 id)原样留着;再跑一次什么都不动。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_audio_engines_are_providers, migration_plan
from app.db.models import Board, Workflow
from tests.util import fresh_client


def test_迁移登记在计划里() -> None:
    assert "migrate-audio-engines-are-providers" in {step.name for step in migration_plan().steps}


def test_工作流和画板里的引擎名改成提供方_再跑一次不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {"nodes": [
        {"id": "a", "type": "denoise_audio", "config": {"asset_id": "x", "engine": "auto", "strength": "light"}},
        {"id": "b", "type": "denoise_audio", "config": {"asset_id": "x", "engine": "rnnoise"}},
        {"id": "c", "type": "separate_audio", "config": {"asset_id": "x", "engine": "demucs"}},
        {"id": "d", "type": "denoise_audio", "config": {"asset_id": "x", "engine": "c0ffee-plugin-connection"}},
        {"id": "loop", "type": "loop_foreach", "config": {"body": {"nodes": [
            {"id": "e", "type": "separate_audio", "config": {"engine": "auto"}}], "edges": []}}},
    ], "edges": []}
    canvas = {"items": [
        {"id": "v", "kind": "video", "form": {"abilities": {"node:denoise_audio": {"config": {"engine": "deepfilternet"}}}}},
        {"id": "n", "kind": "note", "text": "hi"},
    ], "edges": []}
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="wf", graph=graph)
        board = Board(workspace_id=ws, name="b", canvas=canvas)
        db.add_all([workflow, board])
        db.commit()
        workflow_id, board_id = workflow.id, board.id

    _migrate_audio_engines_are_providers()

    with SessionLocal() as db:
        nodes = {node["id"]: node["config"] for node in db.get(Workflow, workflow_id).graph["nodes"]}
        assert "engine" not in nodes["a"] and nodes["a"]["strength"] == "light"
        assert nodes["b"]["engine"] == "builtin:rnnoise" and nodes["c"]["engine"] == "builtin:demucs"
        assert nodes["d"]["engine"] == "c0ffee-plugin-connection", "插件连接 id 原样留着"
        assert "engine" not in nodes["loop"]["body"]["nodes"][0]["config"], "循环体里的也改"
        ability = db.get(Board, board_id).canvas["items"][0]["form"]["abilities"]["node:denoise_audio"]
        assert ability["config"]["engine"] == "builtin:deepfilternet"

    with engine.connect() as conn:
        before = conn.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}).scalar()
    _migrate_audio_engines_are_providers()
    with engine.connect() as conn:
        after = conn.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}).scalar()
    assert json.loads(before) == json.loads(after) if isinstance(before, str) else before == after
