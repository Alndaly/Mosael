from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.unit_of_work import unit_of_work
from app.core.i18n import tr
from app.domain.jobs import RENDER_SLOTS, dispatch_job, run_job_guarded, say
from app.db.models import Asset, Font, Job, Lut, Sequence, Track
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import EXPORT, FRAME, derived
from app.domain.export_presets import QUALITY_PRESETS, RESOLUTION_PRESETS
from app.domain.jobs import create_job, emit_job_event, finish_job, register_job_child, unregister_job_child
from app.media.paths import resolve_key
from app.media.render_executor import (
    PHASE_ENCODE,
    PHASE_FALLBACK,
    PHASE_FINALIZE,
    PHASE_PREPARE,
    RenderExecutionError,
    RenderProgress,
    ensure_text_can_burn,
    execute_render,
)
from app.media.render_plan import RenderPlan, RenderPlanError, build_render_plan
from app.media.scene import assign_base_and_overlays, is_visual_clip, text_layers


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

# 导出参数(对话框可调,全部可省略 → 维持原有行为)的几档见 export_presets。


def resolve_export_output(
    width: int, height: int, fps: float, export_params: dict | None
) -> tuple[int, int, float, float, int, str]:
    """把导出参数落成输出设置:(width, height, fps, pixel_scale, crf, preset)。

    pixel_scale 是输出 ÷ 序列的比例:字幕 / 花字字号、描边、阴影这些以序列像素记的量都要乘它,
    交给 build_render_plan 一处做(此前只在这里改了字幕字号)。"""
    crf, encode_preset = QUALITY_PRESETS["standard"]
    pixel_scale = 1.0
    if not export_params:
        return width, height, fps, pixel_scale, crf, encode_preset
    target_short = RESOLUTION_PRESETS.get(str(export_params.get("resolution") or ""))
    short_side = min(width, height)
    if target_short and target_short < short_side:
        # 等比缩放到目标短边(偶数对齐)。
        pixel_scale = target_short / short_side
        width = max(2, round(width * pixel_scale / 2) * 2)
        height = max(2, round(height * pixel_scale / 2) * 2)
    fps_override = export_params.get("fps")
    if fps_override:
        fps = max(1.0, min(120.0, float(fps_override)))
    quality = QUALITY_PRESETS.get(str(export_params.get("quality") or ""))
    if quality:
        crf, encode_preset = quality
    return width, height, fps, pixel_scale, crf, encode_preset


def build_plan_for_sequence(db: Session, sequence_id: str, export_params: dict | None = None) -> RenderPlan:
    stmt = (
        select(Sequence)
        .where(Sequence.id == sequence_id)
        .options(selectinload(Sequence.tracks).selectinload(Track.clips))
    )
    sequence = db.scalar(stmt)
    if sequence is None:
        raise LookupError("Sequence not found")

    # **脱机片段挡在导出之前。** 素材被删掉之后,引用它的片段既不是画面片段(查不到 kind)
    # 也不是文字片段(没有 text_override),下面每一条筛选都会把它漏掉 —— 于是导出静默地
    # 少一段,成片短了一截而没有任何提示,等发出去才发现。时间线上它是看得见的红色占位,
    # 导出时也必须看得见。
    offline = [clip for track in sequence.tracks for clip in track.clips if clip.offline]
    if offline:
        names = sorted({str((clip.offline_asset or {}).get("name") or "?") for clip in offline})
        raise RenderPlanError(
            f"有 {len(offline)} 个片段的素材已被删除({'、'.join(names[:3])}"
            f"{' 等' if len(names) > 3 else ''}):请先把这些片段从时间线上删掉,或换上别的素材。"
        )

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

    audio_tracks = [track for track in sequence.tracks if track.kind == "audio" and not track.muted]

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
            "hidden": track.hidden,
            "clips": [
                {"id": c.id, "asset_id": c.asset_id, "timeline_start": c.timeline_start,
                 "src_in": c.src_in, "src_out": c.src_out, "speed": c.speed, "text_override": c.text_override}
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

    def carries_sound(clip) -> bool:
        """视频素材带声音,图片不带。和预览(playback/audioMix)用同一条判据 —— 这里不探文件:
        无声视频两边都当有声处理,好过两边各猜各的。"""
        return (kind_by_asset.get(str(clip.asset_id)) or {}).get("kind") == "video"

    # has_audio:基底轨的这一段算不算「别的声音」—— 闪避轨要给它让路(见 build_render_plan)。
    base_clips = [
        {**clip_dict(clip), "has_audio": carries_sound(clip)}
        for clip in (media_clips(base_track) if base_track else [])
    ]
    # overlay_views 已是 bottom→top(绘制序),直接展开即可——不要再 reversed 一次。
    # **静音轨的画面保留**:轨道头静音是喇叭图标,只关音频;把画面一并去掉会让「给画中画轨静音」
    # 变成「这层画面从成片里消失」,而预览里它还好好地显示着。音频侧的排除在下面 audible。
    overlay_clips = [clip_dict(clip) for track in overlay_tracks for clip in media_clips(track)]
    # 字幕与花字画哪些,同样由契约实现决定(scene.text_layers ⇄ 前端 textLayers,
    # contracts/text-layer-cases.json):隐藏只管字幕,静音只管声音 —— 静音视频轨上的花字照旧烧录。
    clip_by_id = {clip.id: clip for track in sequence.tracks for clip in track.clips}
    shown_text = text_layers(track_views)
    # 花字按各自 transform 定位烧录。
    text_overlays = [clip_dict(clip_by_id[view["id"]]) for view in shown_text.titles]
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
        # 只有视频片段有声音可混。图片片段此前也进了这张表:执行时探不到音轨会跳过它,但在那之前
        # 它已经被算成闪避的触发源 —— 成片里音乐在一张静图底下被压低,预览里却没有。
        {**clip_dict(clip), "solo": track.solo, "duck": track.duck, "optional": True}
        for track in audible_overlay_tracks
        for clip in media_clips(track)
        if carries_sound(clip)
    ]
    # lane:这条字幕在字幕框里排第几道(时间线上靠上的字幕轨在上)。同一时刻各道的字由计划合成一框。
    subtitle_clips = [
        {**clip_dict(clip_by_id[view["id"]]), "lane": shown_text.subtitle_lanes[view["id"]]} for view in shown_text.subtitles
    ]

    solo_active = any(track.solo for track in sequence.tracks)
    base_video_soloed = bool(base_track and base_track.solo)
    # base 轨自己被静音时也要闭嘴——画面留着,声音去掉,与 overlay 轨同一条规则。
    mute_base_audio = (solo_active and not base_video_soloed) or bool(base_track and base_track.muted)
    # 基底轨也可以标闪避(轨道右键·闪避)。它的声音不走 audio_overlays,所以要单独告诉计划一声 ——
    # 不然界面上按下去了、渲染侧什么都不做。译配就是这个形状:原片在基底轨,配音在音频轨。
    duck_base_audio = bool(base_track and base_track.duck)

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
    width, height, fps, pixel_scale, crf, encode_preset = resolve_export_output(
        sequence.width, sequence.height, sequence.fps, export_params
    )
    #: 成片里用了 AI 生成 / 合成的素材就加标识(ADR 0028 §5):**隐式的总写**(不影响画面,没有关掉的理由),
    #: 显式的按导出时的开关。听得见的才算:静音的音频片段不进成片。
    used = {clip["asset_id"] for clip in base_clips + overlay_clips if clip["asset_id"]}
    used |= {clip["asset_id"] for clip in audio_clips if clip["asset_id"] and not clip.get("muted")}
    generated = ai_generated_assets(db, used)
    ai_label = tr("exportAiLabelText") if generated and (export_params or {}).get("ai_label", True) is not False else ""
    metadata = aigc_metadata(sequence) if generated else ()
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
        subtitle_style=_resolve_subtitle_font(db, sequence),
        text_overlays=text_overlays,
        luts=luts,
        solo_active=solo_active,
        mute_base_audio=mute_base_audio,
        duck_base_audio=duck_base_audio,
        crf=crf,
        encode_preset=encode_preset,
        ai_label=ai_label,
        metadata=metadata,
        loudness_normalize=bool((export_params or {}).get("loudness_normalize", False)),
        pixel_scale=pixel_scale,
    )


#: 由数字人片段拼接出来的素材(如「译配对口型」把几块改口型结果接成的整段):它不是任何一条生成记录的产出,
#: 生成记录认不出它,登记时就标上这个来源。
DIGITAL_HUMAN_SOURCE = "digital_human"


def ai_generated_assets(db: Session, asset_ids: set[str]) -> set[str]:
    """这几份素材里哪些是 AI 生成 / 合成的 —— 成片里有它们,导出就加显式与隐式标识。

    《人工智能生成合成内容标识办法》管的是 AI 生成合成的文本、图片、音频、视频,《深度合成管理规定》第十七条
    点名了合成人声、仿声、人脸生成与操控 —— 不只数字人。此前只认数字人(生成时带驱动音频),文生 / 图生视频、
    AI 图片、AI 配音进了成片什么标识都没有。

    判据只有一份:素材登记时定下、顺着出处继承的 ai_generated(assets/lineage)。时间线上片段的「AI」角标、
    导出对话框里那个开关出不出现,看的也是它 —— 两边各认各的,就会出现「角标亮着、成片没标」。"""
    from app.domain.assets import lineage

    return lineage.ai_generated_assets(db, asset_ids)


def aigc_metadata(sequence: Sequence) -> tuple[tuple[str, str], ...]:
    """隐式标识:写进成片元数据的 AIGC 字段(《人工智能生成合成内容标识办法》第五条、GB 45438 的字段名)。
    ProduceID 是这条时间线和它的修订 —— 能对回是哪一次导出。

    **写在 MP4 的标准键里**(comment / description,iTunes 那组原子),不用自定义键:自定义键要
    `use_metadata_tags` 写成 mdta,而平台转码、用户自己 `ffmpeg -c copy` 一遍,mdta 里认不出的键直接丢
    (审查实测 remux 之后 AIGC 没了,只剩 comment)。comment 在 MP4、MOV 的 remux 和重编码后都还在 ——
    机读的那份 JSON 就放在它里面,外层包一个 "AIGC" 键,字段名不丢;description 放一句人读得懂的话。"""
    import json

    label = {"Label": "1", "ContentProducer": "Mosael", "ProduceID": f"{sequence.id}:{sequence.revision}",
             "ReservedCode1": "", "ContentPropagator": "", "PropagateID": "", "ReservedCode2": ""}
    return (("comment", json.dumps({"AIGC": label}, ensure_ascii=False, separators=(",", ":"))),
            ("description", "Contains AI-generated content (AIGC) · Mosael"))


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


def grab_sequence_frame(db: Session, sequence_id: str, at: float, *, created_by: str | None) -> Asset:
    """把时间线在 `at` 处的合成画面存成一份新素材。

    **同步返回** —— 一帧就是一次 ffmpeg,几百毫秒到两三秒;为它铺一套任务/进度,用户看到的
    只是一个多余的转圈。而**导出成片是任务**,因为那要几十秒到几分钟。

    产出走 register_file_asset(和渲染成片、AI 生成、配音同一条入库路),所以缩略图、探测、
    代理这些一样也不会少。
    """
    from app.media.render_executor import render_still

    #: 取出来的这一帧是**素材**,不是要发布的成片:不烧「AI 生成」标识 —— 片头 3 秒里取一帧,正中就是一块大字。
    #: 它含不含 AI 由出处记着(lineage,登记时继承),拿它再导出的时候标识照加。
    plan = build_plan_for_sequence(db, sequence_id, {"ai_label": False})
    ensure_text_can_burn(plan)
    sequence = db.get(Sequence, sequence_id)
    assert sequence is not None
    with tempfile.TemporaryDirectory(prefix="mosael-still-") as tmp:
        target = Path(tmp) / "frame.jpg"
        render_still(plan, resolve_key, target, at)
        return register_file_asset(
            db,
            workspace_id=sequence.workspace_id,
            project_id=sequence.project_id,
            source_path=target,
            #: 名字带上时间 —— 从同一条时间线取三帧,光看「xxx 的帧」分不出哪张是哪张。
            name=f"{sequence.name} · {at:.1f}s",
            source="generated",
            derived_from=derived(FRAME, *_sources_at(plan, at)),
        )


def _sources_at(plan: RenderPlan, at: float) -> list[str]:
    """`at` 这一刻画面上看得见的素材:那一刻的底轨片段和盖在上面的叠层(取当前帧的出处)。"""
    found: list[str] = []
    cursor = 0.0
    for segment in plan.video_segments:
        if segment.source is not None and cursor <= at < cursor + segment.duration:
            found.append(segment.source.asset_id)
        cursor += segment.duration
    found += [item.source.asset_id for item in plan.overlays if item.start <= at < item.start + item.duration]
    return found


def _export_sources(plan: RenderPlan) -> list[str]:
    """成片用到的素材:底轨的每一段、上层的每一段、混进去的每一段声音(静音的不在计划里)。导出成片的出处。"""
    return [
        *(segment.source.asset_id for segment in plan.video_segments if segment.source is not None),
        *(item.source.asset_id for item in plan.overlays),
        *(item.source.asset_id for item in plan.audio_overlays),
    ]


def start_export(db: Session, sequence_id: str, export_params: dict | None = None, *, created_by: str | None) -> Job:
    """Validate the plan, create the render job, and run FFmpeg off-thread."""
    plan = build_plan_for_sequence(db, sequence_id, export_params)  # raises before job creation
    #: 字烧不了(没有 libass、浏览器那条路也不通)在建任务之前就说,别等跑起来才失败。
    ensure_text_can_burn(plan)
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
    # (MOSAEL_EXTERNAL_JOB_KINDS=render),任务留在 queued 等外部 worker 认领,本函数不变。
    job_id = job.id
    dispatch_job(db, job, lambda: _run_export(job_id, plan))
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
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        if not finish_job(db, job, status="running"):
            return
        say(job, _export_message(PHASE_PREPARE, None))
        emit_job_event(db, job.id, "job.running", {"render_plan_hash": plan.render_plan_hash})
        # 「在导出」先落库:编码要几十秒到几分钟,界面要马上看得到;也把 finish_job 拿的写锁放掉。
        db.commit()
        started = time.monotonic()

        phase = PHASE_PREPARE
        last_fraction = -1.0
        last_write = 0.0

        def write_progress(fraction: float | None, message: str) -> None:
            with unit_of_work() as progress_db:
                progress_job = progress_db.get(Job, job_id)
                if progress_job is not None and finish_job(progress_db, progress_job, status="running"):
                    if fraction is not None:
                        progress_job.progress = round(fraction, 4)
                    say(progress_job, message)

        def on_phase(name: str) -> None:
            nonlocal phase, last_fraction
            phase = name
            if name == PHASE_FALLBACK:
                # 软件编码从头再来:进度条明确回退到 0 并说明原因,而不是无声归零让人以为卡死。
                last_fraction = -1.0
                with unit_of_work() as fb_db:
                    fb_job = fb_db.get(Job, job_id)
                    if fb_job is not None and finish_job(fb_db, fb_job, status="running"):
                        fb_job.progress = 0.0
                        say(fb_job, _export_message(name, None))
                        emit_job_event(fb_db, job_id, "job.encode_fallback", {})
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
                return
            say(job, "jobMsg_renderFinishing")
            # 「封装 / 入库中」先落库再登记:成片要整个拷进素材库(几百 MB),这期间不攥着写锁。
            db.commit()
            sequence = db.get(Sequence, plan.sequence_id)
            asset = register_file_asset(
                db,
                workspace_id=job.workspace_id,
                project_id=sequence.project_id if sequence else None,
                source_path=output_path,
                name=f"{sequence.name if sequence else 'Sequence'} · Export r{plan.sequence_revision}",
                #: 成片的出处是它用到的每一份素材 —— 其中有 AI 内容的,成片也含 AI 内容(导出再拿去剪、再导出,照样认得出)。
                derived_from=derived(EXPORT, *_export_sources(plan)),
            )
            if finish_job(
                db,
                job,
                status="succeeded",
                progress=1.0,
                message="jobMsg_renderDone",
                result={"asset_id": asset.id},
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
            # ffmpeg 写的那个文件是**中转**,不是成品:成功时它已经被拷进素材库(register_file_asset
            # 是流式拷贝,不搬走源文件),失败和取消时它是个半截。三种情况都不该留下 ——
            # 留着的话,成功的导出在磁盘上存两份,取消的导出留一截永远没人清。
            # 实测某台机器上 ~/.mosael/exports 攒了 66 个文件 445 MB,全是这么来的。
            output_path.unlink(missing_ok=True)


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
