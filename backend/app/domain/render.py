from __future__ import annotations

import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job, Lut, Sequence, TaskEvent, Track
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job
from app.media.paths import resolve_key
from app.media.render_executor import RenderExecutionError, execute_render
from app.media.render_plan import RenderPlan, RenderPlanError, build_render_plan


def build_plan_for_sequence(db: Session, sequence_id: str) -> RenderPlan:
    stmt = (
        select(Sequence)
        .where(Sequence.id == sequence_id)
        .options(selectinload(Sequence.tracks).selectinload(Track.clips))
    )
    sequence = db.scalar(stmt)
    if sequence is None:
        raise LookupError("Sequence not found")

    def clip_dict(clip) -> dict:
        return {
            "id": clip.id,
            "asset_id": clip.asset_id,
            "timeline_start": clip.timeline_start,
            "src_in": clip.src_in,
            "src_out": clip.src_out,
            "speed": clip.speed,
            "gain": clip.gain,
            "muted": clip.muted,
            "effects": clip.effects,
            "text_override": clip.text_override,
        }

    video_tracks = sorted(
        (track for track in sequence.tracks if track.kind == "video"), key=lambda track: track.position
    )
    audio_tracks = [track for track in sequence.tracks if track.kind == "audio" and not track.muted]
    subtitle_tracks = [track for track in sequence.tracks if track.kind == "subtitle" and not track.muted]
    base_clips = [clip_dict(clip) for clip in (video_tracks[0].clips if video_tracks else [])]
    overlay_clips = [clip_dict(clip) for track in video_tracks[1:] if not track.muted for clip in track.clips]
    audio_clips = [clip_dict(clip) for track in audio_tracks for clip in track.clips]
    subtitle_clips = [clip_dict(clip) for track in subtitle_tracks for clip in track.clips]

    asset_ids = {clip["asset_id"] for clip in base_clips + overlay_clips + audio_clips if clip["asset_id"]}
    assets = {
        asset.id: {"file_key": asset.file_key}
        for asset in db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))
    }
    lut_ids = {
        str((clip.get("effects") or {}).get("color", {}).get("lut") or "")
        for clip in base_clips + overlay_clips
    }
    lut_ids.discard("")
    luts = {
        lut.id: lut.file_key
        for lut in (db.scalars(select(Lut).where(Lut.id.in_(lut_ids))) if lut_ids else [])
    }
    return build_render_plan(
        sequence_id=sequence.id,
        revision=sequence.revision,
        width=sequence.width,
        height=sequence.height,
        fps=sequence.fps,
        fill_mode=str((sequence.reframe or {}).get("fill_mode", "cover")),
        clips=base_clips,
        assets=assets,
        overlay_clips=overlay_clips,
        audio_clips=audio_clips,
        subtitle_clips=subtitle_clips,
        luts=luts,
    )


def start_export(db: Session, sequence_id: str) -> Job:
    """Validate the plan, create the render job, and run FFmpeg off-thread."""
    plan = build_plan_for_sequence(db, sequence_id)  # raises before job creation
    sequence = db.get(Sequence, sequence_id)
    assert sequence is not None
    job = create_job(
        db,
        workspace_id=sequence.workspace_id,
        kind="render",
        payload={
            "sequence_id": sequence_id,
            "sequence_revision": plan.sequence_revision,
            "render_plan_hash": plan.render_plan_hash,
        },
        message="Export queued",
    )
    db.commit()
    thread = threading.Thread(target=_run_export, args=(job.id, plan), daemon=True)
    thread.start()
    return job


def _run_export(job_id: str, plan: RenderPlan) -> None:
    output_path = settings.data_dir / "exports" / f"{job_id}.mp4"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = "Rendering"
        db.add(TaskEvent(job_id=job.id, type="job.running", payload={"render_plan_hash": plan.render_plan_hash}))
        db.commit()

        last_progress = -1.0

        def on_progress(value: float) -> None:
            nonlocal last_progress
            if value - last_progress < 0.02:
                return
            last_progress = value
            with SessionLocal() as progress_db:
                progress_job = progress_db.get(Job, job_id)
                if progress_job is not None:
                    progress_job.progress = round(value, 4)
                    progress_db.commit()

        try:
            execute_render(plan, resolve_key, output_path, on_progress)
            sequence = db.get(Sequence, plan.sequence_id)
            asset = register_file_asset(
                db,
                workspace_id=job.workspace_id,
                project_id=sequence.project_id if sequence else None,
                source_path=output_path,
                name=f"{sequence.name if sequence else 'Sequence'} · Export r{plan.sequence_revision}",
            )
            job.status = "succeeded"
            job.progress = 1.0
            job.message = "Export complete"
            job.result = {"asset_id": asset.id, "output_key": f"exports/{job_id}.mp4"}
            db.add(TaskEvent(job_id=job.id, type="job.succeeded", payload={"asset_id": asset.id}))
        except RenderExecutionError as exc:
            job.status = "failed"
            job.message = "Export failed"
            job.error = str(exc)
            db.add(
                TaskEvent(
                    job_id=job.id,
                    type="job.failed",
                    payload={"stderr_tail": exc.stderr_tail, "render_plan_hash": plan.render_plan_hash},
                )
            )
        except Exception as exc:  # defensive: a worker thread must never die silently
            job.status = "failed"
            job.message = "Export failed"
            job.error = str(exc)[:500]
            db.add(TaskEvent(job_id=job.id, type="job.failed", payload={}))
        db.commit()


__all__ = ["build_plan_for_sequence", "start_export", "RenderPlanError"]
