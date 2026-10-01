"""配音念不完时能占用多少空当,按**整条字幕轨**和**原片终点**算;1.5 倍也放不下的,如实报出来。

此前空当只按「这一批选中的」算:剪辑台上只配中间两句时,第二句以为后面全空,原速一路念到没选的第三句上;
最后一句后面「没有下一条」时也原速念完,可能念过片尾。1.5 倍加上空当还放不下的,静默叠在下一句上。
走真的配音任务(_run_dub)、真的时间线操作,合成换成按句给时长的桩。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.i18n import t
from app.db.models import Asset, Clip, Job, Track
from app.domain.jobs import create_job, wait_for_idle_jobs
from app.domain.voices.subtitle_dub import start_subtitle_dub
from tests.util import fresh_client

#: 每句念出来多长(秒)。
SPOKEN = {"甲": 4.0, "乙": 6.0, "丙": 6.0}


@pytest.fixture
def timeline(monkeypatch):
    """10 秒原片;字幕「甲」0–2、「乙」3–5、「丙」8–9.5。"""
    import app.domain.voices.voices as voices_module

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence_id = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        video = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 10.0})
        db.add(video)
        db.commit()
        video_id = video.id
    placed = client.post(f"/api/sequences/{sequence_id}/append", json={"asset_id": video_id})
    assert placed.status_code == 200, placed.text
    tracks = client.post(f"/api/sequences/{sequence_id}/tracks", json={"kind": "subtitle"}).json()["tracks"]
    track_id = next(track["id"] for track in tracks if track["kind"] == "subtitle")
    cues: dict[str, str] = {}
    for text, start, duration in (("甲", 0.0, 2.0), ("乙", 3.0, 2.0), ("丙", 8.0, 1.5)):
        created = client.post(f"/api/sequences/{sequence_id}/text-clips",
                              json={"track_id": track_id, "text": text, "timeline_start": start, "duration": duration}).json()
        clips = next(track["clips"] for track in created["tracks"] if track["id"] == track_id)
        cues[text] = next(clip["id"] for clip in clips if clip["timeline_start"] == start)

    def fake_synthesis(db, *, text, project_id, created_by, **_synthesis):
        audio = Asset(workspace_id=ws, kind="audio", name=text, file_key="media/d.wav", media_info={"duration": SPOKEN[text]})
        db.add(audio)
        db.flush()
        job = create_job(db, workspace_id=ws, kind="tts", payload={}, created_by=None)
        job.status = "succeeded"
        job.result = {"asset_id": audio.id}
        return job

    monkeypatch.setattr(voices_module, "start_synthesis", fake_synthesis)

    def dub(*texts: str) -> Job:
        with SessionLocal() as db:
            job_id = start_subtitle_dub(
                db, sequence_id=sequence_id, clip_ids=[cues[text] for text in texts], match_duration=True, created_by=None,
                synthesis={"engine": "builtin:volcano", "engine_voice": "v", "workspace_id": ws}, original_audio="keep",
            ).id
        assert wait_for_idle_jobs(10)
        with SessionLocal() as db:
            return db.get(Job, job_id)

    def speeds() -> dict[float, float]:
        with SessionLocal() as db:
            track = db.scalar(select(Track).where(Track.sequence_id == sequence_id, Track.role == "dub"))
            return {clip.timeline_start: round(clip.speed, 3) for clip in db.scalars(select(Clip).where(Clip.track_id == track.id))}

    return dub, speeds


def test_只配选中的两句_第二句的空当到没选的第三句为止(timeline) -> None:
    dub, speeds = timeline
    job = dub("甲", "乙")
    assert job.status == "succeeded", job.error
    assert speeds() == {0.0: pytest.approx(4 / 3, abs=1e-3), 3.0: 1.2}, \
        "「乙」6 秒:没选的「丙」8 秒开始,空当 5 秒,1.2 倍念完 —— 不是以为后面全空、原速一路念到「丙」上"
    assert (job.result["overlaps"], job.message_key) == (0, "jobMsg_dubDone")


def test_最后一句按原片终点算_1点5倍还念不完就报出来(timeline) -> None:
    dub, speeds = timeline
    job = dub("丙")
    assert job.status == "succeeded", job.error
    assert speeds() == {8.0: 1.5}, "后面没有字幕了:到原片结束(10 秒)还有 2 秒,6 秒的配音要 3 倍 —— 夹到 1.5 倍,不再原速念过片尾"
    assert (job.result["overlaps"], job.result["overlap_seconds"]) == (1, 2.0), "1.5 倍念 4 秒,出界 2 秒"
    assert job.message_key == "jobMsg_dubDoneOverlap"
    assert "2.0" in t(job.message_key, "zh", **job.message_params)
