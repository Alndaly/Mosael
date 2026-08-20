from __future__ import annotations

import logging
import os
import re
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import SessionLocal
from app.domain.jobs import RENDER_SLOTS, dispatch_job, run_job_guarded, say
from app.db.models import Asset, Font, Job, Lut, Sequence, Track
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job, emit_job_event, finish_job, register_job_child, unregister_job_child
from app.media.paths import resolve_key
from app.media.render_executor import (
    PHASE_ENCODE,
    PHASE_FALLBACK,
    PHASE_FINALIZE,
    PHASE_PREPARE,
    RenderExecutionError,
    RenderProgress,
    execute_render,
)
from app.media.render_plan import RenderPlan, RenderPlanError, build_render_plan
from app.media.scene import assign_base_and_overlays, is_visual_clip


logger = logging.getLogger(__name__)


def _asset_kinds(db: Session, sequence: Sequence) -> dict[str, dict[str, str]]:
    """本序列引用到的素材 → {id: {"kind": ...}},喂给场景契约实现。

    画面层判定要看素材种类(音频素材放在 video 轨上也不该进画面),所以在分配 base/overlay
    之前就得知道 kind——比原来「先分层、后查素材」的顺序提前一步。
    """
    ids = {clip.asset_id for track in sequence.tracks for clip in track.clips if clip.asset_id}
    if not ids:
        return {}
    return {
        asset.id: {"kind": asset.kind}
        for asset in db.scalars(select(Asset).where(Asset.id.in_(ids)))
    }

# 导出参数(对话框可调,全部可省略 → 维持原有行为):
# resolution 是目标短边档位,只降不升;quality 映射 (CRF, x264 preset)。
RESOLUTION_PRESETS = {"1080p": 1080, "720p": 720, "480p": 480}
QUALITY_PRESETS = {"high": (18, "medium"), "standard": (20, "veryfast"), "compact": (26, "veryfast")}


def resolve_export_output(
    width: int, height: int, fps: float, subtitle_style: dict, export_params: dict | None
) -> tuple[int, int, float, dict, int, str]:
    """把导出参数落成输出设置:(width, height, fps, subtitle_style, crf, preset)。"""
    crf, encode_preset = QUALITY_PRESETS["standard"]
    if not export_params:
        return width, height, fps, subtitle_style, crf, encode_preset
    target_short = RESOLUTION_PRESETS.get(str(export_params.get("resolution") or ""))
    short_side = min(width, height)
    if target_short and target_short < short_side:
        # 等比缩放到目标短边(偶数对齐);字幕字号是原生帧像素,必须一起缩,
        # 否则 720p 导出里的字会比预览大出一截。
        ratio = target_short / short_side
        width = max(2, round(width * ratio / 2) * 2)
        height = max(2, round(height * ratio / 2) * 2)
        if subtitle_style.get("font_size"):
            subtitle_style = {**subtitle_style, "font_size": round(float(subtitle_style["font_size"]) * ratio, 1)}
    fps_override = export_params.get("fps")
    if fps_override:
        fps = max(1.0, min(120.0, float(fps_override)))
    quality = QUALITY_PRESETS.get(str(export_params.get("quality") or ""))
    if quality:
        crf, encode_preset = quality
    return width, height, fps, subtitle_style, crf, encode_preset


def build_plan_for_sequence(db: Session, sequence_id: str, export_params: dict | None = None) -> RenderPlan:
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
            # transform(缩放/位置/旋转/透明度 + 关键帧)必须带上,否则导出侧一律回落成恒等变换——
            # 画面变换、关键帧动画、花字定位全部丢失,成片与预览严重不一致。
            "transform": clip.transform,
        }

    video_tracks = sorted(
        (track for track in sequence.tracks if track.kind == "video"), key=lambda track: track.position
    )
    audio_tracks = [track for track in sequence.tracks if track.kind == "audio" and not track.muted]
    subtitle_tracks = [track for track in sequence.tracks if track.kind == "subtitle" and not track.muted]

    def text_clips(track: Track) -> list:
        return [clip for clip in track.clips if not clip.asset_id and clip.text_override]

    # 画面的 base/overlay 归属由 app/media/scene.py 决定——它是**契约实现**,前端
    # sceneModel.ts 是它的对侧,两者由 contracts/scene-cases.json 钉死(见 test_scene_parity.py)。
    # 这里绝不要就地重写这段判定:曾经就是两侧各写一份、各自绿测试、语义却相反。
    kind_by_asset = _asset_kinds(db, sequence)
    track_views = [
        {
            "id": track.id,
            "kind": track.kind,
            "position": track.position,
            "muted": track.muted,
            "clips": [
                {"id": c.id, "asset_id": c.asset_id, "timeline_start": c.timeline_start,
                 "src_in": c.src_in, "src_out": c.src_out, "speed": c.speed}
                for c in track.clips
            ],
        }
        for track in sequence.tracks
    ]
    base_view, overlay_views = assign_base_and_overlays(track_views, kind_by_asset)
    track_by_id = {track.id: track for track in sequence.tracks}
    base_track = track_by_id.get(str(base_view["id"])) if base_view else None
    overlay_tracks = [track_by_id[str(v["id"])] for v in overlay_views]

    def media_clips(track: Track) -> list:
        return [clip for clip in track.clips if is_visual_clip({"asset_id": clip.asset_id}, kind_by_asset)]

    base_clips = [clip_dict(clip) for clip in (media_clips(base_track) if base_track else [])]
    # overlay_views 已是 bottom→top(绘制序),直接展开即可——不要再 reversed 一次。
    # **静音轨的画面保留**:轨道头静音是喇叭图标,只关音频;把画面一并去掉会让「给画中画轨静音」
    # 变成「这层画面从成片里消失」,而预览里它还好好地显示着。音频侧的排除在下面 audible。
    overlay_clips = [clip_dict(clip) for track in overlay_tracks for clip in media_clips(track)]
    # 花字:未静音 video 轨上的文本片段(无 asset、有 text_override),按各自 transform 定位烧录。
    text_overlays = [
        clip_dict(clip) for track in video_tracks if not track.muted for clip in text_clips(track)
    ]
    # 花字若选了上传字体,把 font_id 解析成真实字族名(给 ASS \fn)+ workspace 字体根(fontsdir),
    # 使成片与预览用同一字体;内置字体栈无 font_id、走系统 fontconfig,不受影响。
    for clip in text_overlays:
        style = dict((clip.get("effects") or {}).get("text_style") or {})
        resolved = _resolve_font(db, sequence.workspace_id, str(style.get("font_id") or "").strip())
        if resolved:
            style["font_family"], style["font_dir"] = resolved
            clip["effects"] = {**(clip.get("effects") or {}), "text_style": style}
    # Audio to mix over the base: every audio-track clip PLUS every overlay video-track clip's
    # own audio (so a video on an upper track sounds, not just the base track — matching the
    # preview). Attach each clip's track solo/duck so the plan can mix (solo silences non-soloed
    # tracks; duck lowers a ducked track under overlapping non-ducked audio). The executor probes
    # and skips overlay sources that have no audio stream (silent videos / images).
    # 静音在**音频侧**才生效(画面侧见上)。overlay_tracks 已是 bottom→top,不要再反转。
    audible_overlay_tracks = [track for track in overlay_tracks if not track.muted]
    audio_clips = [
        {**clip_dict(clip), "solo": track.solo, "duck": track.duck}
        for track in audio_tracks
        for clip in track.clips
    ] + [
        {**clip_dict(clip), "solo": track.solo, "duck": track.duck, "optional": True}
        for track in audible_overlay_tracks
        for clip in media_clips(track)
    ]
    subtitle_clips = [clip_dict(clip) for track in subtitle_tracks for clip in track.clips]

    solo_active = any(track.solo for track in sequence.tracks)
    base_video_soloed = bool(base_track and base_track.solo)
    # base 轨自己被静音时也要闭嘴——画面留着,声音去掉,与 overlay 轨同一条规则。
    mute_base_audio = (solo_active and not base_video_soloed) or bool(base_track and base_track.muted)

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
    width, height, fps, subtitle_style, crf, encode_preset = resolve_export_output(
        sequence.width, sequence.height, sequence.fps, _resolve_subtitle_font(db, sequence), export_params
    )
    return build_render_plan(
        sequence_id=sequence.id,
        revision=sequence.revision,
        width=width,
        height=height,
        fps=fps,
        fill_mode=str((sequence.reframe or {}).get("fill_mode", "cover")),
        clips=base_clips,
        assets=assets,
        overlay_clips=overlay_clips,
        audio_clips=audio_clips,
        subtitle_clips=subtitle_clips,
        subtitle_style=subtitle_style,
        text_overlays=text_overlays,
        luts=luts,
        solo_active=solo_active,
        mute_base_audio=mute_base_audio,
        crf=crf,
        encode_preset=encode_preset,
    )


def _resolve_font(db: Session, workspace_id: str, font_id: str) -> tuple[str, str] | None:
    """上传字体 id → (真实字族名, workspace 字体根目录)。字体存在 media/fonts/{ws}/{font_id}/,
    返回根目录 media/fonts/{ws}/——libass 对 fontsdir 递归扫描,一个目录即可覆盖字幕与所有花字
    用到的上传字体。跨工作区或文件缺失则返回 None。"""
    if not font_id:
        return None
    font = db.get(Font, font_id)
    if font is None or font.workspace_id != workspace_id:
        return None
    path = resolve_key(font.file_key)
    if not path.is_file():
        return None
    return font.family, str(path.parent.parent)


def _resolve_subtitle_font(db: Session, sequence: Sequence) -> dict:
    """Turn a subtitle_style referencing an uploaded font into one the renderer can use: the
    preview picks the font by id over HTTP, libass matches a family name inside a directory."""
    style = dict(sequence.subtitle_style or {})
    resolved = _resolve_font(db, sequence.workspace_id, str(style.get("font_id") or "").strip())
    if resolved:
        style["font_family"], style["font_dir"] = resolved
    return style


def start_export(db: Session, sequence_id: str, export_params: dict | None = None, *, created_by: str | None) -> Job:
    """Validate the plan, create the render job, and run FFmpeg off-thread."""
    plan = build_plan_for_sequence(db, sequence_id, export_params)  # raises before job creation
    sequence = db.get(Sequence, sequence_id)
    assert sequence is not None
    job = create_job(
        db,
        workspace_id=sequence.workspace_id,
        kind="render",
        created_by=created_by,
        payload={
            "sequence_id": sequence_id,
            "subject": sequence.name,
            "sequence_revision": plan.sequence_revision,
            "render_plan_hash": plan.render_plan_hash,
            **({"export_params": export_params} if export_params else {}),
        },
        message="Export queued",
    )
    # 「怎么跑」在这里,「由谁跑」是任务总线的决定:render 翻成 external 模式时
    # (OPEN_STUDIO_EXTERNAL_JOB_KINDS=render),任务留在 queued 等外部 worker 认领,本函数不变。
    dispatch_job(db, job, lambda: _run_export(job.id, plan))
    return job


def _run_export(job_id: str, plan: RenderPlan) -> None:
    """Take an admission slot before touching the database — see run_job_guarded."""
    with RENDER_SLOTS:
        run_job_guarded(job_id, lambda: _run_export_body(job_id, plan), what="导出")


def _format_eta(seconds: float) -> str:
    """预计剩余时间的中文速写:'8 秒' / '1 分 20 秒' / '1 时 5 分'。"""
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total} 秒"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} 分 {secs} 秒" if secs else f"{minutes} 分"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 时 {minutes} 分"


def _export_message(phase: str, prog: RenderProgress | None) -> str:
    """按阶段(+编码时的速度/ETA)组织用户可感知的中文进度文案。"""
    if phase == PHASE_PREPARE:
        return "准备导出…"
    if phase == PHASE_FALLBACK:
        return "硬件编码不可用,已转软件编码…"
    if phase == PHASE_FINALIZE:
        return "封装文件…"
    # PHASE_ENCODE
    bits = ["编码中"]
    if prog is not None:
        if prog.speed:
            bits.append(f"{prog.speed:.1f}x")
        if prog.eta_seconds is not None:
            bits.append(f"约剩 {_format_eta(prog.eta_seconds)}")
    return " · ".join(bits) if len(bits) > 1 else "编码中…"


def _run_export_body(job_id: str, plan: RenderPlan) -> None:
    output_path = settings.data_dir / "exports" / f"{job_id}.mp4"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = "running"
        job.message = _export_message(PHASE_PREPARE, None)
        emit_job_event(db, job.id, "job.running", {"render_plan_hash": plan.render_plan_hash})
        db.commit()
        started = time.monotonic()

        phase = PHASE_PREPARE
        last_fraction = -1.0
        last_write = 0.0

        def write_progress(fraction: float | None, message: str) -> None:
            with SessionLocal() as progress_db:
                progress_job = progress_db.get(Job, job_id)
                if progress_job is not None:
                    if fraction is not None:
                        progress_job.progress = round(fraction, 4)
                    progress_job.message = message
                    progress_db.commit()

        def on_phase(name: str) -> None:
            nonlocal phase, last_fraction
            phase = name
            if name == PHASE_FALLBACK:
                # 软件编码从头再来:进度条明确回退到 0 并说明原因,而不是无声归零让人以为卡死。
                last_fraction = -1.0
                with SessionLocal() as fb_db:
                    fb_job = fb_db.get(Job, job_id)
                    if fb_job is not None:
                        fb_job.progress = 0.0
                        fb_job.message = _export_message(name, None)
                        emit_job_event(fb_db, job_id, "job.encode_fallback", {})
                        fb_db.commit()
            elif name == PHASE_FINALIZE:
                # ffmpeg 逐帧进度到不了 100%(末块 out_time ≈ 时长−1帧),封装阶段再顶到 99%,
                # 让进度条贴近满、配合"封装文件…"文案,避免观感上"卡在 96%"。
                write_progress(0.99, _export_message(name, None))
            else:
                write_progress(None, _export_message(name, None))

        def on_progress(prog: RenderProgress) -> None:
            nonlocal last_fraction, last_write
            now = time.monotonic()
            # 至少涨 1.5% 或过去 1 秒才落库:既不每秒多写,又让 ETA/速度保持新鲜。
            if prog.fraction - last_fraction < 0.015 and now - last_write < 1.0:
                return
            last_fraction = prog.fraction
            last_write = now
            write_progress(prog.fraction, _export_message(PHASE_ENCODE, prog))

        try:
            execute_render(
                plan,
                resolve_key,
                output_path,
                on_progress,
                on_child=lambda child: register_job_child(job_id, child),
                on_phase=on_phase,
            )
            # Cancelling kills ffmpeg, which makes it exit non-zero and raise below — but a
            # cancellation landing just as it finished would otherwise be overwritten here, and
            # the export the user stopped would appear in their library as a succeeded job.
            if not finish_job(db, job, status="running"):
                db.commit()
                return
            say(job, "jobMsg_renderFinishing")
            db.commit()
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
                message="jobMsg_renderDone",
                result={"asset_id": asset.id, "output_key": f"exports/{job_id}.mp4"},
            ):
                emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
                size_mb = output_path.stat().st_size / 1_048_576 if output_path.exists() else 0.0
                logger.info(
                    "export job %s finished in %.1fs (%.1f MB) → asset %s",
                    job_id,
                    time.monotonic() - started,
                    size_mb,
                    asset.id,
                )
        except RenderExecutionError as exc:
            # A cancelled render fails because we killed ffmpeg; finish_job keeps the
            # cancellation's own message rather than relabelling it "导出失败".
            if not finish_job(db, job, status="failed", message="jobMsg_renderFailed", error=_friendly_render_error(exc)):
                db.commit()
                unregister_job_child(job_id)
                return
            emit_job_event(db, job.id, "job.failed", {"stderr_tail": exc.stderr_tail, "render_plan_hash": plan.render_plan_hash})
        except Exception as exc:  # defensive: a worker thread must never die silently
            if finish_job(db, job, status="failed", message="jobMsg_renderFailed", error=str(exc)[:500]):
                emit_job_event(db, job.id, "job.failed", {})
        finally:
            # The registry must not outlive the run, or a later cancel would kill a dead
            # process handle — or worse, a recycled one.
            unregister_job_child(job_id)
        db.commit()


def _friendly_render_error(exc: RenderExecutionError) -> str:
    """把 ffmpeg 失败翻成可操作的中文。能从 stderr 认出「某个输入文件打不开」时点名是哪个素材
    —— 最常见就是录制未完整 / 损坏的 webm(无效 EBML / End of file),让用户知道该换哪段,
    而不是只看到无意义的「FFmpeg exited with code 187」。认不出就退回原始错误。"""
    tail = exc.stderr_tail or ""
    match = re.search(r"Error opening input file (.+)", tail)
    if match:
        name = os.path.basename(match.group(1).strip().rstrip(".")) or match.group(1).strip()
        return f"无法读取素材「{name}」——文件可能损坏或未录制完整,请移除或替换该片段后重试。"
    if re.search(r"Invalid data found|invalid as first byte of an EBML|moov atom not found|End of file", tail):
        return "有素材文件损坏或未录制完整,导出中止;请检查时间线上的片段(尤其是录制的 webm)。"
    return f"导出失败:{exc}"


__all__ = ["build_plan_for_sequence", "start_export", "RenderPlanError"]
