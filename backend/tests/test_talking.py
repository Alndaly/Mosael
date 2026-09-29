"""数字人第 3 步(ADR 0028 §4):人物资产「让它说话」、图片格「让它说话」、视频格「对口型」。

配音、生成、模型清单都换成假的;钉住的是:授权门槛在起任务之前拦、脸和嗓子从哪来、素材挂成什么角色、
模型只挑声明了那种模式的、画板上各挂在哪种格子上。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.domain.workflows import NODE_TYPES, WorkflowDomainError
from app.domain.workflows.executors import talking
from tests.util import fresh_client, seed_assets

S2V = {"id": "p:video:wan2.2-s2v", "provider": "alibaba", "provider_profile_id": "p", "model": "wan2.2-s2v",
       "label": "百炼 · 说话照片", "is_default": False, "adapter_available": True,
       "capabilities": {"modes": ["speech-to-video"]}}
RETALK = {**S2V, "id": "p:video:videoretalk", "model": "videoretalk", "label": "百炼 · 改口型",
          "capabilities": {"modes": ["video-lipsync"]}}
SEEDANCE = {**S2V, "id": "p:video:seedance", "model": "seedance", "label": "Seedance", "is_default": True,
            "capabilities": {"modes": ["image-to-video"]}}


class Fakes:
    def __init__(self, ws: str) -> None:
        self.ws = ws
        self.spoken: list[dict[str, Any]] = []
        self.generated: list[dict[str, Any]] = []

    def speak(self, db, scope, config):
        self.spoken.append(config)
        seed_assets(self.ws, {f"voice-{len(self.spoken)}": "audio"})
        return {"asset_id": f"voice-{len(self.spoken)}"}

    def create(self, db, **kwargs):
        self.generated.append(kwargs)
        return SimpleNamespace(id="g"), SimpleNamespace(id="j")


@pytest.fixture()
def setup(monkeypatch):
    from app.domain import generation
    from app.domain.generation import resolution, runner
    from app.domain.workflows.executors import subjobs

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"face": "image", "side": "image", "clip": "video", "line": "audio"})
    fakes = Fakes(ws)
    monkeypatch.setattr(subjobs, "synthesize_speech", fakes.speak)
    monkeypatch.setattr(generation, "create_generation_job", fakes.create)
    monkeypatch.setattr(runner, "start_generation_thread", lambda generation_id: None)
    monkeypatch.setattr(resolution, "generation_options", lambda db, kind, user_id=None: [SEEDANCE, S2V, RETALK])
    monkeypatch.setattr(talking, "wait_for_job", lambda job_id, release=None: SimpleNamespace(result={"asset_ids": ["talk"]}))
    return client, ws, fakes


def _scope(ws: str):
    return SimpleNamespace(workspace_id=ws, id="board:b", name="画板")


def _character(client, ws: str, **attributes) -> str:
    made = client.post("/api/entities", json={"workspace_id": ws, "kind": "character", "name": "小美", "attributes": attributes}).json()
    for asset_id, role in (("side", "side"), ("face", "front")):
        client.post(f"/api/entities/{made['id']}/references", json={"asset_id": asset_id, "role": role})
    return made["id"]


def _roles(fakes: Fakes) -> list[tuple[str, str]]:
    return [(one["asset_id"], one["role"]) for one in fakes.generated[-1]["source_assets"]]


def test_人物说话_用它自己的嗓子配音_正面图加这段配音做说话照片(setup) -> None:
    client, ws, fakes = setup
    person = _character(client, ws, voice_engine="builtin:edge", voice_id="zh-CN-XiaoxiaoNeural")
    with SessionLocal() as db:
        out = talking.entity_speak(db, _scope(ws), {"entity_id": person, "text": "大家好,我是小美"})
    assert fakes.spoken == [{"text": "大家好,我是小美", "engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"}]
    assert _roles(fakes) == [("face", "first_frame"), ("voice-1", "driving_audio")], "正面图是脸,不是挑图先后的第一张"
    assert fakes.generated[-1]["model"] == "wan2.2-s2v", "默认视频模型不会说话照片,就用第一个会的"
    assert out == {"asset_id": "talk", "asset_ids": ["talk"], "audio_asset_id": "voice-1"}


def test_人物说话的门槛_真人没声明_没音色_不是人物_都在起任务之前拦(setup) -> None:
    client, ws, fakes = setup
    real = _character(client, ws, real_person=True, voice_engine="builtin:edge", voice_id="v")
    mute = _character(client, ws)
    place = client.post("/api/entities", json={"workspace_id": ws, "kind": "location", "name": "天台"}).json()["id"]
    for entity_id, key in ((real, "wfErr_entitySpeakNoConsent"), (mute, "wfErr_entitySpeakNoVoice"),
                           (place, "wfErr_entitySpeakCharacterOnly")):
        with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
            talking.entity_speak(db, _scope(ws), {"entity_id": entity_id, "text": "你好"})
        assert caught.value.key == key
    assert fakes.spoken == [] and fakes.generated == [], "拦在配音和生成之前,一分钱不花"


def test_图片格说话_没确认授权不跑_确认了用挑的嗓子(setup) -> None:
    _client, ws, fakes = setup
    config = {"asset_id": "face", "text": "你好", "engine": "builtin:clone", "voice": "v1"}
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        talking.image_speak(db, _scope(ws), config)
    assert caught.value.key == "wfErr_talkingNeedsConsent" and fakes.spoken == []
    with SessionLocal() as db:
        talking.image_speak(db, _scope(ws), {**config, "consent": "yes", "model": "p:video:wan2.2-s2v"})
    assert _roles(fakes) == [("face", "first_frame"), ("voice-1", "driving_audio")]


def test_对口型_接了上游音频就不配音_也不交回那段音频_没接就用稿子配(setup) -> None:
    _client, ws, fakes = setup
    with SessionLocal() as db:
        given = talking.video_lipsync(db, _scope(ws), {"asset_id": "clip", "audio_asset_id": "line", "consent": "yes"})
    assert fakes.spoken == [] and given["audio_asset_id"] == "", "画板上不多出一格重复的音频"
    assert _roles(fakes) == [("clip", "source_video"), ("line", "driving_audio")]
    assert fakes.generated[-1]["model"] == "videoretalk", "只挑声明了改口型的模型"
    with SessionLocal() as db:
        voiced = talking.video_lipsync(db, _scope(ws), {"asset_id": "clip", "text": "新台词", "voice": "v1", "consent": "yes"})
    assert voiced["audio_asset_id"] == "voice-1"


def test_没有会这一种的模型_说该去接哪一种(setup, monkeypatch) -> None:
    from app.domain.generation import resolution

    _client, ws, _fakes = setup
    monkeypatch.setattr(resolution, "generation_options", lambda db, kind, user_id=None: [SEEDANCE])
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        talking.video_lipsync(db, _scope(ws), {"asset_id": "clip", "audio_asset_id": "line", "consent": "yes"})
    assert caught.value.key == "wfErr_lipsyncNoModel"


def test_画板上_人物格_图片格_视频格各有一项_对口型不挂在音频格上() -> None:
    from app.domain.boards.transforms import board_hosts, board_role, host_entity_kinds, host_fields

    expected = {"entity_speak": ("entity",), "image_speak": ("image",), "video_lipsync": ("video",)}
    for node_type, hosts in expected.items():
        meta = NODE_TYPES[node_type]
        assert board_role(meta) == "ability" and board_hosts(meta) == hosts, node_type
    assert host_fields(NODE_TYPES["video_lipsync"]) == {"video": "asset_id"}
    assert host_entity_kinds(NODE_TYPES["entity_speak"]) == ["character"], "只有人物有「让它说话」"


def test_详情页上让真人说话_没声明就当场_422_不起任务(setup) -> None:
    from app.db.models import Job

    client, ws, fakes = setup
    real = _character(client, ws, real_person=True, voice_engine="builtin:edge", voice_id="v")
    refused = client.post(f"/api/entities/{real}/draw", json={"ability": "speak", "text": "你好"})
    assert refused.status_code == 422 and "声明" in refused.json()["detail"]
    with SessionLocal() as db:
        assert db.query(Job).filter(Job.kind == "entity_draw").count() == 0
    assert fakes.spoken == []
