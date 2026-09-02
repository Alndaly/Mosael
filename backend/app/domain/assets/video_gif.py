"""Video → GIF as a derived-asset job. The source asset is never mutated."""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import RENDER_SLOTS, create_job, emit_job_event, run_job_guarded, say
from app.media.paths import resolve_key
from app.media.video_gif import encode_video_gif

logger = logging.getLogger(__name__)


class VideoGifError(ValueError):
    pass


def start_video_to_gif(
    db: Session,
    *,
    asset: Asset,
    created_by: str | None,
    fps: int = 12,
    width: int = 720,
    start: float = 0,
    duration: float | None = None,
) -> Job:
    if asset.kind != "video":
        raise VideoGifError("只有视频素材可以转换为 GIF")
    if not asset.file_key:
        raise VideoGifError("视频素材没有本地文件")
    if fps < 1 or fps > 30 or width < 64 or width > 1920 or start < 0 or (duration is not None and duration <= 0):
        raise VideoGifError("GIF 参数超出允许范围")

    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="video_to_gif",
        created_by=created_by,
        payload={
            "asset_id": asset.id,
            "subject": asset.name,
            "fps": fps,
            "width": width,
            "start": start,
            "duration": duration,
        },
        message="jobMsg_videoGifQueued",
    )
    db.commit()
    threading.Thread(
        target=lambda: _run(job.id, asset.id, fps, width, start, duration),
        daemon=True,
    ).start()
    return job


def _run(job_id: str, asset_id: str, fps: int, width: int, start: float, duration: float | None) -> None:
    with RENDER_SLOTS:
        run_job_guarded(
            job_id,
            lambda: _body(job_id, asset_id, fps, width, start, duration),
            what="视频转 GIF",
        )


def _body(job_id: str, asset_id: str, fps: int, width: int, start: float, duration: float | None) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        asset = db.get(Asset, asset_id)
        if job is None or asset is None:
            return
        job.status = "running"
        job.progress = 0.1
        say(job, "jobMsg_videoGifRunning")
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

        source = resolve_key(asset.file_key)
        if not source.is_file():
            raise VideoGifError("视频素材文件不存在")
        with tempfile.TemporaryDirectory(prefix="mosael-gif-") as tmp:
            target = Path(tmp) / f"{source.stem}.gif"
            encode_video_gif(source, target, fps=fps, width=width, start=start, duration=duration)
            made = register_file_asset(
                db,
                workspace_id=asset.workspace_id,
                project_id=asset.project_id,
                source_path=target,
                name=f"{asset.name} · GIF",
                source="generated",
            )
            # 派生关系放在新素材上；原视频不改一字。后续可据此显示“来源”或重新转换。
            made.media_info = {
                **(made.media_info or {}),
                "derived_from_asset_id": asset.id,
                "derivation": "video_to_gif",
                "gif_fps": fps,
                "gif_width": width,
                "gif_start": start,
                "gif_duration": duration,
            }
            db.commit()

        job.status = "succeeded"
        job.progress = 1.0
        job.result = {"asset_id": made.id, "source_asset_id": asset.id}
        say(job, "jobMsg_videoGifDone")
        emit_job_event(db, job.id, "job.succeeded", dict(job.result))
        db.commit()
        logger.info("video %s -> gif asset %s", asset.id, made.id)


__all__ = ["VideoGifError", "start_video_to_gif"]

