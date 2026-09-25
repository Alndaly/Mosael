"""取消字幕配音(或取消它所在的工作流),剩下的句子就不再合成。

取消会级联到**正在合成的那一句**(见 test_job_parent 的逐句合成用例),但配音任务自己的循环
不看自己的状态:那一句失败了记一笔 `failed += 1`,接着合成下一句 —— 每一句都是一次付费的
TTS 调用,产出照样一段段落到时间线上。最后还把自己写成「完成」,盖掉了用户的取消。

能挡住它的一处是任务总线:执行体里派生的子任务(derived)在父任务已经收尾**成功**时照样挂上
(导出收尾时登记产物),但父任务被取消、失败之后就不该再起新活。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, Job, Track
from app.domain.jobs import cancel_job, create_job, wait_for_idle_jobs
from tests.util import fresh_client


def _sequence_with_cues(count: int) -> tuple[str, str, list[str]]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence_id = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}
    ).json()["id"]
    tracks = client.post(f"/api/sequences/{sequence_id}/tracks", json={"kind": "subtitle"}).json()["tracks"]
    track_id = next(track["id"] for track in tracks if track["kind"] == "subtitle")
    cue_ids: list[str] = []
    for index in range(count):
        created = client.post(
            f"/api/sequences/{sequence_id}/text-clips",
            json={"track_id": track_id, "text": f"第{index}句", "timeline_start": index * 4.0, "duration": 3.0},
        ).json()
        clips = next(track["clips"] for track in created["tracks"] if track["id"] == track_id)
        cue_ids = [clip["id"] for clip in clips]
    return ws, sequence_id, cue_ids


def test_取消之后剩下的句子不再合成_任务也不会被写回完成(monkeypatch) -> None:
    import app.domain.voices.voices as voices_module
    from app.domain.voices.subtitle_dub import start_subtitle_dub

    ws, sequence_id, cue_ids = _sequence_with_cues(3)
    synthesized: list[str] = []
    dub: dict[str, str] = {}

    def fake_synthesis(db, *, text, project_id, created_by, **synthesis):
        synthesized.append(text)
        if len(synthesized) == 1:
            # 第一句合成期间,用户取消了(或者取消了外面那条工作流,级联下来)。
            with SessionLocal() as other:
                cancel_job(other, other.get(Job, dub["id"]))
        audio = Asset(workspace_id=ws, kind="audio", name=text, file_key="media/d.wav", media_info={"duration": 2.0})
        db.add(audio)
        db.flush()
        job = create_job(db, workspace_id=ws, kind="tts", payload={}, created_by=None)
        job.status = "succeeded"
        job.result = {"asset_id": audio.id}
        return job

    monkeypatch.setattr(voices_module, "start_synthesis", fake_synthesis)
    with SessionLocal() as db:
        dub["id"] = start_subtitle_dub(
            db, sequence_id=sequence_id, clip_ids=cue_ids, match_duration=False, created_by=None,
            synthesis={"engine": "volcano", "engine_voice": "v", "workspace_id": ws}, original_audio="keep",
        ).id
    assert wait_for_idle_jobs(10)

    assert len(synthesized) == 1, f"取消之后又合成了 {len(synthesized) - 1} 句"
    with SessionLocal() as db:
        job = db.get(Job, dub["id"])
        assert job.status == "failed" and job.error_key == "jobErr_cancelled", (job.status, job.error_key)
        dub_track = db.scalar(select(Track).where(Track.sequence_id == sequence_id, Track.role == "dub"))
        assert dub_track is None or not dub_track.clips, "取消之后还往时间线上落了配音"
