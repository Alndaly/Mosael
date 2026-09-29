"""迁移 migrate-speech-engines-are-providers(ADR 0032 第四步):配音引擎的裸名改成能力表的提供方 id。

`clone` / `edge` / `volcano` / `alibaba`…… → `builtin:<引擎>`;空的不动(画板配音表单里空 = 克隆音色);认不出的
(插件连接 id)原样留着。工作流(含循环体)、画板(配音表单顶层、节点表单与能力设置)、实体的 voice_engine、
智能体语音偏好都改;再跑一次什么都不动。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_speech_engines_are_providers, migration_plan
from app.db.models import Board, Entity, Workflow
from tests.util import fresh_client


def test_迁移登记在计划里() -> None:
    assert "migrate-speech-engines-are-providers" in {step.name for step in migration_plan().steps}


def test_四处存着的配音引擎都换成提供方_再跑一次不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    me = client.get("/api/auth/me").json()["id"]
    graph = {"nodes": [
        {"id": "a", "type": "synthesize_speech", "config": {"text": "hi", "engine": "clone", "voice": "v"}},
        {"id": "b", "type": "dub_subtitles", "config": {"engine": "alibaba-cosyvoice", "voice": "x"}},
        {"id": "c", "type": "image_speak", "config": {"engine": "c0ffee-plugin", "voice": "x"}},
        {"id": "d", "type": "translate", "config": {"engine": "edge"}},
        {"id": "loop", "type": "loop_foreach", "config": {"body": {"nodes": [
            {"id": "e", "type": "talking_segments", "config": {"engine": "edge"}}], "edges": []}}},
    ], "edges": []}
    canvas = {"items": [
        {"id": "s", "kind": "audio", "form": {"producer": "speak", "engine": "volcano", "engine_voice": "zh_x"}},
        {"id": "t", "kind": "audio", "form": {"producer": "speak", "engine": "", "voice_id": "v"}},
        {"id": "n", "kind": "video", "form": {"abilities": {"node:video_lipsync": {"config": {"engine": "openai"}}}}},
    ], "edges": []}
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="wf", graph=graph)
        board = Board(workspace_id=ws, name="b", canvas=canvas)
        person = Entity(workspace_id=ws, kind="character", name="甲", attributes={"voice_engine": "edge", "voice_id": "zh"})
        db.add_all([workflow, board, person])
        db.commit()
        workflow_id, board_id, person_id = workflow.id, board.id, person.id
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO agent_voice_prefs (owner_user_id, engine, engine_voice, engine_voice_resource, "
                          "engine_model, speed, enabled, updated_at) VALUES (:me, 'volcano', 'zh_x', '', '', 1.0, 1, "
                          "CURRENT_TIMESTAMP)"), {"me": me})

    _migrate_speech_engines_are_providers()
    _migrate_speech_engines_are_providers()

    with SessionLocal() as db:
        nodes = {node["id"]: node["config"] for node in db.get(Workflow, workflow_id).graph["nodes"]}
        assert nodes["a"]["engine"] == "builtin:clone"
        assert nodes["b"]["engine"] == "builtin:alibaba-cosyvoice"
        assert nodes["c"]["engine"] == "c0ffee-plugin", "插件连接 id 原样留着"
        assert nodes["d"]["engine"] == "edge", "翻译节点的 engine 不归这一步"
        assert nodes["loop"]["body"]["nodes"][0]["config"]["engine"] == "builtin:edge"
        items = {item["id"]: item for item in db.get(Board, board_id).canvas["items"]}
        assert items["s"]["form"]["engine"] == "builtin:volcano"
        assert items["t"]["form"]["engine"] == "", "空 = 克隆音色,不动"
        assert items["n"]["form"]["abilities"]["node:video_lipsync"]["config"]["engine"] == "builtin:openai"
        assert db.get(Entity, person_id).attributes["voice_engine"] == "builtin:edge"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT engine FROM agent_voice_prefs WHERE owner_user_id = :me"), {"me": me}).scalar() \
            == "builtin:volcano"
