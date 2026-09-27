"""克隆音色的授权声明(ADR 0028 §5):建的时候必须说这把嗓子是谁的;升级前建的是「未声明」,照常能配音,
用于数字人(让它说话、对口型)之前要补上 —— 在配音之前拦下,不白付那段配音。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.db.models import Voice
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import talking
from tests.test_voices import _tiny_wav
from tests.util import fresh_client, make_voice, seed_assets


def _upload(client, ws: str, **extra):
    return client.post("/api/voices/upload", data={"workspace_id": ws, "name": "小明", "reference_text": "你好", **extra},
                       files={"file": ("ref.wav", _tiny_wav(), "audio/wav")})


def test_建克隆音色必须选一项声明_谁何时由服务端记() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    assert _upload(client, ws).status_code == 422, "不选不给建"
    refused = _upload(client, ws, consent_kind="undeclared")
    assert refused.status_code == 422 and "self" in refused.json()["detail"], "「未声明」不是一项声明"
    made = _upload(client, ws, consent_kind="fictional")
    assert made.status_code == 200, made.text
    assert made.json()["consent_kind"] == "fictional" and made.json()["consent_at"]
    with SessionLocal() as db:
        assert db.get(Voice, made.json()["id"]).consent_by


def test_未声明的音色补上声明() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    voice = make_voice(ws)
    listed = client.get("/api/voices", params={"workspace_id": ws}).json()
    assert listed[0]["consent_kind"] == "undeclared" and listed[0]["consent_at"] is None
    declared = client.patch(f"/api/voices/{voice}", json={"consent_kind": "self"})
    assert declared.status_code == 200 and declared.json()["consent_kind"] == "self" and declared.json()["consent_at"]
    assert client.patch(f"/api/voices/{voice}", json={"consent_kind": "maybe"}).status_code == 422


def test_迁移_已有的音色写成未声明_再跑一次不动() -> None:
    from app.db.migrations import _migrate_voices_declare_consent, migration_plan

    assert "migrate-voices-declare-consent" in {step.name for step in migration_plan().steps}
    fresh_client()
    _migrate_voices_declare_consent()
    _migrate_voices_declare_consent()


@pytest.fixture()
def gate(monkeypatch):
    from app.domain.workflows.executors import subjobs

    spoken: list = []
    monkeypatch.setattr(subjobs, "synthesize_speech", lambda db, scope, config: spoken.append(config) or {"asset_id": "x"})
    monkeypatch.setattr(talking, "_pick_model", lambda db, choice, mode: {"id": "m"})
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"face": "image"})
    return client, ws, spoken


def test_没声明的克隆音色用于数字人_配音之前就拦(gate) -> None:
    client, ws, spoken = gate
    voice = make_voice(ws, "老王")
    scope = SimpleNamespace(workspace_id=ws, id="board:b", name="画板")
    config = {"asset_id": "face", "text": "你好", "engine": "clone", "voice": voice, "consent": "yes"}
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as refused:
        talking.image_speak(db, scope, config)
    assert refused.value.key == "wfErr_voiceConsentMissing" and spoken == []

    person = client.post("/api/entities", json={"workspace_id": ws, "kind": "character", "name": "小美",
                                                "attributes": {"voice_engine": "clone", "voice_id": voice}}).json()["id"]
    client.post(f"/api/entities/{person}/references", json={"asset_id": "face", "role": "front"})
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as refused:
        talking.check_entity_speak(db, ws, {"entity_id": person, "text": "你好"}, None)
    assert refused.value.key == "wfErr_voiceConsentMissing"


def test_引擎自带的嗓子不是谁的克隆_不问声明(gate) -> None:
    from app.domain.workflows.executors.talking import _require_voice_consent

    _client, ws, _spoken = gate
    voice = make_voice(ws)
    with SessionLocal() as db:
        _require_voice_consent(db, "edge", "zh-CN-XiaoxiaoNeural")
        db.get(Voice, voice).consent_kind = "self"
        db.commit()
        _require_voice_consent(db, "clone", voice)
        _require_voice_consent(db, "", voice)
