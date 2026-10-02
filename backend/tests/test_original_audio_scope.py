"""配音之后的原声处理**只动原片、只动配音盖到的那几段**。

审查时在真的配音任务上实测到的:

- 选「静音原声」,BGM 那条轨跟着整条静音 —— 成片里配音之外什么都没了;没配音的段落原声也没了。
- 选「只去人声」,BGM 也被拆一遍;第二次配音把第一次拆出来的背景音**再拆一遍、再叠一条轨**。

合成换成立刻交回一段音频,分离换成立刻交回一份背景音素材(两者都是付费 / 耗时的外部能力);
其余 —— 配音任务、原声处理、剪辑操作、渲染计划 —— 都是真的。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Job, Sequence, Transcript
from app.domain.jobs import create_job, wait_for_idle_jobs
from app.domain.render import build_plan_for_sequence
from app.domain.voices.original_audio import muted_gain_keyframes
from app.domain.voices.subtitle_dub import start_subtitle_dub
from tests.util import fresh_client


def _timeline(client, *, bgm: bool = True) -> tuple[str, str, str, str]:
    """原片(视频轨)+ BGM(音频轨)+ 一条字幕 1–3 秒。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 10.0})
        music = Asset(workspace_id=ws, kind="audio", name="BGM", file_key="media/m.mp3", media_info={"duration": 10.0})
        db.add_all([footage, music])
        db.commit()
        footage_id, music_id = footage.id, music.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).status_code == 200
    if bgm:
        assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": music_id}).status_code == 200
    seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    track = next(t["id"] for t in seq["tracks"] if t["kind"] == "subtitle")
    seq = client.post(f"/api/sequences/{sid}/subtitles/generate",
                      json={"track_id": track, "cues": [{"text": "甲", "timeline_start": 1.0, "duration": 2.0}]}).json()
    line = next(t for t in seq["tracks"] if t["id"] == track)["clips"][0]["id"]
    return ws, sid, line, music_id


def _dub(monkeypatch, ws: str, sid: str, line: str, mode: str, voice: str = "a") -> Job:
    import app.domain.voices.voices as voices_module

    def fake_synthesis(db, *, text, project_id, created_by, **_):
        audio = Asset(workspace_id=ws, kind="audio", name=text, file_key="media/d.wav", media_info={"duration": 2.0})
        db.add(audio)
        db.flush()
        job = create_job(db, workspace_id=ws, kind="tts", payload={}, created_by=None)
        job.status, job.result = "succeeded", {"asset_id": audio.id}
        return job

    monkeypatch.setattr(voices_module, "start_synthesis", fake_synthesis)
    with SessionLocal() as db:
        job_id = start_subtitle_dub(db, sequence_id=sid, clip_ids=[line], match_duration=False, created_by=None,
                                    synthesis={"engine": "builtin:volcano", "engine_voice": voice, "workspace_id": ws},
                                    original_audio=mode).id
        db.commit()
    assert wait_for_idle_jobs(15)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "succeeded", job.error
        return job


def test_静音原声只静原片_只静配音占着的那一段_BGM不动(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, line, music_id = _timeline(client)
    _dub(monkeypatch, ws, sid, line, "mute")
    with SessionLocal() as db:
        sequence = db.get(Sequence, sid)
        assert not any(track.muted for track in sequence.tracks), "没有哪条轨被整条静音"
        plan = build_plan_for_sequence(db, sid)
        [music] = [item for item in plan.audio_overlays if item.source.asset_id == music_id]
        assert not music.gain_keyframes and music.gain == 1, "BGM 原样(静音的片段不会出现在混音里)"
        [footage] = [segment for segment in plan.video_segments if segment.kind == "clip"]
        curve = dict(footage.gain_keyframes)
        # 原片 0–10 秒,配音 1–3 秒:进度 0.1–0.3 是 0,两头是原音量。
        assert curve[0.1] == 0 and curve[0.3] == 0 and curve[0.0] == 1 and curve[1.0] == 1


def test_重复静音同一段_关键帧不越堆越多(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, line, _ = _timeline(client, bgm=False)
    _dub(monkeypatch, ws, sid, line, "mute", voice="a")
    with SessionLocal() as db:
        first = next(t for t in db.get(Sequence, sid).tracks if t.kind == "video").clips[0].effects["gain_keyframes"]
    _dub(monkeypatch, ws, sid, line, "mute", voice="b")
    with SessionLocal() as db:
        again = next(t for t in db.get(Sequence, sid).tracks if t.kind == "video").clips[0].effects["gain_keyframes"]
    assert again == first


def test_静音窗外保留用户自己画的音量曲线() -> None:
    # 片段 10–20 秒,用户画了一条 1 → 0.5 的渐弱;配音占着 12–14 秒。
    existing = [{"t": 0.0, "gain": 1.0}, {"t": 1.0, "gain": 0.5}]
    points = {p["t"]: p["gain"] for p in muted_gain_keyframes(existing, 1.0, 10.0, 10.0, [(12.0, 14.0)])}
    assert points[0.0] == 1.0 and points[1.0] == 0.5
    assert points[0.2] == 0 and points[0.4] == 0
    assert points[0.195] == pytest.approx(0.9025), "窗口前的过渡起点:原曲线在那一刻的值"


def _fake_separation(monkeypatch, ws: str) -> list[tuple[str, tuple[float, float]]]:
    import app.domain.assets.separation as sep

    calls: list[tuple[str, tuple[float, float]]] = []

    def fake_separate(db, asset, engine="", owner_user_id=None, span=None, **_):
        calls.append((asset.name, span))
        made = {}
        for stem in ("vocals", "background"):
            row = Asset(workspace_id=ws, kind="audio", name=f"{asset.name}·{stem}", file_key=f"media/{stem}.wav",
                        derived_from=[{"asset_id": asset.id, "op": "separate"}],
                        media_info={"stem": stem, "source_range": list(span)})
            db.add(row)
            db.flush()
            made[stem] = row
        return SimpleNamespace(vocals=made["vocals"], background=made["background"], engine="fake")

    monkeypatch.setattr(sep, "available", lambda db, user=None, engine="": True)
    monkeypatch.setattr(sep, "separate_asset", fake_separate)
    return calls


def test_只去人声_只拆原片_第二次配音用缓存_不再叠背景音轨(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, line, music_id = _timeline(client)
    calls = _fake_separation(monkeypatch, ws)
    _dub(monkeypatch, ws, sid, line, "separate", voice="a")
    assert calls == [("原片", (0.0, 10.0))], "BGM 不拆;原片只拆用到的那一段"
    with SessionLocal() as db:
        tracks_after_first = len(db.get(Sequence, sid).tracks)
    _dub(monkeypatch, ws, sid, line, "separate", voice="b")
    assert len(calls) == 1, "第二次:原片已经静音、背景音也不是原声 —— 什么都不再拆"
    with SessionLocal() as db:
        sequence = db.get(Sequence, sid)
        assert len(sequence.tracks) == tracks_after_first, "没有再叠一条背景音轨"
        plan = build_plan_for_sequence(db, sid)
        [music] = [item for item in plan.audio_overlays if item.source.asset_id == music_id]
        assert music.gain == 1, "BGM 还在响(静音的片段不会出现在混音里)"


def test_拆过的素材再次需要时按缓存直接用(monkeypatch) -> None:
    """撤销了上一次配音(原片恢复发声)再配一次:拆出来的背景音还在,不用再拆。"""
    from app.domain.sequences.history import undo

    client = fresh_client()
    ws, sid, line, _ = _timeline(client, bgm=False)
    calls = _fake_separation(monkeypatch, ws)
    _dub(monkeypatch, ws, sid, line, "separate", voice="a")
    with SessionLocal() as db:
        undo(db, sid)
        db.commit()
    _dub(monkeypatch, ws, sid, line, "separate", voice="a")
    assert len(calls) == 1


def test_转写过的口播录音也算原声_没转写过的音频不算(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, line, music_id = _timeline(client)
    with SessionLocal() as db:
        db.add(Transcript(workspace_id=ws, asset_id=music_id))
        db.commit()
    _dub(monkeypatch, ws, sid, line, "mute")
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, sid)
        [voiceover] = [item for item in plan.audio_overlays if item.source.asset_id == music_id]
        assert dict(voiceover.gain_keyframes)[0.1] == 0, "有逐字稿的音频是口播,一起静"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_只拆用到的区间_真的只抽那一段声音(tmp_path) -> None:
    from app.media.audio_io import as_audio

    source = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=6:sample_rate=48000",
                    str(source)], check=True)
    audio = as_audio(source, tmp_path, (2.0, 3.5))
    probed = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(audio)],
                                       capture_output=True, text=True, check=True).stdout)
    assert audio != source, "只要一段时,音频也要抽出那一段,不能整份原样交出去"
    assert float(probed["format"]["duration"]) == pytest.approx(1.5, abs=0.05)
