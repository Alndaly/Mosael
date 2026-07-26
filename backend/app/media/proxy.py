"""Proxies for the WebCodecs compositor.

On video import we transcode a lightweight 720p H.264 proxy with a fixed short
GOP + faststart. The browser compositor decodes THIS (guaranteed-decodable
avc/mp4, cheap to seek) instead of the original, whose codec/container could be
anything. Best-effort — a failed proxy just means that clip falls back to the
`<video>` element path in the preview.

The same pipeline, minus the height cap and at a near-lossless CRF, produces the
**export proxy**: a full-resolution short-GOP variant the offline export
compositor decodes so a single canvas renderer drives both preview and export
(see docs/superpowers/specs/2026-07-27-preview-export-parity-design.md, 路 C).
Built on demand at export time and cache-reused; it is an intermediate that the
final encode re-compresses, hence the low CRF to keep generational loss negligible.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.jobs import create_job, emit_job_event, run_job_guarded
from app.media.paths import resolve_key

PROXY_NAME = "proxy.mp4"
# Height cap for the proxy. The compositor decodes this, not the original, so a
# 720p ceiling keeps decode cheap while staying crisp on typical preview panes.
PROXY_HEIGHT = 720
# Full-resolution export proxy (路 C): same short-GOP/no-B-frame recipe, native resolution, and a
# near-visually-lossless CRF because the final export pass re-encodes it — the extra generation must
# not show. Sibling to the asset like the preview proxy; larger, but temporary and cache-reused.
EXPORT_PROXY_NAME = "export-proxy.mp4"
EXPORT_PROXY_CRF = 16
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


def export_proxy_path(asset_directory: Path) -> Path:
    return asset_directory / EXPORT_PROXY_NAME


def export_proxy_key_for(asset: Asset) -> str:
    """Storage key of the export proxy sibling to the asset's own file."""
    return str(Path(asset.file_key).parent / EXPORT_PROXY_NAME)


def export_proxy_status(asset: Asset) -> str:
    """ready | failed | none — the full-resolution export proxy's build state."""
    return str((asset.media_info or {}).get("export_proxy_status") or "none")


def _set_proxy_meta(db: Session, asset_id: str, status: str, *, key: str | None = None, prefix: str = "proxy") -> None:
    """Reassign media_info (a plain JSON column) so SQLAlchemy tracks the change.

    `prefix` selects which proxy's flags to write: "proxy" for the preview proxy,
    "export_proxy" for the full-resolution export one — they cache independently.
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        return
    info = dict(asset.media_info or {})
    info[f"{prefix}_status"] = status
    if key is not None:
        info[f"{prefix}_key"] = key
    elif status != "ready":
        info.pop(f"{prefix}_key", None)
    asset.media_info = info
    db.commit()


def build_proxy(source: Path, target: Path, *, max_height: int | None = PROXY_HEIGHT, crf: int = 23) -> bool:
    """Transcode an H.264 short-GOP faststart proxy. Returns success.

    `max_height` caps height (never upscaling) for the preview proxy; pass None to keep native
    resolution (the export proxy), still forcing even dimensions for yuv420p. `crf` trades size
    for quality — 23 for preview, lower for the near-lossless export intermediate.
    """
    # Cap height (even width via -2) for preview; for the export proxy keep native size but round
    # each dimension down to even, which yuv420p requires. Same size in → essentially no resample.
    scale = (
        f"scale=-2:'min({max_height},ih)'"
        if max_height is not None
        else "scale='trunc(iw/2)*2':'trunc(ih/2)*2'"
    )
    args = [
        settings.ffmpeg, "-y", "-v", "error",
        "-i", str(source),
        "-vf", scale,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
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


def build_export_proxy(source: Path, target: Path) -> bool:
    """Full-resolution, near-lossless short-GOP proxy for deterministic offline export compositing."""
    return build_proxy(source, target, max_height=None, crf=EXPORT_PROXY_CRF)


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
            emit_job_event(db, job.id, "job.running", {})
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
                emit_job_event(db, job.id, "job.succeeded", {"proxy_key": key})
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
        emit_job_event(db, job.id, "job.failed", {"reason": reason})
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


def ensure_export_proxy(db: Session, asset: Asset) -> Path | None:
    """Build (once, cached) the full-resolution export proxy for a video asset; return its path.

    Synchronous and idempotent — the export orchestrator calls it before offline rendering, and a
    file already on disk short-circuits (repairing the media_info flag if a restart lost it). Holds
    a transcode slot only for the actual build. Returns None for non-file-backed non-videos or when
    the transcode fails (the caller then falls back to the ffmpeg render_plan path).
    """
    if asset.kind != "video" or not asset.file_key:
        return None
    source = resolve_key(asset.file_key)
    target = export_proxy_path(source.parent)
    if target.is_file():
        if export_proxy_status(asset) != "ready":
            _set_proxy_meta(db, asset.id, "ready", key=export_proxy_key_for(asset), prefix="export_proxy")
        return target
    with _TRANSCODE_SLOTS:
        ok = build_export_proxy(source, target)
    if ok:
        _set_proxy_meta(db, asset.id, "ready", key=export_proxy_key_for(asset), prefix="export_proxy")
        return target
    _set_proxy_meta(db, asset.id, "failed", prefix="export_proxy")
    return None


__all__ = [
    "PROXY_NAME",
    "EXPORT_PROXY_NAME",
    "build_proxy",
    "build_export_proxy",
    "proxy_path",
    "proxy_key_for",
    "proxy_status",
    "export_proxy_path",
    "export_proxy_key_for",
    "export_proxy_status",
    "ensure_export_proxy",
    "start_proxy_job",
    "reconcile_missing_proxies",
]
