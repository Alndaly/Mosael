from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import SessionLocal
from app.domain.jobs import RENDER_SLOTS, dispatch_job, run_job_guarded
from app.db.models import Asset, Font, Job, Lut, Sequence, Track
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job, emit_job_event, finish_job, register_job_child, unregister_job_child
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
    # PR/DaVinci z-order: the topmost timeline video track renders on top. The base (full-frame
    # bottom layer) is the BOTTOM-MOST video track that actually has clips — empty tracks below
    # it contribute nothing, and treating an empty bottom track as the base would drop the whole
    # render ("no clips to render"). Tracks above the base composite as overlays (top row last).
    video_tracks_with_clips = [track for track in video_tracks if track.clips]
    base_track = video_tracks_with_clips[-1] if video_tracks_with_clips else None
    base_clips = [clip_dict(clip) for clip in (base_track.clips if base_track else [])]
    overlay_tracks = [track for track in video_tracks_with_clips[:-1] if not track.muted]
    overlay_clips = [clip_dict(clip) for track in reversed(overlay_tracks) for clip in track.clips]
    # Audio to mix over the base: every audio-track clip PLUS every overlay video-track clip's
    # own audio (so a video on an upper track sounds, not just the base track — matching the
    # preview). Attach each clip's track solo/duck so the plan can mix (solo silences non-soloed
    # tracks; duck lowers a ducked track under overlapping non-ducked audio). The executor probes
    # and skips overlay sources that have no audio stream (silent videos / images).
    audio_clips = [
        {**clip_dict(clip), "solo": track.solo, "duck": track.duck}
        for track in audio_tracks
        for clip in track.clips
    ] + [
        {**clip_dict(clip), "solo": track.solo, "duck": track.duck, "optional": True}
        for track in reversed(overlay_tracks)
        for clip in track.clips
    ]
    subtitle_clips = [clip_dict(clip) for track in subtitle_tracks for clip in track.clips]

    solo_active = any(track.solo for track in sequence.tracks)
    base_video_soloed = bool(base_track and base_track.solo)
    mute_base_audio = solo_active and not base_video_soloed

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
        subtitle_style=_resolve_subtitle_font(db, sequence),
        luts=luts,
        solo_active=solo_active,
        mute_base_audio=mute_base_audio,
    )


def _resolve_subtitle_font(db: Session, sequence: Sequence) -> dict:
    """Turn a subtitle_style referencing an uploaded font into one the renderer can use.

    The preview picks the font by id and loads it over HTTP; libass instead matches a family
    name inside a directory. Resolve the id here — where we still have a session — into the
    font's real family plus its directory, so the burn-in uses the same file you previewed.
    A font from another workspace is ignored rather than honoured."""
    style = dict(sequence.subtitle_style or {})
    font_id = str(style.get("font_id") or "").strip()
    if not font_id:
        return style
    font = db.get(Font, font_id)
    if font is None or font.workspace_id != sequence.workspace_id:
        return style
    path = resolve_key(font.file_key)
    if not path.is_file():
        return style
    style["font_family"] = font.family
    style["font_dir"] = str(path.parent)
    return style


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
    # 「怎么跑」在这里,「由谁跑」是任务总线的决定:render 翻成 external 模式时
    # (MIBU_EXTERNAL_JOB_KINDS=render),任务留在 queued 等外部 worker 认领,本函数不变。
    dispatch_job(db, job, lambda: _run_export(job.id, plan))
    return job


def _run_export(job_id: str, plan: RenderPlan) -> None:
    """Take an admission slot before touching the database — see run_job_guarded."""
    with RENDER_SLOTS:
        run_job_guarded(job_id, lambda: _run_export_body(job_id, plan), what="导出")


def _run_export_body(job_id: str, plan: RenderPlan) -> None:
    output_path = settings.data_dir / "exports" / f"{job_id}.mp4"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = "Rendering"
        emit_job_event(db, job.id, "job.running", {"render_plan_hash": plan.render_plan_hash})
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
            execute_render(
                plan,
                resolve_key,
                output_path,
                on_progress,
                on_child=lambda child: register_job_child(job_id, child),
            )
            # Cancelling kills ffmpeg, which makes it exit non-zero and raise below — but a
            # cancellation landing just as it finished would otherwise be overwritten here, and
            # the export the user stopped would appear in their library as a succeeded job.
            if not finish_job(db, job, status="running"):
                db.commit()
                return
            sequence = db.get(Sequence, plan.sequence_id)
            asset = register_file_asset(
                db,
                workspace_id=job.workspace_id,
                project_id=sequence.project_id if sequence else None,
                source_path=output_path,
                name=f"{sequence.name if sequence else 'Sequence'} · Export r{plan.sequence_revision}",
            )
            if finish_job(
                db,
                job,
                status="succeeded",
                progress=1.0,
                message="Export complete",
                result={"asset_id": asset.id, "output_key": f"exports/{job_id}.mp4"},
            ):
                emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
        except RenderExecutionError as exc:
            # A cancelled render fails because we killed ffmpeg; finish_job keeps the
            # cancellation's own message rather than relabelling it "Export failed".
            if not finish_job(db, job, status="failed", message="Export failed", error=str(exc)):
                db.commit()
                unregister_job_child(job_id)
                return
            emit_job_event(db, job.id, "job.failed", {"stderr_tail": exc.stderr_tail, "render_plan_hash": plan.render_plan_hash})
        except Exception as exc:  # defensive: a worker thread must never die silently
            if finish_job(db, job, status="failed", message="Export failed", error=str(exc)[:500]):
                emit_job_event(db, job.id, "job.failed", {})
        finally:
            # The registry must not outlive the run, or a later cancel would kill a dead
            # process handle — or worse, a recycled one.
            unregister_job_child(job_id)
        db.commit()


__all__ = ["build_plan_for_sequence", "start_export", "RenderPlanError"]
