"""译配对口型(ADR 0028 阶段 3「视频译配 · 改口型」):一条译配好的时间线 → 原片的嘴对上译文配音。

「视频译配」把配音一句一句铺在一条轨上(各自变过速,塞回原句的长度),原片的人声拆掉、背景音留着。改口型要的却是
**一段完整的音频**,而且百炼的改口型一次只收 2–120 秒的视频(描述符的 `source_duration_seconds.source_video`)。所以:

1. 把配音轨上的片段(按各自的起点、截取、变速、增益)混成一段和原片等长的人声;
2. 把原片切成模型收得下的块,**切点优先落在两句配音之间的空当**,不从一句话中间断开;
3. 有配音的块交给改口型(`video_lipsync` 同一个模型挑法、同一个生成漏斗),一句都没有的块直接用原片,不花钱;
4. 各块接回整段(去掉声音 —— 声音已经在配音轨和背景轨上,不重复),放到**最上面一条新的视频轨**、盖在原片上。

原片一个字节都不动:删掉最上面那条轨就回到改口型之前。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.ai.providers.contracts.generation import DRIVING_AUDIO, SOURCE_VIDEO
from app.domain.voices.subtitle_dub import DUB_LINE_KEY
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors.common import stop_if_stopping
from app.domain.workflows.executors.registry import PreflightNode, RunScope, register, register_preflight
from app.media.tempo import atempo_filters
from app.domain.workflows.executors.talking import (
    VIDEO_LIPSYNC,
    _generate,
    _pick_model,
    _require_consent,
    _require_voice_consent,
    _text,
    preflight_consent,
    preflight_model,
)

#: 模型没声明时的保守上下限(百炼 videoretalk 的文档值)。
DEFAULT_LIMITS = (2.0, 120.0)
#: 改好口型的那一块素材上记着「它是哪一块」(原片、区间、这块里每句念的什么/谁念的/从哪一秒起、模型的摘要),
#: 重跑时认得出、不再买一次(见 _chunk_key)。
CHUNK_KEY = "dub_lipsync_chunk"


@dataclass(frozen=True)
class Line:
    """配音轨上的一句:在原片这一段里的起止(秒),和它自己的文件、截取、变速、增益。"""

    start: float
    end: float
    path: Path
    src_in: float
    speed: float
    gain: float
    #: 这一句的音频素材(查它是哪把克隆嗓子配的,见 _require_rights)。
    asset_id: str
    #: 这一句「说的是什么」:字幕配音记在音频上的那句话和那把嗓子(voices/subtitle_dub.DUB_LINE_KEY)。
    #: 不是字幕配音配出来的(自己摆上去的一段音频):那段音频本身就是它说的内容,记素材 id。
    said: str


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


def _lines_on(db: Session, scope: RunScope, voice_track: Any, clip_start: float, span: float) -> list[Line]:
    """配音轨上落在原片这一段里的每一句,时间换成原片这一段里的秒数。

    **起点在原片之前的那一句,把头上露在外面的那截剪掉**:混音时 `adelay` 不收负数,此前只是把起点夹到 0,
    截取却仍从这句的开头算 —— 整句往后错了那一截,越往后嘴越对不上。现在起点落在 0,截取往后挪同样一段
    (按这句的变速折回素材里的秒数)。
    """
    from app.domain.workflows.executors.subjobs import _asset_in
    from app.media.paths import resolve_key

    lines: list[Line] = []
    for one in sorted(voice_track.clips, key=lambda item: float(item.timeline_start)):
        if one.muted or not one.asset_id:
            continue
        speed = float(one.speed or 1.0)
        start = float(one.timeline_start) - clip_start
        end = start + (float(one.src_out) - float(one.src_in)) / speed
        if end <= 0 or start >= span:
            continue
        src_in = float(one.src_in)
        if start < 0:
            src_in -= start * speed
            start = 0.0
        source = _asset_in(db, scope, one.asset_id)
        dubbed = (source.media_info or {}).get(DUB_LINE_KEY)
        said = json.dumps(dubbed, ensure_ascii=False, sort_keys=True) if dubbed else f"asset:{source.id}"
        lines.append(Line(start=start, end=end, path=resolve_key(str(source.file_key)), src_in=src_in,
                          speed=speed, gain=float(one.gain), asset_id=source.id, said=said))
    return lines


def _require_rights(db: Session, workspace_id: str, video_id: str, lines: list[Line]) -> None:
    """数字人的两道声明,在花第一分钱之前查(ADR 0028 §4、§5)。

    交给改口型的是**切出来的新素材**:混成一段的配音不再记着是哪把克隆嗓子配的,切出来的原片也不再是哪个人物
    资产的参考图 —— 漏斗里的 check_digital_human_rights 查它们什么都查不到。所以拿**原来的**素材走同一套判据:
    配音轨上每一句的音频(克隆音色要有授权声明)、原片(真人人物资产要有本人或已获同意的声明)。
    """
    from app.domain.generation.operations import GenerationDomainError, check_digital_human_rights

    entries = [{"asset_id": video_id, "role": SOURCE_VIDEO},
               *({"asset_id": asset_id, "role": DRIVING_AUDIO} for asset_id in dict.fromkeys(line.asset_id for line in lines))]
    try:
        check_digital_human_rights(db, workspace_id, entries)
    except GenerationDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _chunk_key(source_digest: str, src_in: float, begin: float, end: float, lines: list[Line], model_id: str) -> str:
    """这一块是不是「同一块」:原片(字节摘要)、区间、这块里每一句(念的字、哪把嗓子、从原片第几秒起)、模型。

    **配音的音频字节不进键。** 整图重跑时翻译和合成都会重来一遍,同一句话同一把嗓子,合成出来的字节每次都可能
    差一点 —— 按字节认,重跑时一块都认不出来,每块再买一次(此前就是这样)。代价也如实:命中时用的是上次那一份
    口型,这次重新合成的那几句如果念得长短略有不同,嘴和声音会差那么一点;译文改了一个字、换了嗓子、挪了时间,
    那一块就是新的,重买。
    """
    #: 时间一律按原片里的秒数记(`src_in` 是原片在时间线上那一段的截取起点):同一段原片换个地方摆,还是同一块。
    said = sorted(f"{src_in + line.start:.3f}|{line.said}" for line in lines if line.start < end and line.end > begin)
    return hashlib.sha256(json.dumps([source_digest, f"{src_in + begin:.3f}-{src_in + end:.3f}", said, model_id],
                                     ensure_ascii=False).encode()).hexdigest()


def _cached_chunk(db: Session, workspace_id: str, key: str) -> str:
    """同一块(见 _chunk_key)之前改过口型:交回那一份,不再花一次钱。"""
    from sqlalchemy import select

    from app.db.models import Asset
    from app.media.paths import resolve_key

    rows = db.scalars(select(Asset).where(Asset.workspace_id == workspace_id, Asset.kind == "video",
                                          Asset.media_info[CHUNK_KEY].as_string() == key))
    return next((row.id for row in rows if row.file_key and resolve_key(str(row.file_key)).is_file()), "")


def _remember_chunk(asset_id: str, key: str) -> None:
    """在改好口型的那一块上记下它是哪一块,**单独一个事务马上落库**:后面哪一块失败、这个节点整体回滚,
    这一块的钱也不白花 —— 重跑时认得出它(见 _cached_chunk)。"""
    from app.core.unit_of_work import unit_of_work
    from app.domain.assets.media_info import patch_media_info

    #: 只补这一个键:这块素材刚登记,代理转码正在别的线程里改它的 media_info(见 assets/media_info)。
    with unit_of_work() as keeper:
        patch_media_info(keeper, asset_id, {CHUNK_KEY: key})


@register_preflight("dub_lipsync")
def dub_lipsync_preflight(db: Session, config: dict[str, Any], actor: str | None, place: PreflightNode) -> None:
    """改口型排在转写、翻译、逐句配音之后:授权没确认、没有会改口型的模型、上游配音用的是没声明的克隆音色,
    都要在那几步花钱之前说。配音的嗓子在**上游**配音节点上(这个节点只接它配好的那条轨),顺着图往上找。"""
    preflight_consent(config, place)
    preflight_model(db, config, place, VIDEO_LIPSYNC, actor)
    for dubbing in place.upstream("dub_subtitles"):
        upstream = PreflightNode(workspace_id=place.workspace_id, graph=place.graph, node=dubbing)
        if upstream.deferred("engine") or upstream.deferred("voice"):
            continue
        voice_config = dubbing.get("config") or {}
        _require_voice_consent(db, _text(voice_config.get("engine")), _text(voice_config.get("voice")))


@register("dub_lipsync")
def dub_lipsync(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一条译配好的时间线上,原片那一段的嘴对上配音轨(见模块说明)。

    **改口型等子任务时,这个会话会被交还**(`_generate` → wait_for_job 的 release:commit + close)。之后
    sequence / clip / video 都是脱离会话、属性已过期的对象,再读一个属性就是 DetachedInstanceError —— 付过钱、
    改好了口型,却在把结果铺上时间线的那一刻崩掉。所以花钱之前把要用的都取成普通值,之后要对象就按 id 重新取。
    """
    from app.db.models import Asset, Clip, Sequence, Track
    from app.domain.assets.importer import register_file_asset
    from app.domain.render import DIGITAL_HUMAN_SOURCE
    from app.domain.sequences.operations import AddTrack, InsertClip, add_track, insert_clip
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

    sequence_id, project_id = sequence.id, sequence.project_id
    clip_start, src_in = float(clip.timeline_start), float(clip.src_in)
    span = float(clip.src_out) - src_in
    video_id, video_name = video.id, video.name
    info = video.media_info or {}
    width, height = int(info.get("width") or sequence.width), int(info.get("height") or sequence.height)
    fps = float(info.get("fps") or sequence.fps or 25)
    source_path = resolve_key(str(video.file_key))
    lines = _lines_on(db, scope, voice_track, clip_start, span)
    if not lines:
        raise WorkflowDomainError("wfErr_dubLipsyncNoSpeech")
    _require_rights(db, scope.workspace_id, video_id, lines)

    #: 切出来的每一块要重新编码,时长按帧取整:29.97 fps 下正好切 120 秒,出来是 3597 帧 = 120.02 秒,漏斗按
    #: 「超过 120 秒」拒掉(下限同理,可能少半帧)。规划时上下限各让出两帧(按原片的帧率)。
    margin = 2 / fps
    chunks = plan_chunks(span, [(line.start, line.end) for line in lines], low + margin, high - margin)
    source_digest = _digest(source_path)
    generated = 0
    reused = 0
    with tempfile.TemporaryDirectory(prefix="mosael-dub-lipsync-") as folder:
        work = Path(folder)
        voice = work / "voice.wav"
        _mix_voice(lines, span, voice)

        def keep(path: Path, name: str, source: str = "derived") -> str:
            #: 挂在译配那个项目下,不散落在素材库的「未归属」里(此前每块两份中间素材都是 project_id=None)。
            return register_file_asset(db, workspace_id=scope.workspace_id, project_id=project_id, source_path=path,
                                       name=name, source=source).id

        parts: list[Path] = []
        for index, (begin, end) in enumerate(chunks, start=1):
            piece = work / f"video-{index}.mp4"
            _cut(source_path, src_in + begin, src_in + end, piece, audio=False)
            if not any(line.start < end and line.end > begin for line in lines):
                parts.append(piece)
                continue
            speech = work / f"voice-{index}.wav"
            _cut(voice, begin, end, speech, audio=True)
            #: 重跑时,已经改好的块不再买一次(什么算「同一块」见 _chunk_key)。
            key = _chunk_key(source_digest, src_in, begin, end, lines, str(model["id"]))
            done = _cached_chunk(db, scope.workspace_id, key)
            if done:
                reused += 1
            else:
                #: 每一块都是一次付费改口型:这一轮在停(取消了、别的节点失败了)就不再提交下一块。
                stop_if_stopping(db)
                label = f"{video_name} · 对口型第 {index} 块"
                results = _generate(db, scope, model, [
                    {"asset_id": keep(piece, f"{label}(原片)"), "role": SOURCE_VIDEO},
                    {"asset_id": keep(speech, f"{label}(配音)"), "role": DRIVING_AUDIO},
                ], project_id=project_id)
                if not results:
                    raise WorkflowDomainError("wfErr_dubLipsyncNoResult", params={"index": index})
                done = _asset_in(db, scope, results[0]).id
                _remember_chunk(done, key)
                generated += 1
            parts.append(resolve_key(str(_asset_in(db, scope, done).file_key)))
        joined = work / "lipsync.mp4"
        _join(parts, width, height, fps, joined)
        #: 接回的整段不是哪一条生成记录的产出:标上数字人来源,导出时照样加 AI 标识(ADR 0028 §5)。
        final = keep(joined, f"{video_name} · 对口型", DIGITAL_HUMAN_SOURCE)
    #: 接回来的整段可能比原片短几帧(各块按帧取整):铺上去的长度取两者较短的那个。
    length = min(span, float((db.get(Asset, final).media_info or {}).get("duration") or span))

    #: 放到最上面一条新的视频轨,盖在原片上(新视频轨默认就建在最上面,见 sequences.tracks.add_track)。
    sequence = db.get(Sequence, sequence_id)
    before = {one.id for one in sequence.tracks}
    add_track(db, sequence_id, AddTrack(kind="video"))
    db.refresh(sequence)
    track = next(one for one in sequence.tracks if one.id not in before)
    track_id = track.id
    placed = insert_clip(db, sequence_id, InsertClip(track_id=track_id, asset_id=final,
                                                    timeline_start=clip_start, src_in=0.0, src_out=length))
    return {"asset_id": final, "clip_id": placed.id, "track_id": track_id, "chunk_count": len(chunks),
            "generated_count": generated, "reused_count": reused}
