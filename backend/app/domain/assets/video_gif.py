"""Video → GIF as a derived-asset job. The source asset is never mutated."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.i18n import LocalizedError
from app.db.models import Asset, Job
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import RENDER_SLOTS, create_job, dispatch_job, emit_job_event, finish_job, run_job_guarded, say
from app.media.paths import resolve_key
from app.media.video_gif import encode_video_gif

logger = logging.getLogger(__name__)


class VideoGifError(LocalizedError, ValueError):
    """视频转 GIF 被拒。带文案 key(`gifErr_*`),按请求方的语言翻。"""


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
        raise VideoGifError("gifErr_notVideo")
    if not asset.file_key:
        raise VideoGifError("gifErr_noLocalFile")
    if fps < 1 or fps > 30 or width < 64 or width > 1920 or start < 0 or (duration is not None and duration <= 0):
        raise VideoGifError("gifErr_badParams")

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
    # 经总线派发。此前这里是一句裸的线程创建 —— 线程没有 JOB_THREAD_NAME,
    # `wait_for_idle_jobs()` 按名字找不到它(测试里 fresh_client() 就会在它还活着时
    # drop_all),而且这个 kind 的执行模式形同虚设:注册成 external 也照样在进程内跑。
    dispatch_job(db, job, lambda: _run(job.id, asset.id, fps, width, start, duration))
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
        # 状态经 finish_job 写:排队时就被取消的不被写回 running,编码完时不盖掉中途的取消
        # (工作流取消会级联到这里,而手里这份 Job 是开始时读的)。
        if not finish_job(db, job, status="running", progress=0.1):
            db.commit()
            return
        say(job, "jobMsg_videoGifRunning")
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

        source = resolve_key(asset.file_key)
        if not source.is_file():
            raise VideoGifError("gifErr_fileMissing")
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

        result = {"asset_id": made.id, "source_asset_id": asset.id}
        if finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_videoGifDone")
            emit_job_event(db, job.id, "job.succeeded", dict(result))
        db.commit()
        logger.info("video %s -> gif asset %s", asset.id, made.id)


__all__ = ["VideoGifError", "start_video_to_gif"]

