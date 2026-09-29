"""译配对口型(ADR 0028 阶段 3「视频翻译 · 改口型」):一条译配好的时间线 → 原片的嘴对上译文配音。

「视频翻译配音」把配音一句一句铺在一条轨上(各自变过速,塞回原句的长度),原片的人声拆掉、背景音留着。改口型要的却是
**一段完整的音频**,而且百炼的改口型一次只收 2–120 秒的视频(描述符的 `source_duration_seconds.source_video`)。所以:

1. 把配音轨上的片段(按各自的起点、截取、变速、增益)混成一段和原片等长的人声;
2. 把原片切成模型收得下的块,**切点优先落在两句配音之间的空当**,不从一句话中间断开;
3. 有配音的块交给改口型(`video_lipsync` 同一个模型挑法、同一个生成漏斗),一句都没有的块直接用原片,不花钱;
4. 各块接回整段(去掉声音 —— 声音已经在配音轨和背景轨上,不重复),放到**最上面一条新的视频轨**、盖在原片上。

原片一个字节都不动:删掉那条轨就回到改口型之前(和译配模板「整条删掉即可回到原样」同一条)。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.ai.providers.contracts.generation import DRIVING_AUDIO, SOURCE_VIDEO
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import RunScope, register
from app.media.tempo import atempo_filters
from app.domain.workflows.executors.talking import VIDEO_LIPSYNC, _generate, _pick_model, _require_consent, _text

#: 模型没声明时的保守上下限(百炼 videoretalk 的文档值)。
DEFAULT_LIMITS = (2.0, 120.0)


@dataclass(frozen=True)
class Line:
    """配音轨上的一句:在原片这一段里的起止(秒),和它自己的文件、截取、变速、增益。"""

    start: float
    end: float
    path: Path
    src_in: float
    speed: float
    gain: float


def plan_chunks(duration: float, lines: list[tuple[float, float]], low: float, high: float) -> list[tuple[float, float]]:
    """原片切成几块:每块在 [low, high] 秒之内,切点优先落在两句之间(没有空当可切时才在上限处硬切)。"""
    if duration <= high:
        return [(0.0, duration)]

    def speaking(at: float) -> bool:
        return any(start < at < end for start, end in lines)

    gaps = sorted({round((a_end + b_start) / 2, 3)
                   for (_a, a_end), (b_start, _b) in zip(sorted(lines), sorted(lines)[1:]) if a_end <= b_start})
    chunks: list[tuple[float, float]] = []
    begin = 0.0
    while duration - begin > high:
        fits = [cut for cut in gaps if begin + low <= cut <= begin + high and not speaking(cut)]
        cut = max(fits) if fits else begin + high
        chunks.append((begin, cut))
        begin = cut
    chunks.append((begin, duration))
    #: 最后一块太短(模型不收):把上一个切点往前挪,让它够长。
    if len(chunks) > 1 and chunks[-1][1] - chunks[-1][0] < low:
        (prev_begin, _), (_, end) = chunks[-2], chunks[-1]
        moved = end - low
        if moved - prev_begin >= low:
            chunks[-2:] = [(prev_begin, moved), (moved, end)]
    return chunks


def _ffmpeg(args: list[str], what: str) -> None:
    from app.core.child_process import run_logged

    result = run_logged([settings.ffmpeg, "-y", "-v", "error", *args], capture_output=True, text=True, timeout=1800, what=what)
    if result.returncode != 0:
        raise WorkflowDomainError("wfErr_dubLipsyncMediaFailed", params={"step": what})


def _mix_voice(lines: list[Line], duration: float, target: Path) -> None:
    """配音轨混成一段和原片这一段等长的人声(没有配音的地方是静音)。"""
    inputs = [part for line in lines for part in ("-i", str(line.path))]
    chains = []
    for index, line in enumerate(lines):
        length = (line.end - line.start) * line.speed
        delay = max(0, int(round(line.start * 1000)))
        chains.append(f"[{index}:a]atrim=start={line.src_in:.3f}:duration={length:.3f},asetpts=PTS-STARTPTS,"
                      f"{atempo_filters(line.speed)}volume={line.gain:.3f},adelay={delay}|{delay}[a{index}]")
    mix = "".join(f"[a{index}]" for index in range(len(lines)))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(lines)}:normalize=0,apad,atrim=0:{duration:.3f}[out]"
    _ffmpeg([*inputs, "-filter_complex", graph, "-map", "[out]", "-ac", "1", "-ar", "24000", str(target)], "配音混成一段")


def _cut(source: Path, start: float, end: float, target: Path, *, audio: bool) -> None:
    what = "切出一段音频" if audio else "切出一段原片"
    keep = ["-vn"] if audio else ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    _ffmpeg(["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source), *keep, str(target)], what)


def _join(parts: list[Path], width: int, height: int, fps: float, target: Path) -> None:
    """各块接回一整段(统一尺寸和帧率,不带声音)。"""
    inputs = [part for path in parts for part in ("-i", str(path))]
    chains = [f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g}[v{index}]" for index in range(len(parts))]
    graph = ";".join(chains) + ";" + "".join(f"[v{index}]" for index in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[out]"
    _ffmpeg([*inputs, "-filter_complex", graph, "-map", "[out]", "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", str(target)], "接回整段")


@register("dub_lipsync")
def dub_lipsync(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一条译配好的时间线上,原片那一段的嘴对上配音轨(见模块说明)。"""
    from app.db.models import Clip, Track
    from app.domain.assets.importer import register_file_asset
    from app.domain.render import DIGITAL_HUMAN_SOURCE
    from app.domain.sequences.operations import AddTrack, InsertClip, MoveTrack, add_track, insert_clip, move_track
    from app.domain.workflows.executors.subjobs import _asset_in, _sequence_in
    from app.media.paths import resolve_key

    _require_consent(config)
    sequence = _sequence_in(db, scope, _text(config.get("sequence_id")))
    clip = db.get(Clip, _text(config.get("clip_id")))
    if clip is None or clip.sequence_id != sequence.id or not clip.asset_id:
        raise WorkflowDomainError("wfErr_dubLipsyncNeedsClip")
    if abs(float(clip.speed) - 1.0) > 1e-6:
        raise WorkflowDomainError("wfErr_dubLipsyncSpeed")
    video = _asset_in(db, scope, clip.asset_id)
    voice_track = db.get(Track, _text(config.get("track_id")))
    if voice_track is None or voice_track.sequence_id != sequence.id:
        raise WorkflowDomainError("wfErr_dubLipsyncNeedsTrack")
    model = _pick_model(db, _text(config.get("model")), VIDEO_LIPSYNC)
    limits = ((model.get("capabilities") or {}).get("source_duration_seconds") or {}).get(SOURCE_VIDEO) or DEFAULT_LIMITS
    low, high = float(limits[0]), float(limits[1])

    span = float(clip.src_out) - float(clip.src_in)
    lines: list[Line] = []
    for one in sorted(voice_track.clips, key=lambda item: float(item.timeline_start)):
        if one.muted or not one.asset_id:
            continue
        start = float(one.timeline_start) - float(clip.timeline_start)
        end = start + (float(one.src_out) - float(one.src_in)) / float(one.speed or 1.0)
        if end <= 0 or start >= span:
            continue
        source = _asset_in(db, scope, one.asset_id)
        lines.append(Line(start=start, end=end, path=resolve_key(str(source.file_key)), src_in=float(one.src_in),
                          speed=float(one.speed or 1.0), gain=float(one.gain)))
    if not lines:
        raise WorkflowDomainError("wfErr_dubLipsyncNoSpeech")

    chunks = plan_chunks(span, [(line.start, line.end) for line in lines], low, high)
    info = video.media_info or {}
    width, height = int(info.get("width") or sequence.width), int(info.get("height") or sequence.height)
    fps = float(info.get("fps") or sequence.fps or 25)
    source_path = resolve_key(str(video.file_key))
    generated = 0
    with tempfile.TemporaryDirectory(prefix="mosael-dub-lipsync-") as folder:
        work = Path(folder)
        voice = work / "voice.wav"
        _mix_voice(lines, span, voice)

        def keep(path: Path, name: str, source: str = "derived") -> str:
            return register_file_asset(db, workspace_id=scope.workspace_id, project_id=None, source_path=path,
                                       name=name, source=source).id

        parts: list[Path] = []
        for index, (begin, end) in enumerate(chunks, start=1):
            piece = work / f"video-{index}.mp4"
            _cut(source_path, float(clip.src_in) + begin, float(clip.src_in) + end, piece, audio=False)
            if not any(line.start < end and line.end > begin for line in lines):
                parts.append(piece)
                continue
            speech = work / f"voice-{index}.wav"
            _cut(voice, begin, end, speech, audio=True)
            label = f"{video.name} · 对口型第 {index} 块"
            results = _generate(db, scope, model, [
                {"asset_id": keep(piece, f"{label}(原片)"), "role": SOURCE_VIDEO},
                {"asset_id": keep(speech, f"{label}(配音)"), "role": DRIVING_AUDIO},
            ])
            if not results:
                raise WorkflowDomainError("wfErr_dubLipsyncNoResult", params={"index": index})
            parts.append(resolve_key(str(_asset_in(db, scope, results[0]).file_key)))
            generated += 1
        joined = work / "lipsync.mp4"
        _join(parts, width, height, fps, joined)
        #: 接回的整段不是哪一条生成记录的产出:标上数字人来源,导出时照样加 AI 标识(ADR 0028 §5)。
        final = keep(joined, f"{video.name} · 对口型", DIGITAL_HUMAN_SOURCE)
    #: 接回来的整段可能比原片短几帧(各块按帧取整):铺上去的长度取两者较短的那个。
    length = min(span, float((_asset_in(db, scope, final).media_info or {}).get("duration") or span))

    #: 放到最上面一条新的视频轨,盖在原片上。新轨建在最下面(add_track),一格一格挪到顶。
    before = {one.id for one in sequence.tracks}
    add_track(db, sequence.id, AddTrack(kind="video"))
    db.refresh(sequence)
    track = next(one for one in sequence.tracks if one.id not in before)
    for _ in range(len(sequence.tracks)):
        move_track(db, sequence.id, MoveTrack(track_id=track.id, direction="up"))
    db.commit()
    placed = insert_clip(db, sequence.id, InsertClip(track_id=track.id, asset_id=final,
                                                    timeline_start=float(clip.timeline_start), src_in=0.0, src_out=length))
    db.commit()
    return {"asset_id": final, "clip_id": placed.id, "track_id": track.id, "chunk_count": len(chunks),
            "generated_count": generated}
