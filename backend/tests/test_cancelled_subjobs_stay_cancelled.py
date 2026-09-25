"""工作流节点等的子任务(转写、转 GIF)被取消之后,跑完也还是「已取消」。

取消工作流会级联到它派生的子任务(jobs.cancel_job)。执行体停不下来的那一段(模型推理、
ffmpeg 编码)跑完之后,此前直接 `job.status = "succeeded"` —— 手里那份 Job 是开始时读的,
取消是别的会话写进来的,于是取消被盖掉:任务中心里取消过的活又成了成功的。导出早就改成
经 finish_job 写(test_job_cancellation),这两条漏了。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.jobs import cancel_job
from tests.util import fresh_client


@pytest.fixture
def media(tmp_path, monkeypatch) -> tuple[str, str, Path]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake")
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/clip.mp4")
        db.add(asset)
        db.commit()
        return ws, asset.id, source


def _job(ws: str, kind: str) -> str:
    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind=kind, status="queued", payload={})
        db.add(job)
        db.commit()
        return job.id


def _cancel(job_id: str) -> None:
    with SessionLocal() as other:
        cancel_job(other, other.get(Job, job_id))


def _assert_still_cancelled(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert (job.status, job.error_key) == ("failed", "jobErr_cancelled"), (job.status, job.error_key)


def test_转_GIF_编码途中被取消(media, monkeypatch) -> None:
    from app.domain.assets import video_gif

    ws, asset_id, source = media
    job_id = _job(ws, "video_to_gif")

    def encode(src, target, **kwargs):
        _cancel(job_id)
        Path(target).write_bytes(b"GIF89a")

    monkeypatch.setattr(video_gif, "resolve_key", lambda key: source)
    monkeypatch.setattr(video_gif, "encode_video_gif", encode)
    video_gif._body(job_id, asset_id, 12, 480, 0.0, None)
    _assert_still_cancelled(job_id)


def test_转写途中被取消(media, monkeypatch) -> None:
    from app.domain.voices import transcription

    ws, asset_id, source = media
    job_id = _job(ws, "transcribe")

    def transcribe(wav, python, engine, language):
        _cancel(job_id)
        return {"language": "zh", "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}]}

    monkeypatch.setattr(transcription, "resolve_key", lambda key: source)
    monkeypatch.setattr(transcription, "resolve_transcription_runtime", lambda language, engine="": ("python", "fake"))
    monkeypatch.setattr(transcription, "_extract_audio", lambda src, target: target.write_bytes(b"RIFF"))
    monkeypatch.setattr(transcription, "_mirror_model_download_progress", lambda job, engine: threading.Event())
    monkeypatch.setattr(transcription, "transcribe_with_engine", transcribe)
    transcription._run_transcription_body(job_id, asset_id)
    _assert_still_cancelled(job_id)
