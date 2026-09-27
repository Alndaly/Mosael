"""长稿分段配音(ADR 0028 阶段 3「稿子 → 数字人口播」):按句切、逐句配音、按**实测时长**凑成说话照片接得住的段。

- 句子不从中间断开;估着太长的句子先按逗号断;
- 分组看配出来的真实时长,上限来自所选模型的描述符(`source_duration_seconds.driving_audio`),`max_seconds` 只能往小里调;
- 一组几句拼成一段音频,一句的直接用那一段;字幕时间是配音的实测时长,不再转写;
- 克隆音色没声明的在配第一句之前就拦;一句配出来还超上限就说是哪一句,不去生成;
- 「让它说话」接上游的一段音频时不再配音。
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import talking
from app.domain.workflows.executors.talking import split_script, talking_segments
from tests.util import fresh_client, make_voice, seed_assets

S2V = {"id": "p:video:wan2.2-s2v", "provider": "alibaba", "provider_profile_id": "p", "model": "wan2.2-s2v",
       "capabilities": {"modes": ["speech-to-video"], "source_duration_seconds": {"driving_audio": [1, 20]}}}


def test_按句切_长句按逗号再断() -> None:
    assert split_script("第一句。第二句！\nThird one. 第四句？", 20) == ["第一句。", "第二句！", "Third one.", "第四句？"]
    long = "今天我们来聊一聊," * 12 + "就这样。"
    pieces = split_script(long, 10)
    assert len(pieces) > 1 and "".join(pieces) == long.strip(), "按逗号断,一个字不丢"
    assert all(len(one) / 4 <= 10 or "," not in one[:-1] for one in pieces)


@pytest.fixture()
def voicing(monkeypatch):
    """配音换成假的:每句一段素材,时长由句子里的数字给(「八」→ 8 秒这种太绕,直接查表)。"""
    from app.domain.workflows.executors import subjobs

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seconds: dict[str, float] = {}
    spoken: list[str] = []

    def fake_speak(db, scope, config):
        spoken.append(config["text"])
        asset = Asset(workspace_id=ws, kind="audio", name=config["text"], file_key="x.wav",
                      media_info={"duration": seconds[config["text"]]})
        db.add(asset)
        db.commit()
        return {"asset_id": asset.id}

    joined: list[list[str]] = []

    def fake_concat(db, scope, assets, name):
        joined.append([one.name for one in assets])
        return f"joined-{len(joined)}"

    monkeypatch.setattr(subjobs, "synthesize_speech", fake_speak)
    monkeypatch.setattr(talking, "_concat_audio", fake_concat)
    monkeypatch.setattr(talking, "_pick_model", lambda db, choice, mode: S2V)
    return SimpleNamespace(ws=ws, seconds=seconds, spoken=spoken, joined=joined,
                           scope=SimpleNamespace(workspace_id=ws, id="wf:1", name="口播"))


def test_按实测时长凑段_字幕时间照配音(voicing) -> None:
    voicing.seconds.update({"甲。": 8, "乙。": 7, "丙。": 6, "丁。": 9})
    with SessionLocal() as db:
        out = talking_segments(db, voicing.scope, {"text": "甲。乙。丙。丁。", "engine": "edge", "voice": "v"})
    assert voicing.joined == [["甲。", "乙。"], ["丙。", "丁。"]], "8+7=15,再加 6 就超 20 秒 —— 从句子之间断"
    assert [(one["audio_asset_id"], one["start"], one["duration"], one["text"]) for one in out["segments"]] == [
        ("joined-1", 0, 15, "甲。乙。"), ("joined-2", 15, 15, "丙。丁。")]
    assert out["cues"] == [{"start": 0, "end": 8, "text": "甲。"}, {"start": 8, "end": 15, "text": "乙。"},
                           {"start": 15, "end": 21, "text": "丙。"}, {"start": 21, "end": 30, "text": "丁。"}]
    assert (out["count"], out["duration"]) == (2, 30)


def test_一句一段的直接用那一段_上限只能往小里调(voicing) -> None:
    voicing.seconds.update({"甲。": 8, "乙。": 7})
    with SessionLocal() as db:
        out = talking_segments(db, voicing.scope, {"text": "甲。乙。", "engine": "edge", "voice": "v", "max_seconds": 10})
        assert out["count"] == 2 and voicing.joined == []
        assert db.get(Asset, out["segments"][0]["audio_asset_id"]).name == "甲。"
        voicing.joined.clear()
        wider = talking_segments(db, voicing.scope, {"text": "甲。乙。", "engine": "edge", "voice": "v", "max_seconds": 99})
    assert wider["count"] == 1, "填得比模型上限大不算数,按模型的 20 秒"


def test_一句配出来就超上限_说是哪一句_不往下走(voicing) -> None:
    voicing.seconds.update({"很长的一句。": 23})
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as refused:
        talking_segments(db, voicing.scope, {"text": "很长的一句。", "engine": "edge", "voice": "v"})
    assert refused.value.key == "wfErr_talkingSentenceTooLong" and refused.value.params["sentence"] == "很长的一句。"


def test_没声明的克隆音色_配第一句之前就拦(voicing) -> None:
    voice = make_voice(voicing.ws, "老王")
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as refused:
        talking_segments(db, voicing.scope, {"text": "你好。", "engine": "clone", "voice": voice})
    assert refused.value.key == "wfErr_voiceConsentMissing" and voicing.spoken == []


def test_让它说话接上游的一段音频_不再配音(monkeypatch) -> None:
    from app.domain.workflows.executors import subjobs

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"face": "image", "seg": "audio"})
    spoken: list = []
    sources: list = []
    monkeypatch.setattr(subjobs, "synthesize_speech", lambda db, scope, config: spoken.append(config) or {"asset_id": "x"})
    monkeypatch.setattr(talking, "_pick_model", lambda db, choice, mode: S2V)
    monkeypatch.setattr(talking, "_generate", lambda db, scope, model, src: sources.append(src) or ["talk"])
    scope = SimpleNamespace(workspace_id=ws, id="wf:1", name="口播")
    with SessionLocal() as db:
        out = talking.image_speak(db, scope, {"asset_id": "face", "audio_asset_id": "seg", "consent": "yes"})
    assert spoken == [] and out == {"asset_id": "talk", "asset_ids": ["talk"], "audio_asset_id": ""}
    assert sources == [[{"asset_id": "face", "role": "first_frame"}, {"asset_id": "seg", "role": "driving_audio"}]]


def test_拼接真的把几段接成一段() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    ids = []
    with SessionLocal() as db:
        for index in range(2):
            key = f"talk-test-{index}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            str(settings.data_dir / key)], check=True)
            asset = Asset(workspace_id=ws, kind="audio", name=key, file_key=key, media_info={"duration": 1.0})
            db.add(asset)
            db.flush()
            ids.append(asset)
        db.commit()
        joined = talking._concat_audio(db, SimpleNamespace(workspace_id=ws, id="wf", name="口播"), ids, "口播第 1 段")
        made = db.get(Asset, joined)
        assert made.workspace_id == ws and made.kind == "audio"
        assert abs(float(made.media_info["duration"]) - 2.0) < 0.1
