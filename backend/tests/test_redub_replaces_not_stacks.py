"""重配一句是**替换**,不是叠加;一次配音在撤销栈上是**一步**。

审查时实测到的三件事(都在真的配音任务、真的时间线上跑,只把付费的合成换成立刻交回一段音频):

1. 换了嗓子把同一句再配一次,配音轨同一秒上叠着两段 —— 成片里两个人同时念这句话。
2. 同一句同一把嗓子再配一次,照样又合成一遍(又花一次钱)、又叠一段;中途断了的配音没法「接着配」。
3. 配 3 句再处理原声,撤销栈上多了 9 步;1000 句就是两千多次 ⌘Z,中间每一步都是「半配好」。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, Job, Sequence, SequenceOperation
from app.domain.jobs import create_job, wait_for_idle_jobs
from app.domain.sequences.history import can_undo, redo, undo
from app.domain.voices.subtitle_dub import DUB_LINE_KEY, start_subtitle_dub
from tests.util import fresh_client

VOICE_A = {"engine": "builtin:volcano", "engine_voice": "a"}
VOICE_B = {"engine": "builtin:volcano", "engine_voice": "b"}


def _timeline(client, cues: list[tuple[str, float, float]]) -> tuple[str, str, list[str]]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 20.0})
        db.add(footage)
        db.commit()
        footage_id = footage.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).status_code == 200
    seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    track = next(t["id"] for t in seq["tracks"] if t["kind"] == "subtitle")
    seq = client.post(
        f"/api/sequences/{sid}/subtitles/generate",
        json={"track_id": track, "cues": [{"text": t, "timeline_start": s, "duration": d} for t, s, d in cues]},
    ).json()
    clips = sorted(next(t for t in seq["tracks"] if t["id"] == track)["clips"], key=lambda c: c["timeline_start"])
    return ws, sid, [c["id"] for c in clips]


def _synth(monkeypatch, ws: str, *, fail: set[str] = frozenset()) -> list[tuple[str, str]]:
    """合成换成立刻交回一段 2 秒的音频;返回每次被调用时的 (文本, 嗓子)。`fail` 里的文本合成失败。"""
    import app.domain.voices.voices as voices_module

    calls: list[tuple[str, str]] = []

    def fake_synthesis(db, *, text, project_id, created_by, **synthesis):
        calls.append((text, synthesis.get("engine_voice", "")))
        job = create_job(db, workspace_id=ws, kind="tts", payload={}, created_by=None)
        if text in fail:
            job.status = "failed"
            job.error = "合成失败"
            return job
        audio = Asset(workspace_id=ws, kind="audio", name=text, file_key="media/d.wav", media_info={"duration": 2.0})
        db.add(audio)
        db.flush()
        job.status = "succeeded"
        job.result = {"asset_id": audio.id}
        return job

    monkeypatch.setattr(voices_module, "start_synthesis", fake_synthesis)
    return calls


def _dub(sid: str, ws: str, clip_ids: list[str], voice: dict, mode: str = "keep") -> Job:
    with SessionLocal() as db:
        job_id = start_subtitle_dub(db, sequence_id=sid, clip_ids=clip_ids, match_duration=True, created_by=None,
                                    synthesis={**voice, "workspace_id": ws}, original_audio=mode).id
        db.commit()
    assert wait_for_idle_jobs(15)
    with SessionLocal() as db:
        return db.get(Job, job_id)


def _dub_clips(sid: str) -> list[tuple[float, str]]:
    """配音轨上每一段:(落点, 念的是谁的嗓子)。"""
    with SessionLocal() as db:
        sequence = db.get(Sequence, sid)
        found = []
        for track in sequence.tracks:
            if track.role != "dub":
                continue
            for clip in track.clips:
                line = db.get(Asset, clip.asset_id).media_info[DUB_LINE_KEY]
                found.append((round(clip.timeline_start, 3), line["voice"]))
        return sorted(found)


def test_换嗓子重配同一句_旧的那段被换掉而不是叠着念(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, [line] = _timeline(client, [("甲", 1.0, 2.0)])
    _synth(monkeypatch, ws)
    assert _dub(sid, ws, [line], VOICE_A).status == "succeeded"
    assert _dub(sid, ws, [line], VOICE_B).status == "succeeded"
    clips = _dub_clips(sid)
    assert len(clips) == 1, f"同一秒上只该有一个人在念这句:{clips}"
    assert "engine_voice=b" in clips[0][1]


def test_同一句同一把嗓子已配过_不再合成也不再叠一段(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, lines = _timeline(client, [("甲", 1.0, 2.0), ("乙", 5.0, 2.0)])
    calls = _synth(monkeypatch, ws)
    _dub(sid, ws, lines, VOICE_A)
    calls.clear()
    job = _dub(sid, ws, lines, VOICE_A)
    assert job.status == "succeeded", job.error
    assert calls == [], "两句都配过了:一次付费合成都不该再发"
    assert job.result["skipped"] == 2 and job.result["done"] == 0
    assert len(_dub_clips(sid)) == 2


def test_中途失败的配音再跑一遍只补缺的那几句(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, lines = _timeline(client, [("甲", 1.0, 2.0), ("乙", 5.0, 2.0), ("丙", 9.0, 2.0)])
    calls = _synth(monkeypatch, ws, fail={"乙"})
    first = _dub(sid, ws, lines, VOICE_A)
    assert (first.result["done"], first.result["failed"]) == (2, 1)
    calls.clear()
    _synth(monkeypatch, ws)  # 这回乙合成得出来了
    import app.domain.voices.voices as voices_module

    retried: list[str] = []
    real = voices_module.start_synthesis
    monkeypatch.setattr(voices_module, "start_synthesis", lambda db, *, text, **k: retried.append(text) or real(db, text=text, **k))
    second = _dub(sid, ws, lines, VOICE_A)
    assert retried == ["乙"], "甲和丙已经配好了,只补乙"
    assert (second.result["done"], second.result["skipped"]) == (1, 2)
    assert [start for start, _ in _dub_clips(sid)] == [1.0, 5.0, 9.0]


def test_上一句的尾巴压进这一句时_重配这一句不会删掉上一句(monkeypatch) -> None:
    """配音按起点认是哪一句的:上一句念不完、尾巴盖到这一句的时间窗里,那段仍是上一句的。"""
    client = fresh_client()
    # 甲只有 0.5 秒,2 秒的配音 1.5 倍速也要 1.33 秒 —— 一直念进乙的窗口(0.6 秒开始)。
    ws, sid, [first, second] = _timeline(client, [("甲", 0.0, 0.5), ("乙", 0.6, 2.0)])
    _synth(monkeypatch, ws)
    _dub(sid, ws, [first, second], VOICE_A)
    _dub(sid, ws, [second], VOICE_B)
    assert _dub_clips(sid) == [(0.0, "engine=builtin:volcano|engine_voice=a"), (0.6, "engine=builtin:volcano|engine_voice=b")]


def test_一次配音连同原声处理在撤销栈上只占一步(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, lines = _timeline(client, [("甲", 1.0, 1.0), ("乙", 4.0, 1.0), ("丙", 8.0, 1.0)])
    _synth(monkeypatch, ws)
    with SessionLocal() as db:
        before = db.get(Sequence, sid).revision
    job = _dub(sid, ws, lines, VOICE_A, mode="mute")
    assert job.status == "succeeded", job.error
    with SessionLocal() as db:
        ops = list(db.scalars(select(SequenceOperation).where(SequenceOperation.sequence_id == sid,
                                                               SequenceOperation.revision_after > before)))
        assert [op.kind for op in ops] == ["operation_group"]
        kinds = [step["kind"] for step in ops[0].payload["steps"]]
        assert kinds.count("insert_clip") == 3 and "add_track" in kinds and "set_clip_effect" in kinds

    with SessionLocal() as db:
        undo(db, sid)
        db.commit()
    with SessionLocal() as db:
        sequence = db.get(Sequence, sid)
        assert not [t for t in sequence.tracks if t.role == "dub"], "一次撤销:配音轨连同三段配音都没了"
        footage = next(t for t in sequence.tracks if t.kind == "video").clips[0]
        assert not (footage.effects or {}).get("gain_keyframes"), "原声处理也一起退回去了"
        assert can_undo(db, sid), "再往前是生成字幕那一步,不是配音的残留"
        redo(db, sid)
        db.commit()
    with SessionLocal() as db:
        sequence = db.get(Sequence, sid)
        [dub] = [t for t in sequence.tracks if t.kind == "audio" and len(t.clips) == 3]
        footage = next(t for t in sequence.tracks if t.kind == "video").clips[0]
        assert footage.effects.get("gain_keyframes"), "重做:原声处理也回来了"
