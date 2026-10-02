"""字幕配音落轨之后,原声怎么办 —— 压低、静音、原样留着,还是只去掉人声。

这是**配音这件事**的一部分,不是某个入口的:剪辑台、智能体、工作流发起的配音都走这里
(此前它长在工作流执行器里,另两个入口选不了,配出来的片子里两个人同时说话)。
每一步都走剪辑操作,撤得回来;原素材一个字节不动。

**「原声」只是原片的声音**(见 `_is_original_footage`)。此前「静音」把除配音轨外所有发声的轨整条
静音、「只去人声」把每一段带声音的素材都拆一遍 —— BGM 和音效跟着一起没了,第二次配音还会把上次
拆出来的背景音再拆一遍、再叠一条轨。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Clip, Sequence, Track, Transcript

if TYPE_CHECKING:
    from app.domain.sequences.grouping import OperationGroup

#: 界面、智能体、工作流共用的那几档。
ORIGINAL_AUDIO_MODES = ("duck", "mute", "keep", "separate")
DEFAULT_ORIGINAL_AUDIO = "duck"

#: 静音窗两头的过渡。硬切到 0 会在窗口边上咔哒一声;再长就会吃掉配音前后半个字的原声。
_MUTE_RAMP_SECONDS = 0.05
#: 两个关键帧在片段进度上离这么近就算同一个(避免重复处理时越堆越多)。
_KEYFRAME_EPSILON = 1e-4


class OriginalAudioError(LocalizedError, RuntimeError):
    """用户要求的原声处理方式无法如实执行。带文案 key(`dubErr_*`),按读的人的语言翻。"""


def ensure_original_audio_mode(mode: str, *, owner_user_id: str | None) -> None:
    """在排配音任务前验证选择，避免做完配音才发现分离能力不存在。

    `owner_user_id` 是这次配音替谁做的:分离用**他的**默认提供方(他定过的插件连接也算)。此前这里传 None ——
    没有人就没有插件,定了分离插件的人在这一步被说成「没有分离能力」,而检查页说他齐了。"""
    if mode not in ORIGINAL_AUDIO_MODES:
        raise OriginalAudioError("dubErr_originalAudioMode", modes=" / ".join(ORIGINAL_AUDIO_MODES))
    if mode == "separate":
        from app.domain import capabilities
        from app.domain.assets.separation import available
        from app.domain.audio_capabilities import SEPARATION

        from app.core.db import SessionLocal

        with SessionLocal() as db:
            if not available(db, owner_user_id):
                #: 他接了分离插件、只是没定成默认:没定时按本机引擎挑(声音交给插件必须是他自己定过的),本机引擎又没装。
                #: 此前一律说「请管理员装引擎」—— 他明明有一家现成能用的,该说的是去设置里把它定成默认。
                ready = [one.name for one in capabilities.plugin_providers(db, owner_user_id, SEPARATION) if not one.missing]
                if ready:
                    raise OriginalAudioError("dubErr_separationPluginNotDefault", names="、".join(ready))
                raise OriginalAudioError("dubErr_separationUnavailableForMode")


def _carries_audio(track: Track) -> bool:
    """这条轨上有没有可能发出声音 —— 音频轨算,带媒体片段的视频轨也算。"""
    if track.kind == "audio":
        return True
    if track.kind != "video":
        return False
    return any(clip.asset_id for clip in (track.clips or []))


def _is_original_footage(db: Session, asset: Asset | None) -> bool:
    """这份素材的声音算不算「原声」—— 字幕和配音说的是它里面的那段话。

    - **视频素材算**:原片(含分离到音频轨上的那段原片声音,它用的还是同一份视频素材)。
    - **转写过的音频算**:口播录音、播客 —— 字幕就是从它转出来的。
    - 其余音频不算:BGM、音效、上次分离出来的背景音、配音本身。它们本来就不该跟着原声一起被静音或去人声。
    """
    if asset is None:
        return False
    info = asset.media_info or {}
    if info.get("derivation") == "separate_audio":
        return False
    if asset.kind == "video":
        return True
    if asset.kind != "audio":
        return False
    return db.scalar(select(func.count()).select_from(Transcript).where(Transcript.asset_id == asset.id)) > 0


def _dub_windows(db: Session, dub_track_id: str) -> list[tuple[float, float]]:
    """配音在时间线上占着的时间窗(合并过的)。"""
    from app.domain.sequences.operations import timeline_span

    spans = sorted(
        (clip.timeline_start, clip.timeline_start + timeline_span(clip))
        for clip in db.scalars(select(Clip).where(Clip.track_id == dub_track_id))
    )
    merged: list[tuple[float, float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _original_clips(db: Session, sequence: Sequence, dub_track_id: str, windows: list[tuple[float, float]]) -> list[Clip]:
    """配音盖得到的、原片发声的那些片段(轨和片段都没被静音)。"""
    from app.domain.sequences.operations import timeline_span

    chosen: list[Clip] = []
    for track in sequence.tracks or []:
        if track.id == dub_track_id or track.role == "dub" or track.muted or not _carries_audio(track):
            continue
        for clip in track.clips or []:
            if not clip.asset_id or clip.muted:
                continue
            start, end = clip.timeline_start, clip.timeline_start + timeline_span(clip)
            if not any(ws < end and we > start for ws, we in windows):
                continue
            if _is_original_footage(db, db.get(Asset, clip.asset_id)):
                chosen.append(clip)
    return chosen


@contextmanager
def _in_group(db: Session, group: OperationGroup | None) -> Iterator[None]:
    with group.collect(db) if group is not None else nullcontext():
        yield


def apply_original_audio(
    sequence_id: str, dub_track_id: str, mode: str, *, actor_id: str | None, group: OperationGroup | None = None
) -> str:
    """配音落轨之后,原声怎么办。自己开会话(分离要先拿渲染名额、再开会话);`group` 给了就把改时间线的
    那几步记进去(配音那一组,见 subtitle_dub)。

    **「压低」不等于「听不见」。** 闪避把原声压到 30%(≈ −10.5 dB),那是给「旁白盖在环境音
    之上」准备的档位:环境音本来就该若隐若现。而译配是**用另一种语言的说话声替换说话声** ——
    两边都是人声,压到 30% 的结果是观众同时听见两个人在说话,只是一个小声点。真机上报回来的
    正是这个:「视频原本的文案对应的音频还在」。所以译配那条流程用 `mute`。

    - `duck`:除配音轨外每条发声的轨都标闪避 —— BGM 一起让路正是想要的(对白之下压低音乐是常规做法),
      而且渲染的闪避规则是「没标闪避的有声轨都是关键音源」:只标原片轨的话,BGM 自己成了关键音源,
      原片在整段音乐底下都被压低。
    - `mute`:**只静原片、只静配音占着的那几段**。用片段的音量关键帧在配音时间窗里压到 0,窗外原样 ——
      此前是整条轨静音,BGM、音效、没配音的段落全没了声。
    - `separate`:只拆原片、只拆配音盖到的那几段用到的区间,背景音放到音频轨上、源片段静音。
    """
    ensure_original_audio_mode(mode, owner_user_id=actor_id)
    if mode == "keep" or not dub_track_id:
        return "keep"
    if mode == "separate":
        _split_voice_from_music(sequence_id, dub_track_id, actor_id=actor_id, group=group)
        return "separate"
    with unit_of_work() as db, _in_group(db, group):
        sequence = db.get(Sequence, sequence_id)
        if sequence is None:
            return mode
        if mode == "mute":
            _mute_under_dub(db, sequence, dub_track_id, actor_id=actor_id)
        else:
            _duck_everything_else(db, sequence, dub_track_id, actor_id=actor_id)
    return mode


def _duck_everything_else(db: Session, sequence: Sequence, dub_track_id: str, *, actor_id: str | None) -> None:
    """闪避两种模式都**不动配音轨**:闪避要求配音轨自己不闪避,否则没有任何一条轨是"关键音源"。

    **视频轨也要算。** 一条视频片段自带的声音和音频轨上的声音一样会被听见,而译配这条流程恰恰把
    原片整段放在视频轨上(音频轨是空的)—— 只挑 kind=="audio" 的话,标记落在一条没有片段的空轨上。
    """
    from app.domain.sequences.operations import SetTrackState, set_track_state

    # 先把要改的那几条挑出来:改动会 flush,边遍历边改的话,下一圈读到的可能是过期的对象。
    targets = [
        track.id
        for track in (sequence.tracks or [])
        if track.id != dub_track_id and track.role != "dub" and _carries_audio(track) and not track.duck
    ]
    for track_id in targets:
        set_track_state(db, sequence.id, SetTrackState(track_id=track_id, duck=True, actor_id=actor_id))


def _mute_under_dub(db: Session, sequence: Sequence, dub_track_id: str, *, actor_id: str | None) -> None:
    from app.domain.sequences.operations import SetClipEffects, set_clip_effects, timeline_span

    windows = _dub_windows(db, dub_track_id)
    plan: list[tuple[str, dict[str, Any]]] = []
    for clip in _original_clips(db, sequence, dub_track_id, windows):
        effects = dict(clip.effects or {})
        keyframes = muted_gain_keyframes(
            effects.get("gain_keyframes"), clip.gain, clip.timeline_start, timeline_span(clip), windows
        )
        if keyframes != effects.get("gain_keyframes"):
            plan.append((clip.id, {**effects, "gain_keyframes": keyframes}))
    for clip_id, effects in plan:
        set_clip_effects(db, sequence.id, SetClipEffects(clip_id=clip_id, effects=effects, actor_id=actor_id))


def _sample(points: list[tuple[float, float]], t: float, fallback: float) -> float:
    """分段线性 + 端点保持(和导出 _kf_expr、预览 sampleGain 同一个内核);少于两个点按静态音量。"""
    if len(points) < 2:
        return fallback
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0.0)
    return points[-1][1]


def muted_gain_keyframes(
    existing: Any, gain: float, clip_start: float, clip_duration: float, windows: list[tuple[float, float]]
) -> list[dict[str, float]]:
    """这一段的音量关键帧,在 `windows`(时间线秒)里压到 0、两头各留一小段过渡,窗外保持原来的音量曲线。

    关键帧的 t 是片段内进度(0 = 片段头,1 = 片段尾);两个点以上时它**取代**静态音量,所以没有关键帧
    的片段用它的静态音量当底。已有的曲线逐点乘上静音遮罩 —— 用户自己画的音量起伏在窗外原样保留。
    重复处理同一个窗口得到的是同一组点(不会越堆越多)。
    """
    if clip_duration <= 0:
        return list(existing) if isinstance(existing, list) else []
    base = sorted(
        (float(point["t"]), float(point["gain"]))
        for point in (existing if isinstance(existing, list) else [])
        if isinstance(point, dict) and isinstance(point.get("t"), (int, float)) and isinstance(point.get("gain"), (int, float))
    )

    def progress(seconds: float) -> float:
        return (seconds - clip_start) / clip_duration

    def mask(seconds: float) -> float:
        level = 1.0
        for start, end in windows:
            if start <= seconds <= end:
                return 0.0
            if start - _MUTE_RAMP_SECONDS < seconds < start:
                level = min(level, (start - seconds) / _MUTE_RAMP_SECONDS)
            elif end < seconds < end + _MUTE_RAMP_SECONDS:
                level = min(level, (seconds - end) / _MUTE_RAMP_SECONDS)
        return level

    times = {0.0, 1.0, *(t for t, _ in base)}
    for start, end in windows:
        for edge in (start - _MUTE_RAMP_SECONDS, start, end, end + _MUTE_RAMP_SECONDS):
            t = progress(edge)
            if 0.0 < t < 1.0:
                times.add(t)
    points: list[dict[str, float]] = []
    for t in sorted(times):
        if points and t - points[-1]["t"] < _KEYFRAME_EPSILON:
            continue
        value = _sample(base, t, gain) * mask(clip_start + t * clip_duration)
        points.append({"t": round(t, 6), "gain": round(value, 6)})
    return points


def _cached_background(db: Session, asset: Asset, span: tuple[float, float]) -> tuple[str, float] | None:
    """这份素材之前拆出来过、覆盖得了 `span` 的背景音:(素材 id, 它从原素材第几秒开始)。

    **按素材缓存**:第二次配音、换个嗓子再配一次,不该把同一段原片再拆一遍(分离一跑就是几分钟)。
    """
    rows = db.scalars(
        select(Asset)
        .where(
            Asset.workspace_id == asset.workspace_id,
            func.json_extract(Asset.media_info, "$.derived_from_asset_id") == asset.id,
            func.json_extract(Asset.media_info, "$.derivation") == "separate_audio",
            func.json_extract(Asset.media_info, "$.stem") == "background",
        )
        .order_by(Asset.created_at.desc())
    )
    for row in rows:
        if not row.file_key:
            continue
        covered = (row.media_info or {}).get("source_range")
        if covered is None:
            return row.id, 0.0
        start, end = float(covered[0]), float(covered[1])
        if start <= span[0] + 1e-3 and end >= span[1] - 1e-3:
            return row.id, start
    return None


def _split_voice_from_music(
    sequence_id: str, dub_track_id: str, *, actor_id: str | None, group: OperationGroup | None
) -> None:
    """原声只留背景音,人声那半丢掉;无法完整执行就报错。

    这是 `original_audio: separate` 的实现。配音盖到的每一段原片(见 `_original_clips`)走一次「分离音频」:
    背景音放到一条音频轨上、时间对齐,源片段静音。**画面不动** —— 此前这里把视频片段直接指向了背景音素材,
    而视频轨上的纯音频素材既不算画面、也不进混音,成片里原片那一段就只剩静音。
    走剪辑操作而不是改行,所以和闪避、静音一样撤得回来;原素材一个字节不动。

    **只拆用到的区间**:一小时的原片只用了其中两分钟,就只拆那两分钟。拆出来的背景音记着它对应原素材的
    哪一段(`source_range`),放上时间线时按这个偏移对齐。
    **占渲染名额**(RENDER_SLOTS):分离和导出一样是「这台机器要忙很久」的活。先拿名额、再开会话。

    **先全部分离完再动时间线**:分到一半失败时不能留下半套背景音轨。用户明确选择的是
    ``separate``，任何静音降级都会改变成片语义，因此失败必须原样上报。
    """
    from app.ai.providers.contracts.separation import SeparationError
    from app.domain.assets.separation import available, separate_asset
    from app.domain.jobs import RENDER_SLOTS
    from app.domain.sequences.operations import DetachClipAudio, detach_clip_audio

    with unit_of_work() as db:
        sequence = db.get(Sequence, sequence_id)
        if sequence is None:
            raise OriginalAudioError("dubErr_sequenceNotFound")
        sources = _original_clips(db, sequence, dub_track_id, _dub_windows(db, dub_track_id))
        spans: dict[str, tuple[float, float]] = {}
        for clip in sources:
            low, high = spans.get(str(clip.asset_id), (clip.src_in, clip.src_out))
            spans[str(clip.asset_id)] = (min(low, clip.src_in), max(high, clip.src_out))
        backgrounds: dict[str, tuple[str, float]] = {}
        missing: list[str] = []
        for asset_id, span in spans.items():
            asset = db.get(Asset, asset_id)
            if asset is None or asset.kind not in ("audio", "video"):
                continue
            cached = _cached_background(db, asset, span)
            if cached is not None:
                backgrounds[asset_id] = cached
            else:
                missing.append(asset_id)
        if missing and not available(db, actor_id):
            raise OriginalAudioError("dubErr_separationUnavailable")
        plan_clips = [(clip.id, str(clip.asset_id)) for clip in sources]

    if missing:
        with RENDER_SLOTS:
            for asset_id in missing:
                with unit_of_work() as db:
                    asset = db.get(Asset, asset_id)
                    try:
                        made = separate_asset(db, asset, engine="", owner_user_id=actor_id, span=spans[asset_id])
                    except SeparationError as exc:
                        # 分离那边的原因原样作参数(它若带 key,渲染时按读的人的语言翻)。
                        raise OriginalAudioError("dubErr_removeVoiceFailed", detail=exc) from exc
                    backgrounds[asset_id] = (made.background.id, spans[asset_id][0])

    with unit_of_work() as db, _in_group(db, group):
        for clip_id, asset_id in plan_clips:
            if asset_id not in backgrounds:
                continue
            background_id, offset = backgrounds[asset_id]
            detach_clip_audio(
                db,
                sequence_id,
                DetachClipAudio(clip_id=clip_id, audio_asset_id=background_id, audio_src_offset=offset, actor_id=actor_id),
            )
