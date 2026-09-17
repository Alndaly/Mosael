"""字幕配音落轨之后,原声怎么办 —— 压低、静音、原样留着,还是只去掉人声。

这是**配音这件事**的一部分,不是某个入口的:剪辑台、智能体、工作流发起的配音都走这里
(此前它长在工作流执行器里,另两个入口选不了,配出来的片子里两个人同时说话)。
每一步都走剪辑操作,撤得回来;原素材一个字节不动。
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.models import Asset, Sequence, Track

logger = logging.getLogger(__name__)

#: 界面、智能体、工作流共用的那几档。实际用了哪一档由 apply_original_audio 返回 ——
#: separate 在没有分离引擎时退回 mute_fallback。
ORIGINAL_AUDIO_MODES = ("duck", "mute", "keep", "separate")
DEFAULT_ORIGINAL_AUDIO = "duck"


def _carries_audio(track: Track) -> bool:
    """这条轨上有没有可能发出声音 —— 音频轨算,带媒体片段的视频轨也算。"""
    if track.kind == "audio":
        return True
    if track.kind != "video":
        return False
    return any(clip.asset_id for clip in (track.clips or []))


def apply_original_audio(db: Session, sequence_id: str, dub_track_id: str, mode: str, *, actor_id: str | None) -> str:
    """配音落轨之后,原声怎么办 —— 压低、静音,还是原样留着。返回**实际**用的那种。

    **「压低」不等于「听不见」。** 闪避把原声压到 30%(≈ −10.5 dB),那是给「旁白盖在环境音
    之上」准备的档位:环境音本来就该若隐若现。而译配是**用另一种语言的说话声替换说话声** ——
    两边都是人声,压到 30% 的结果是观众同时听见两个人在说话,只是一个小声点。真机上报回来的
    正是这个:「视频原本的文案对应的音频还在」。

    所以译配那条流程用 `mute`:原片整段的声音在成片里不出现。它仍然**不删任何东西** ——
    动的是轨道上那个静音位,轨还在、片段还在,取消静音就回到原样,和闪避同样可撤销。
    带音乐的片子想留背景音时选 `duck`。

    两种模式都**只动原有的**那几条轨,不动配音轨:闪避要求配音轨自己不闪避,否则没有任何一条
    轨是"关键音源",闪避窗口算出来是空的。

    **视频轨也要算。** 一条视频片段自带的声音和音频轨上的声音一样会被听见,而译配这条流程
    恰恰把原片整段放在视频轨上(音频轨是空的)—— 只挑 kind=="audio" 的话,标记落在一条没有
    片段的空轨上,成片里原声一分贝没降。带画面的轨只在真有媒体片段时才算数:纯文字/纯占位的
    轨没有声音可压。
    """
    from app.domain.sequences.operations import SetTrackState, set_track_state

    if mode not in ORIGINAL_AUDIO_MODES:
        raise ValueError(f"原声处理方式只能是 {' / '.join(ORIGINAL_AUDIO_MODES)}")
    if mode == "keep":
        return "keep"
    if mode == "separate":
        #: 分不成就退回整轨静音 —— **一个没装的可选引擎不该让一条本来能跑完的流程失败**
        #: (ADR-0016 决定 4)。退回的是"原声全没",不是"原声全在":后者才会让成片里
        #: 两个人同时说话,而那正是用户报回来的那个症状。
        if _split_voice_from_music(db, sequence_id, dub_track_id, actor_id=actor_id):
            return "separate"
        logger.info("没有可用的音频分离引擎,原声整轨静音(序列 %s)", sequence_id)
        mode = "mute_fallback"
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        return mode
    # 先把要改的那几条挑出来:set_track_state 会 commit,而 commit 之后 sequence.tracks
    # 上的对象全部过期 —— 边遍历边改的话,下一圈读 track.kind 会去重新查一遍库。
    mute = mode in {"mute", "mute_fallback"}
    targets = [
        track.id
        for track in (sequence.tracks or [])
        if track.id != dub_track_id
        and _carries_audio(track)
        # 已经是那个状态的不重复记一次操作 —— 那只会在撤销栈里堆空步。
        and (not track.muted if mute else not track.duck)
    ]
    for track_id in targets:
        #: SetTrackState 是 frozen 的 —— 建好就不能再改字段,所以一次性构造。
        set_track_state(
            db,
            sequence_id,
            SetTrackState(
                track_id=track_id,
                muted=True if mute else None,
                duck=None if mute else True,
                actor_id=actor_id,
            ),
        )
    return mode


def _split_voice_from_music(db: Session, sequence_id: str, dub_track_id: str, *, actor_id: str | None) -> bool:
    """原声只留背景音,人声那半丢掉。成功返回 True。

    这是 `original_audio: separate` 的实现。每个发声的片段走一次「分离音频」:背景音放到一条
    音频轨上、时间对齐,源片段静音。**画面不动** —— 此前这里把视频片段直接指向了背景音素材,
    而视频轨上的纯音频素材既不算画面、也不进混音,成片里原片那一段就只剩静音。
    走剪辑操作而不是改行,所以和闪避、静音一样撤得回来;原素材一个字节不动。

    **先全部分离完再动时间线**:分到一半失败时调用方退回整轨静音,不能留下半套背景音轨。
    问不到引擎就返回 False,由调用方退回整轨静音 —— 见 ADR-0016 决定 4。
    """
    from app.ai.providers.contracts.separation import SeparationError
    from app.domain.separation import available, separate_asset
    from app.domain.sequences.operations import DetachClipAudio, detach_clip_audio

    if not available():
        return False
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        return False
    sources = [
        clip
        for track in sequence.tracks or []
        if track.id != dub_track_id and not track.muted and _carries_audio(track)
        for clip in track.clips or []
        if clip.asset_id and not clip.muted
    ]
    backgrounds: dict[str, str] = {}
    for asset_id in dict.fromkeys(clip.asset_id for clip in sources):
        asset = db.get(Asset, asset_id)
        if asset is None or asset.kind not in ("audio", "video"):
            continue
        try:
            backgrounds[asset_id] = separate_asset(db, asset, engine="").background.id
        except SeparationError as exc:
            logger.warning("分离失败,原声退回静音:%s", exc)
            return False
    #: 先取出 id:每次操作都会 commit,之后 ORM 对象全部过期。
    plan = [(clip.id, backgrounds[clip.asset_id]) for clip in sources if clip.asset_id in backgrounds]
    for clip_id, background_id in plan:
        detach_clip_audio(db, sequence_id, DetachClipAudio(clip_id=clip_id, audio_asset_id=background_id, actor_id=actor_id))
    return bool(plan)
