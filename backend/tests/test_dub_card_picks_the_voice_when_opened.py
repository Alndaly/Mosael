"""智能体的字幕配音卡,引擎和音色在**开卡时**就定成确定的一对 —— 和 generate_audio 同一个认法(pick_speech)。

此前开卡只认引擎、不看音色:一个不存在的克隆音色照样开卡,用户批了之后每一句都合成失败;只给了 Edge 的音色、
没写引擎,被当成克隆音色去配音库里找。走真的开卡入口(request_confirmation)。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import User
from app.domain.agent.confirmations import request_confirmation
from app.domain.agent.errors import ConfirmationError
from tests.util import fresh_client, make_voice


@pytest.fixture(autouse=True)
def _clone_engine_installed(monkeypatch) -> None:
    """本机装没装克隆引擎是机器的状态;这里要的是「装了」的那种机器。"""
    from app.ai.runtime import tts_models

    monkeypatch.setattr(tts_models, "runtime_status", lambda engine: (True, True))


def _sequence(client) -> tuple[str, str]:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": workspace, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": workspace, "project_id": project, "name": "S"}).json()["id"]
    client.post(f"/api/sequences/{sequence}/tracks", json={"kind": "subtitle"})
    return workspace, sequence


def _open(workspace: str, payload: dict):
    with SessionLocal() as db:
        user = db.scalars(select(User)).first()
        card = request_confirmation(db, workspace_id=workspace, tool="dub_subtitles", payload=payload,
                                    actor_id=user.id, requested_by=user.id)
        db.commit()
        return card.payload


def test_不在这个工作区的克隆音色_开卡时就拒() -> None:
    workspace, sequence = _sequence(fresh_client())
    with pytest.raises(ConfirmationError) as refused:
        _open(workspace, {"sequence_id": sequence, "engine": "builtin:clone", "voice_id": "no-such-voice"})
    assert refused.value.key == "voiceErr_voiceNotInWorkspace"


def test_只给了音色_按音色认出是哪一家_写回卡上() -> None:
    client = fresh_client()
    workspace, sequence = _sequence(client)
    payload = _open(workspace, {"sequence_id": sequence, "engine_voice": "zh-CN-XiaoxiaoNeural"})
    assert (payload["engine"], payload["engine_voice"], payload["voice_id"]) == ("builtin:edge", "zh-CN-XiaoxiaoNeural", "")

    voice = make_voice(workspace, "我的嗓子")
    payload = _open(workspace, {"sequence_id": sequence, "voice_id": voice})
    assert (payload["engine"], payload["voice_id"], payload["engine_voice"]) == ("builtin:clone", voice, "")


def test_引擎音色都没给_说要成对点名_不替人挑() -> None:
    workspace, sequence = _sequence(fresh_client())
    with pytest.raises(ConfirmationError) as refused:
        _open(workspace, {"sequence_id": sequence})
    assert refused.value.key == "speechErr_pickEngineAndVoice"
