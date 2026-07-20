"""Preview proxies for the WebCodecs compositor.

On video import we transcode a lightweight 720p H.264 proxy with a fixed short
GOP + faststart. The browser compositor decodes THIS (guaranteed-decodable
avc/mp4, cheap to seek) instead of the original, whose codec/container could be
anything; export still uses the original. Best-effort — a failed proxy just
means that clip falls back to the `<video>` element path in the preview.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job, TaskEvent
from app.domain.jobs import run_job_guarded, create_job
from app.media.paths import resolve_key

PROXY_NAME = "proxy.mp4"
# Height cap for the proxy. The compositor decodes this, not the original, so a
# 720p ceiling keeps decode cheap while staying crisp on typical preview panes.
PROXY_HEIGHT = 720
# Bound concurrent ffmpeg transcodes (a startup backfill can queue one job per video at once).
_TRANSCODE_SLOTS = threading.Semaphore(2)


def proxy_path(asset_directory: Path) -> Path:
    return asset_directory / PROXY_NAME


def proxy_key_for(asset: Asset) -> str:
    """Storage key of the proxy sibling to the asset's own file."""
    return str(Path(asset.file_key).parent / PROXY_NAME)


def proxy_status(asset: Asset) -> str:
    """pending | ready | failed | none (not a video, or proxies disabled)."""
    return str((asset.media_info or {}).get("proxy_status") or "none")


def _set_proxy_meta(db: Session, asset_id: str, status: str, *, key: str | None = None) -> None:
    """Reassign media_info (a plain JSON column) so SQLAlchemy tracks the change."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        return
    info = dict(asset.media_info or {})
    info["proxy_status"] = status
    if key is not None:
        info["proxy_key"] = key
    elif status != "ready":
        info.pop("proxy_key", None)
    asset.media_info = info
    db.commit()


def build_proxy(source: Path, target: Path) -> bool:
    """Transcode a 720p H.264 short-GOP faststart proxy. Returns success."""
    args = [
        settings.ffmpeg, "-y", "-v", "error",
        "-i", str(source),
        # Cap height at 720 (never upscale), keep aspect, force even dimensions.
        "-vf", f"scale=-2:'min({PROXY_HEIGHT},ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        # Fixed 30-frame GOP (a keyframe every 30 frames, no scene-cut keyframes)
        # → the compositor can seek to a nearby sync sample cheaply.
        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
        # No B-frames: decode order == presentation order (cts == dts), so the
        # WebCodecs compositor never has to reorder frames — seeking is trivial.
        "-bf", "0",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        str(target),
    ]
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=600)
    except Exception:
        target.unlink(missing_ok=True)
        return False
    return target.is_file()


def start_proxy_job(db: Session, asset: Asset, *, force: bool = False) -> Job | None:
    """Queue proxy generation for a video asset (in-process daemon thread).

    No-op (returns None) when proxies are disabled, the asset isn't a file-backed
    video, or a proxy is already ready/in-flight (unless `force`).
    """
    if not settings.generate_proxies or asset.kind != "video" or not asset.file_key:
        return None
    if not force and proxy_status(asset) in ("ready", "pending"):
        return None
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="proxy",
        payload={"asset_id": asset.id},
        message="生成预览代理排队中",
    )
    info = dict(asset.media_info or {})
    info["proxy_status"] = "pending"
    info.pop("proxy_key", None)
    asset.media_info = info
    db.commit()
    threading.Thread(target=_run_proxy, args=(job.id, asset.id), daemon=True).start()
    return job


def _run_proxy(job_id: str, asset_id: str) -> None:
    """Wait for a transcode slot BEFORE opening a database session.

    The slot used to be taken inside the session, so every queued worker sat in the semaphore
    while holding a pooled connection. The pool is 5 + 10 overflow with a 30s checkout timeout,
    so a startup backfill of 60 videos put 45 threads into that timeout — each dying with its
    job still `queued` and nothing to reconcile it. Queueing on the semaphore costs a sleeping
    thread; queueing on the connection pool costs the job.
    """
    with _TRANSCODE_SLOTS:
        run_job_guarded(job_id, lambda: _proxy_body(job_id, asset_id), what="代理生成")


def _proxy_body(job_id: str, asset_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            job.status = "running"
            job.message = "生成预览代理中"
            job.progress = 0.1
            db.add(TaskEvent(job_id=job.id, type="job.running", payload={}))
            db.commit()

            asset = db.get(Asset, asset_id)
            if asset is None or not asset.file_key:
                _fail(db, job_id, asset_id, "素材文件缺失")
                return
            source = resolve_key(asset.file_key)
            target = proxy_path(source.parent)
            ok = build_proxy(source, target)  # slot already held by _run_proxy
            if ok:
                key = proxy_key_for(asset)
                _set_proxy_meta(db, asset_id, "ready", key=key)
                job = db.get(Job, job_id)
                job.status = "succeeded"
                job.progress = 1.0
                job.message = "预览代理完成"
                job.result = {"proxy_key": key}
                db.add(TaskEvent(job_id=job.id, type="job.succeeded", payload={"proxy_key": key}))
                db.commit()
            else:
                _fail(db, job_id, asset_id, "ffmpeg 代理转码失败")
        except Exception as exc:  # a worker thread must record failure, never die silently
            db.rollback()
            _fail(db, job_id, asset_id, str(exc)[:500])


def _fail(db: Session, job_id: str, asset_id: str, reason: str) -> None:
    _set_proxy_meta(db, asset_id, "failed")
    job = db.get(Job, job_id)
    if job is not None:
        job.status = "failed"
        job.message = "预览代理生成失败"
        job.error = reason
        db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"reason": reason}))
        db.commit()


def reconcile_missing_proxies(db: Session) -> int:
    """Startup: (re)queue proxies for video assets without a ready one on disk.

    A backend restart orphans the daemon thread, leaving media_info stuck at
    "pending"; here we re-drive anything whose proxy file is actually missing,
    and repair the status of proxies that exist on disk but lost their flag.
    """
    if not settings.generate_proxies:
        return 0
    queued = 0
    for asset in db.scalars(select(Asset).where(Asset.kind == "video")):
        if not asset.file_key:
            continue
        directory = resolve_key(asset.file_key).parent
        if proxy_path(directory).is_file():
            if proxy_status(asset) != "ready":
                _set_proxy_meta(db, asset.id, "ready", key=proxy_key_for(asset))
            continue
        if start_proxy_job(db, asset, force=True):
            queued += 1
    return queued


__all__ = [
    "PROXY_NAME",
    "build_proxy",
    "proxy_path",
    "proxy_key_for",
    "proxy_status",
    "start_proxy_job",
    "reconcile_missing_proxies",
]
