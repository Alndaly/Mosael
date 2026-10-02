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
        out = talking_segments(db, voicing.scope, {"text": "甲。乙。丙。丁。", "engine": "builtin:edge", "voice": "v"})
    assert voicing.joined == [["甲。", "乙。"], ["丙。", "丁。"]], "8+7=15,再加 6 就超 20 秒 —— 从句子之间断"
    assert [(one["audio_asset_id"], one["start"], one["duration"], one["text"]) for one in out["segments"]] == [
        ("joined-1", 0, 15, "甲。乙。"), ("joined-2", 15, 15, "丙。丁。")]
    assert out["cues"] == [{"start": 0, "end": 8, "text": "甲。"}, {"start": 8, "end": 15, "text": "乙。"},
                           {"start": 15, "end": 21, "text": "丙。"}, {"start": 21, "end": 30, "text": "丁。"}]
    assert (out["count"], out["duration"]) == (2, 30)


def test_每段带着起止和挑定的模型_下游字幕和说话照片接得上(voicing) -> None:
    """此前段落只有 start / duration:「生成字幕」按 start/end 读段落,接它就是 0 条;下游「让它说话」留空模型时
    自己再挑一次,可能挑到上限不同的另一个 —— 分段是按这个模型的上限切的。"""
    from app.domain.workflows import NODE_TYPES

    voicing.seconds.update({"甲。": 8, "乙。": 7, "丙。": 6})
    with SessionLocal() as db:
        out = talking_segments(db, voicing.scope, {"text": "甲。乙。丙。", "engine": "builtin:edge", "voice": "v"})
    assert [(one["start"], one["end"]) for one in out["segments"]] == [(0, 15), (15, 21)]
    assert {one["model"] for one in out["segments"]} == {S2V["id"]} and out["model"] == S2V["id"]
    declared = NODE_TYPES["talking_segments"]
    assert declared["config"]["voice"]["required"] is True, "全是逐句配音,没有嗓子什么都做不了"
    assert "model" in declared["outputs"]


def test_一句一段的直接用那一段_上限只能往小里调(voicing) -> None:
    voicing.seconds.update({"甲。": 8, "乙。": 7})
    with SessionLocal() as db:
        out = talking_segments(db, voicing.scope, {"text": "甲。乙。", "engine": "builtin:edge", "voice": "v", "max_seconds": 10})
        assert out["count"] == 2 and voicing.joined == []
        assert db.get(Asset, out["segments"][0]["audio_asset_id"]).name == "甲。"
        voicing.joined.clear()
        wider = talking_segments(db, voicing.scope, {"text": "甲。乙。", "engine": "builtin:edge", "voice": "v", "max_seconds": 99})
    assert wider["count"] == 1, "填得比模型上限大不算数,按模型的 20 秒"


def test_一句配出来就超上限_说是哪一句_不往下走(voicing) -> None:
    voicing.seconds.update({"很长的一句。": 23})
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as refused:
        talking_segments(db, voicing.scope, {"text": "很长的一句。", "engine": "builtin:edge", "voice": "v"})
    assert refused.value.key == "wfErr_talkingSentenceTooLong" and refused.value.params["sentence"] == "很长的一句。"


def test_没声明的克隆音色_配第一句之前就拦(voicing) -> None:
    voice = make_voice(voicing.ws, "老王")
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as refused:
        talking_segments(db, voicing.scope, {"text": "你好。", "engine": "builtin:clone", "voice": voice})
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
    monkeypatch.setattr(talking, "_generate", lambda db, scope, model, src, parameters=None: sources.append(src) or ["talk"])
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
            asset = Asset(workspace_id=ws, kind="audio", name=key, file_key=key, media_info={"duration": 1.0},
                          ai_generated=True)
            db.add(asset)
            db.flush()
            ids.append(asset)
        db.commit()
        joined = talking._concat_audio(db, SimpleNamespace(workspace_id=ws, id="wf", name="口播"), ids, "口播第 1 段")
        made = db.get(Asset, joined)
        assert made.workspace_id == ws and made.kind == "audio"
        assert abs(float(made.media_info["duration"]) - 2.0) < 0.1
        # 出处是拼进来的那几段;它们是合成的配音,拼出来的这段也含 AI。
        assert made.derived_from == [{"asset_id": one.id, "op": "concat"} for one in ids]
        assert made.ai_generated is True


KLING = {**S2V, "id": "k:video:kling-avatar", "model": "kling-avatar",
         "capabilities": {"modes": ["speech-to-video"], "source_duration_seconds": {"driving_audio": [2, 10]}}}


def test_整篇就一句短的_补静音到下限_不交一段注定被拒的音频(voicing, monkeypatch) -> None:
    """此前分组只看上限:一句「好的。」单独成段,到提交时才被可灵(2 秒起)拒。"""
    monkeypatch.setattr(talking, "_pick_model", lambda db, choice, mode: KLING)
    padded: list[tuple[str, float]] = []
    monkeypatch.setattr(talking, "_pad_audio",
                        lambda db, scope, asset, seconds, name: padded.append((asset.name, seconds)) or "padded-1")
    voicing.seconds.update({"好的。": 1})
    with SessionLocal() as db:
        out = talking_segments(db, voicing.scope, {"text": "好的。", "engine": "builtin:edge", "voice": "v"})
    assert padded == [("好的。", 2.0)]
    assert [(one["audio_asset_id"], one["duration"]) for one in out["segments"]] == [("padded-1", 2.0)]


def test_夹在两段长的中间的短句_补静音到下限_后面的段往后排(voicing, monkeypatch) -> None:
    monkeypatch.setattr(talking, "_pick_model", lambda db, choice, mode: KLING)
    padded: list[tuple[str, float]] = []
    monkeypatch.setattr(talking, "_pad_audio",
                        lambda db, scope, asset, seconds, name: padded.append((asset.name, seconds)) or "padded-1")
    voicing.seconds.update({"甲。": 9.5, "嗯。": 1, "乙。": 9.5})
    with SessionLocal() as db:
        out = talking_segments(db, voicing.scope, {"text": "甲。嗯。乙。", "engine": "builtin:edge", "voice": "v"})
    assert padded == [("嗯。", 2.0)], "9.5+1 超了 10 秒,前后都并不进,只能补到 2 秒"
    assert [(one["audio_asset_id"], one["start"], one["duration"]) for one in out["segments"]][1:] == [
        ("padded-1", 9.5, 2.0), (out["segments"][2]["audio_asset_id"], 11.5, 9.5)]
    #: 字幕照配音的实测时长,补的静音不算字幕。
    assert out["cues"][1] == {"start": 9.5, "end": 10.5, "text": "嗯。"}
    assert out["duration"] == 21


def test_这一轮在停_不再配下一句(voicing, monkeypatch) -> None:
    from app.domain.workflows.executors import subjobs
    from app.domain.workflows.run_scope import halt_scope

    voicing.seconds.update({"甲。": 3, "乙。": 3, "丙。": 3})
    speak = subjobs.synthesize_speech
    with halt_scope() as halt:
        def speak_then_stop(db, scope, config):
            out = speak(db, scope, config)
            halt.set()
            return out

        monkeypatch.setattr(subjobs, "synthesize_speech", speak_then_stop)
        with SessionLocal() as db, pytest.raises(WorkflowDomainError) as stopped:
            talking_segments(db, voicing.scope, {"text": "甲。乙。丙。", "engine": "builtin:edge", "voice": "v"})
    assert stopped.value.key == "wfErr_cancelled" and voicing.spoken == ["甲。"], "配完第一句就停,后两句不再付费"
