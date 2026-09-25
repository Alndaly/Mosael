"""插入片段之后,调用方拿到的是**它刚插的那一段**,不是猜出来的一段。

insert_clip 此前返回整条时间线,于是它的两个调用方各自去猜「刚插进去的是哪一段」:

· 「接到时间线」节点取**整条序列里 created_at 最新**的片段。并行的两条分支同时往一条时间线上
  接素材(视频轨一条、配音轨一条,这是编排最常见的形状)时,拿到的是另一条分支刚插的那段 ——
  输出的 clip_id 是别人的,`max_duration` 的变速也加到了别人头上;
· 字幕配音按**落点**在配音轨上找。重配同一条字幕时,配音轨上那一秒已经有上一次的配音,
  变速加到了旧的那段上,新配的这段原速播放、盖过下一句。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Sequence, Track, Workflow
from app.domain.sequences import operations
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _sequence():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    return client, ws, sequence["id"]


def _asset(ws: str, kind: str, seconds: float) -> str:
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind=kind, name=kind, file_key=f"media/{kind}.bin", media_info={"duration": seconds})
        db.add(asset)
        db.commit()
        return asset.id


def test_并行分支同时往时间线上接_各自拿到自己那一段(monkeypatch) -> None:
    _, ws, sequence_id = _sequence()
    video = _asset(ws, "video", 10.0)
    voice = _asset(ws, "audio", 8.0)
    with SessionLocal() as db:
        tracks = {track.kind: track.id for track in db.get(Sequence, sequence_id).tracks}

    real_insert = operations.insert_clip

    def insert_then_a_sibling_lands(db, seq_id, op):
        """这一段刚落库,另一条分支(接配音)紧跟着也落了一段 —— 引擎里两条分支本来就并行。"""
        made = real_insert(db, seq_id, op)
        with SessionLocal() as other:
            real_insert(other, seq_id, operations.InsertClip(
                track_id=tracks["audio"], asset_id=voice, timeline_start=0.0, src_in=0.0, src_out=8.0,
            ))
        return made

    monkeypatch.setattr(operations, "insert_clip", insert_then_a_sibling_lands)
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        out = get_executor("timeline_append")(db, workflow, {
            "sequence_id": sequence_id, "asset_id": video, "max_duration": 8,
        })
    with SessionLocal() as db:
        clip = db.get(Clip, out["clip_id"])
        assert (clip.track_id, clip.asset_id) == (tracks["video"], video), "输出的是另一条分支插的那段"
        assert clip.speed == 1.25, "max_duration 的变速没加到自己这段上"
        sibling = db.scalar(select(Clip).where(Clip.asset_id == voice))
        assert (sibling.speed or 1.0) == 1.0, "变速加到了别的分支那段上"


def test_重配同一条字幕_变速加在新配的这段上(monkeypatch) -> None:
    import app.domain.voices.voices as voices_module
    from app.domain.jobs import create_job, wait_for_idle_jobs
    from app.domain.voices.subtitle_dub import start_subtitle_dub

    client, ws, sequence_id = _sequence()
    tracks = client.post(f"/api/sequences/{sequence_id}/tracks", json={"kind": "subtitle"}).json()["tracks"]
    subtitle_track = next(track["id"] for track in tracks if track["kind"] == "subtitle")
    created = client.post(
        f"/api/sequences/{sequence_id}/text-clips",
        json={"track_id": subtitle_track, "text": "你好", "timeline_start": 1.0, "duration": 3.0},
    ).json()
    cue_id = next(track["clips"] for track in created["tracks"] if track["id"] == subtitle_track)[0]["id"]

    def fake_synthesis(db, *, text, project_id, created_by, **synthesis):
        audio = Asset(workspace_id=ws, kind="audio", name=text, file_key="media/d.wav", media_info={"duration": 6.0})
        db.add(audio)
        db.flush()
        job = create_job(db, workspace_id=ws, kind="tts", payload={}, created_by=None)
        job.status = "succeeded"
        job.result = {"asset_id": audio.id}
        return job

    monkeypatch.setattr(voices_module, "start_synthesis", fake_synthesis)
    for _ in range(2):
        with SessionLocal() as db:
            start_subtitle_dub(
                db, sequence_id=sequence_id, clip_ids=[cue_id], match_duration=True, created_by=None,
                synthesis={"engine": "volcano", "engine_voice": "v", "workspace_id": ws}, original_audio="keep",
            )
        assert wait_for_idle_jobs(10)

    with SessionLocal() as db:
        dub = db.scalar(select(Track).where(Track.sequence_id == sequence_id, Track.role == "dub"))
        speeds = sorted((clip.created_at, clip.speed or 1.0) for clip in dub.clips)
        # 6 秒的配音塞进 3 秒的字幕 → 2 倍速。两次配出来的两段都该是 2 倍速。
        assert [speed for _, speed in speeds] == [2.0, 2.0], speeds
