"""片段的放置:插入、移动、修剪、删除与波纹删除。"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from math import inf

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, Track
from app.domain.media_kinds import MEDIA_KINDS
from app.domain.sequences._timeline import (
    INHERITED_CLIP_FIELDS,
    MIN_CUT_REMAINDER,
    _record_operation,
    _require_clip,
    _require_sequence,
    _require_target_track,
    _slice_keyframes,
    _sliced_transform,
    _validate_clip_range,
    finite_number,
    require_speed,
    timeline_span,
    too_short,
)
from app.domain.sequences.coverage import (
    clear_range,
    clip_end,
    make_room,
    neighbours,
    remove_time_ranges,
)
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.domain.sequences.fitting import fit_asset_on_track
from app.domain.sequences.journal import Journal
from app.domain.sequences.links import linked_members, new_link_group, with_links


@dataclass(frozen=True)
class InsertClip:
    track_id: str
    asset_id: str
    timeline_start: float
    src_in: float
    src_out: float
    # Insert-edit:落点后的同轨片段右移让位(与 MoveClip.ripple 同语义)。不让位就是覆盖。
    ripple: bool = False
    #: 一放下就是这个倍速。配音、旁白按它的位置定速:先按 1 倍放下再改速的话,放下那一刻多出来的
    #: 那截已经把后面的片段盖掉了。
    speed: float = 1.0
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveClip:
    clip_id: str
    timeline_start: float
    track_id: str | None = None
    # Insert-edit (DaVinci "insert" mode): push destination-track clips at or
    # after the drop point right by this clip's duration to make room.
    ripple: bool = False
    #: 链接组(视频和它分离出去的音频)一起动;False = 只动这一段(前端的「临时解链」)。见 links.py。
    linked: bool = True
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveClipsBatch:
    """一次手势移动多个片段(框选后整组拖动)。

    刻意不是「循环调用 move_clip」:那样 N 个片段会产生 N 条 SequenceOperation,撤销一次
    只退回一个,用户得按 N 次 ⌘Z 才能还原一次拖动。整组落成一条操作,撤销才与手势对齐。

    也不支持 ripple:插入模式为单个片段"挤开下游"是明确的,一组跨轨片段要挤开什么则没有
    唯一解。组拖一律按覆盖(overwrite)语义,与前端 startClipDrag 里的说明一致:落点盖住的
    同轨片段被裁掉或切开;组里的几段彼此叠上时,后开始的盖住先开始的。
    """

    moves: tuple["ClipMove", ...]
    #: 链接组(视频和它分离出去的音频)一起动;False = 只动这一段(前端的「临时解链」)。见 links.py。
    linked: bool = True
    actor_id: str | None = None


@dataclass(frozen=True)
class ClipMove:
    clip_id: str
    timeline_start: float
    track_id: str | None = None


@dataclass(frozen=True)
class TrimClip:
    clip_id: str
    timeline_start: float
    src_in: float
    src_out: float
    #: 链接组(视频和它分离出去的音频)一起动;False = 只动这一段(前端的「临时解链」)。见 links.py。
    linked: bool = True
    actor_id: str | None = None


@dataclass(frozen=True)
class DeleteClip:
    clip_id: str
    #: 链接组(视频和它分离出去的音频)一起动;False = 只动这一段(前端的「临时解链」)。见 links.py。
    linked: bool = True
    actor_id: str | None = None


def insert_clip(db: Session, sequence_id: str, op: InsertClip) -> Clip:
    """插入一个片段,返回**插进去的那一段**。

    此前返回整条时间线,于是调用方只能自己去猜刚插的是哪一段:「接到时间线」取整条序列里
    最新的一段(并行分支同时往上接时拿到的是别人的),字幕配音按落点在轨上找(重配同一句时
    找到的是上一次的配音)—— 变速都加错了地方。新建的东西由建它的操作说出来,不要让人猜。

    落点上已有片段时是**覆盖**(coverage.clear_range);插入模式(ripple)先把后面的推开再放。
    """
    sequence = _require_sequence(db, sequence_id)
    journal = Journal(db, sequence)
    clip = place_clip(journal, op)
    _record_operation(
        db,
        sequence,
        kind="insert_clip",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "insert_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return clip


def place_clip(journal: Journal, op: InsertClip) -> Clip:
    """插入的本体:校验、建行、站稳(覆盖 / 让位)—— 经由改动日志写,**不记账**,交回放下的那一段。

    拆出来是给要把插入和别的改动记成**一步**的入口用的(接到空时间线时连画幅一起改,见 append)。
    """
    db, sequence = journal.db, journal.sequence
    track = _require_target_track(db, sequence.id, op.track_id)
    asset = db.get(Asset, op.asset_id)
    if asset is None or asset.workspace_id != sequence.workspace_id:
        raise SequenceNotFound("Asset not found")
    if asset.kind not in MEDIA_KINDS:
        #: 文档(ADR 0031)没有画面和声音可放 —— 渲染时会炸在 ffmpeg 里,在这里就说清楚。
        raise SequenceDomainError("seqErr_assetNotMedia", name=asset.name)
    _validate_clip_range(op.timeline_start, op.src_in, op.src_out)
    src_out = fit_asset_on_track(asset, track, op.src_in, op.src_out)
    if too_short(src_out - op.src_in):
        raise SequenceDomainError("seqErr_clipTooShort", min=MIN_CUT_REMAINDER)
    speed = require_speed(op.speed)

    clip = journal.create(
        Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=track.id,
            asset_id=asset.id,
            timeline_start=op.timeline_start,
            src_in=op.src_in,
            src_out=src_out,
            speed=speed,
        )
    )
    _land(journal, [clip], ripple=op.ripple)
    return clip


def _land(journal: Journal, placed: list[Clip], *, ripple: bool) -> None:
    """刚放到新位置的几段,在各自的轨上站稳:插入模式先让位,然后覆盖落点上剩下的。

    **后开始的先站**:同一次放下的几段彼此叠着时(整组拖到一起),后开始的那段盖住先开始的
    那段 —— 和迁移规整老数据同一条规矩。倒过来的话,先开始的那段会把后开始的挖掉。
    """
    placed_ids = {clip.id for clip in placed}
    if ripple:
        for clip in placed:
            make_room(journal, clip.track_id, clip.timeline_start, clip_end(clip), exclude=placed_ids)
    for clip in sorted(placed, key=lambda one: one.timeline_start, reverse=True):
        if inspect(clip).was_deleted:  # 被同一次放下的、更晚开始的那段整个盖住了
            continue
        clear_range(journal, clip.track_id, clip.timeline_start, clip_end(clip), keep={clip.id})


def _target_track(db: Session, sequence_id: str, clip: Clip, track_id: str | None) -> str:
    target_track_id = track_id or clip.track_id
    if target_track_id != clip.track_id:
        target = _require_target_track(db, sequence_id, target_track_id)
        if target.kind != clip.track.kind:
            raise SequenceDomainError("Target track kind does not match clip track kind")
    return target_track_id


def move_clip(db: Session, sequence_id: str, op: MoveClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    timeline_start = finite_number("timeline_start", op.timeline_start)
    if timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")
    target_track_id = _target_track(db, sequence_id, clip, op.track_id)

    journal = Journal(db, sequence)
    moved = _move_with_links(journal, [(clip, timeline_start, target_track_id)], linked=op.linked)
    _land(journal, moved, ripple=op.ripple)
    _record_operation(
        db,
        sequence,
        kind="move_clip",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "move_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return sequence


def move_clips_batch(db: Session, sequence_id: str, op: MoveClipsBatch) -> Sequence:
    """整组移动。逐个校验后一次性记账,失败则整组不落(校验先于任何写入)。"""
    sequence = _require_sequence(db, sequence_id)
    if not op.moves:
        raise SequenceDomainError("No clips to move")

    planned: list[tuple[Clip, float, str]] = []
    for move in op.moves:
        start = finite_number("timeline_start", move.timeline_start)
        if start < 0:
            raise SequenceDomainError("timeline_start must be non-negative")
        clip = _require_clip(db, sequence_id, move.clip_id)
        planned.append((clip, start, _target_track(db, sequence_id, clip, move.track_id)))

    journal = Journal(db, sequence)
    moved = _move_with_links(journal, planned, linked=op.linked)
    _land(journal, moved, ripple=False)
    _record_operation(
        db,
        sequence,
        kind="move_clips_batch",
        payload={"clip_ids": [clip.id for clip, _, _ in planned], "changes": journal.entries},
        summary={"operation": "move_clips_batch", "count": len(planned)},
        actor_id=op.actor_id,
    )
    return sequence


def _move_with_links(journal: Journal, planned: list[tuple[Clip, float, str]], *, linked: bool) -> list[Clip]:
    """把点中的几段挪到各自的落点,同组的片段平移同样的量(留在自己的轨上)。返回挪过的全部片段。

    一组里谁也不能挪到 0 之前:往左拖过头时整组停在最早那段碰到 0 的位置,而不是只把它压扁在 0 上 ——
    那样音画就错开了。
    """
    picked = {clip.id for clip, _, _ in planned}
    followers: dict[str, tuple[Clip, Clip]] = {}  # 组员 id → (组员, 带着它的那段)
    for clip, _, _ in planned:
        for member in linked_members(journal.db, [clip], linked=linked):
            if member.id not in picked:
                followers.setdefault(member.id, (member, clip))
    moved: list[Clip] = []
    for clip, start, track_id in planned:
        group = [clip] + [member for member, leader in followers.values() if leader is clip]
        delta = max(start - clip.timeline_start, -min(one.timeline_start for one in group))
        for member in group[1:]:
            journal.update(member, timeline_start=member.timeline_start + delta)
        journal.update(clip, timeline_start=clip.timeline_start + delta, track_id=track_id)
        moved.extend(group)
    return moved


def trim_clip(db: Session, sequence_id: str, op: TrimClip) -> Sequence:
    """修剪:改片段的起点、入点、出点。**拉进邻居时夹到邻居的边上**,不盖住它。

    修剪是在动这一段自己的边,用户没打算动邻居 —— 和放下一段(覆盖)不是一回事。夹住而不是
    报错:拖过头是手势的常态,停在边上就是用户要的结果。

    链接的组员跟着修同一条边、修同样的量(头往右收 1 秒,链接音频的头也收 1 秒),而且**整组一起夹**:
    哪一段先碰到邻居、素材头尾,整组就停在那里 —— 只让一段停下的话,音画就错开了。
    """
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    _validate_clip_range(op.timeline_start, op.src_in, op.src_out)

    speed = clip.speed or 1.0
    start, src_in, src_out = float(op.timeline_start), float(op.src_in), float(op.src_out)
    members = linked_members(db, [clip], linked=op.linked)
    group_ids = {clip.id, *(member.id for member in members)}
    head = start - clip.timeline_start  # 起点挪了多少(时间线秒,往右为正)
    tail = start + (src_out - src_in) / speed - clip_end(clip)  # 终点挪了多少

    head_floor, tail_ceiling = -inf, inf
    for one in (clip, *members):
        previous_end, next_start = neighbours(db, one, exclude=group_ids)
        head_floor = max(head_floor, previous_end - one.timeline_start)
        tail_ceiling = min(tail_ceiling, next_start - clip_end(one))
    # 源区间也夹:不早于素材的 0、不晚于素材的末尾 —— 点中的这段和组员一样(往外拉出去的那一截渲染时是空白;
    # 此前只夹了组员,点中的这段能拉成 10 秒素材上的 40 秒片段)。
    for one in (clip, *members):
        one_speed = one.speed or 1.0
        head_floor = max(head_floor, -one.src_in / one_speed)
        duration = _source_duration(one)
        if duration is not None:
            tail_ceiling = min(tail_ceiling, (duration - one.src_out) / one_speed)
    clamped_head, clamped_tail = max(head, head_floor), min(tail, tail_ceiling)
    start += clamped_head - head
    src_in += (clamped_head - head) * speed
    src_out += (clamped_tail - tail) * speed
    if too_short(src_out - src_in) or any(
        too_short((timeline_span(member) - clamped_head + clamped_tail) * (member.speed or 1.0)) for member in members
    ):
        raise SequenceDomainError("seqErr_trimNoRoom")

    journal = Journal(db, sequence)
    journal.update(clip, timeline_start=start, src_in=src_in, src_out=src_out, **_reanchored(clip, src_in, src_out))
    for member in members:
        member_speed = member.speed or 1.0
        member_in = member.src_in + clamped_head * member_speed
        member_out = member.src_out + clamped_tail * member_speed
        journal.update(
            member,
            timeline_start=member.timeline_start + clamped_head,
            src_in=member_in,
            src_out=member_out,
            **_reanchored(member, member_in, member_out),
        )
    _record_operation(
        db,
        sequence,
        kind="trim_clip",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "trim_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return sequence


def _reanchored(clip: Clip, new_in: float, new_out: float) -> dict[str, Any]:
    """修剪之后关键帧还钉在**原来的那一帧画面**上:transform 与音量关键帧按源时间重投影到新的出入点。

    关键帧按片段内进度(0=头、1=尾)存。只改出入点不动它们,等于把整条动画压缩 / 拉伸到新的长度里:
    剪掉后一半,原来在第 5 秒的峰值跑到了第 2.5 秒。和切分同一个做法(_slice_keyframes):剪短时取原动画
    在新端点处的值,拉长时端点钉住(动画在原来的地方结束)。

    淡入淡出不动:它们是相对片段首尾的秒数,修剪之后照样在新的首尾淡 —— 这一点和切分不同
    (切分出的中间段不该在切口淡)。没有可动的,交回原值(改动日志不记没变的字段)。
    """
    transform = _sliced_transform(clip.transform, clip.src_in, clip.src_out, new_in, new_out)
    effects = clip.effects
    if isinstance(effects, dict):
        gain = _slice_keyframes(effects.get("gain_keyframes"), ("gain",), clip.src_in, clip.src_out, new_in, new_out)
        if gain is not None:
            effects = {**effects, "gain_keyframes": gain}
    return {"transform": transform, "effects": effects}


def _source_duration(clip: Clip) -> float | None:
    """素材本身多长(在 media_info 里,不是独立列);图片、文字没有尽头。"""
    if clip.asset is None or clip.asset.kind not in ("video", "audio"):
        return None
    duration = (clip.asset.media_info or {}).get("duration")
    return float(duration) if duration else None


def delete_clip(db: Session, sequence_id: str, op: DeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)

    journal = Journal(db, sequence)
    for one in with_links(db, [clip], linked=op.linked):
        journal.delete(one)
    _record_operation(
        db,
        sequence,
        kind="delete_clip",
        payload={"clip_id": op.clip_id, "changes": journal.entries},
        summary={"operation": "delete_clip", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
    return sequence


@dataclass(frozen=True)
class DeleteClipsBatch:
    """多选后一次删除。整批一条操作,撤销一步全部找回。"""

    clip_ids: tuple[str, ...]
    #: 链接组(视频和它分离出去的音频)一起动;False = 只动这一段(前端的「临时解链」)。见 links.py。
    linked: bool = True
    actor_id: str | None = None


@dataclass(frozen=True)
class RippleDeleteClipsBatch:
    """多选后一次波纹删除(删掉并让同轨后续左移补位)。"""

    clip_ids: tuple[str, ...]
    #: 链接组员一起删、在各自的轨上一起左移(视频和它分离出去的音频)。False = 只删这一段。
    linked: bool = True
    #: 波纹影响所有**未锁定**的轨:把这段时间从整条时间线上拿掉 —— 每条未锁定轨上落在这段时间里的
    #: 都挖掉(盖住一部分的裁掉、跨过去的切开)、后面的一起左移,各轨之间的对位不变。锁定轨原样不动。
    #: False(默认)只动被删片段(和链接组员)自己的轨。
    all_tracks: bool = False
    actor_id: str | None = None


@dataclass(frozen=True)
class RippleDeleteClip:
    """Delete a clip and shift later clips on the same track left to close the gap."""

    clip_id: str
    #: 链接组员一起删、在各自的轨上一起左移(视频和它分离出去的音频)。False = 只删这一段。
    linked: bool = True
    #: 波纹影响所有**未锁定**的轨:把这段时间从整条时间线上拿掉 —— 每条未锁定轨上落在这段时间里的
    #: 都挖掉(盖住一部分的裁掉、跨过去的切开)、后面的一起左移,各轨之间的对位不变。锁定轨原样不动。
    #: False(默认)只动被删片段(和链接组员)自己的轨。
    all_tracks: bool = False
    actor_id: str | None = None


def delete_clips_batch(db: Session, sequence_id: str, op: DeleteClipsBatch) -> Sequence:
    """一次删除多个片段(多选后按 Delete)。

    与 move_clips_batch 同理:循环调 delete_clip 会落成 N 条操作,撤销一次只找回一个,
    删 5 段要按 5 次 ⌘Z。整批记一条,撤销一步全部找回。
    """
    sequence = _require_sequence(db, sequence_id)
    if not op.clip_ids:
        raise SequenceDomainError("No clips to delete")
    # 全部先解析,任一不存在就整批不删——留下删了一半的时间线比直接报错更难收拾。
    clips = [_require_clip(db, sequence_id, clip_id) for clip_id in dict.fromkeys(op.clip_ids)]
    journal = Journal(db, sequence)
    for clip in with_links(db, clips, linked=op.linked):
        journal.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="delete_clips_batch",
        payload={"clip_ids": [clip_id for clip_id in dict.fromkeys(op.clip_ids)], "changes": journal.entries},
        summary={"operation": "delete_clips_batch", "count": len(clips)},
        actor_id=op.actor_id,
    )
    return sequence


def ripple_delete_clips_batch(db: Session, sequence_id: str, op: RippleDeleteClipsBatch) -> Sequence:
    """一次波纹删除多个片段:删掉并让同轨后续片段左移补位,整批一条操作。"""
    sequence = _require_sequence(db, sequence_id)
    if not op.clip_ids:
        raise SequenceDomainError("No clips to delete")
    clips = [_require_clip(db, sequence_id, clip_id) for clip_id in dict.fromkeys(op.clip_ids)]
    journal = Journal(db, sequence)
    _ripple_delete(journal, clips, linked=op.linked, all_tracks=op.all_tracks)
    _record_operation(
        db,
        sequence,
        kind="ripple_delete_clips_batch",
        payload={"clip_ids": [clip.id for clip in clips], "changes": journal.entries},
        summary={"operation": "ripple_delete_clips_batch", "count": len(clips)},
        actor_id=op.actor_id,
    )
    return sequence


def ripple_delete_clip(db: Session, sequence_id: str, op: RippleDeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    journal = Journal(db, sequence)
    _ripple_delete(journal, [clip], linked=op.linked, all_tracks=op.all_tracks)
    _record_operation(
        db,
        sequence,
        kind="ripple_delete_clip",
        payload={"clip_id": op.clip_id, "changes": journal.entries},
        summary={"operation": "ripple_delete_clip", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
    return sequence


def _ripple_delete(journal: Journal, clips: list[Clip], *, linked: bool, all_tracks: bool) -> None:
    """删掉这几段(和它们的链接组员),并把它们占的时间拿掉、后面的左移补位。

    - 默认:每段只在**自己的轨上**拿掉自己那段时间。链接音频和画面同删同移,音画对位不变;
      别的轨不动。
    - all_tracks:这几段时间从**每一条未锁定的轨**上拿掉。区间里的东西都挖掉(这是「从时间线上
      剪掉这段时间」,不只是删一段),所以各轨之间的对位不变;锁定轨原样不动 —— 锁定就是为了这个。
    """
    targets = with_links(journal.db, clips, linked=linked)
    spans = [(clip.timeline_start, clip_end(clip)) for clip in targets]
    if all_tracks:
        tracks = journal.db.scalars(
            select(Track.id).where(Track.sequence_id == journal.sequence.id, Track.locked.is_(False))
        ).all()
        for track_id in tracks:
            remove_time_ranges(journal, track_id, spans)
        return
    ranges: dict[str, list[tuple[float, float]]] = {}
    for clip, span in zip(targets, spans):
        ranges.setdefault(clip.track_id, []).append(span)
    for track_id, track_ranges in ranges.items():
        remove_time_ranges(journal, track_id, track_ranges)


@dataclass(frozen=True)
class DuplicateClips:
    """复制几段片段(复制粘贴、Alt 拖复制)。整批一条操作,撤销一步全部拿掉。

    副本保持彼此的相对位置。`timeline_start` 是整组副本的起点,不给就紧接在原片段组的末尾之后;
    `track_id` 把整组放到那一条轨上(轨道类型要对得上),不给就各回各的原轨。
    """

    clip_ids: tuple[str, ...]
    timeline_start: float | None = None
    track_id: str | None = None
    actor_id: str | None = None


def duplicate_clips(db: Session, sequence_id: str, op: DuplicateClips) -> Sequence:
    """按 id 复制片段,**位置之外的一切照原样**(速度、音量、静音、调色与特效、变换与关键帧、文字、脱机占位)。

    前端此前要自己拼一个 insert_clip 去「复制」:只带得过去素材和出入点,速度、调色、关键帧、花字的文字
    全没了;复制字幕 / 花字(没有素材)则根本插不进去。

    副本**放下**和插入同一条规矩(_land):落点上已有的片段被盖住的部分裁掉,同轨不重叠。链接组:一起复制
    的组员(画和它分离出去的声音)在副本里自成一个新组;只复制了组里一段的,副本不进任何组 —— 进原来的组的话,
    拖原片会把副本一起拖走。原片段只读,源轨锁着也能复制;副本要放进去的轨才过锁定检查。
    """
    sequence = _require_sequence(db, sequence_id)
    ids = tuple(dict.fromkeys(op.clip_ids))
    if not ids:
        raise SequenceDomainError("No clips to duplicate")
    sources: list[Clip] = []
    for clip_id in ids:
        clip = db.get(Clip, clip_id)
        if clip is None or clip.sequence_id != sequence_id:
            raise SequenceNotFound("Clip not found")
        sources.append(clip)
    group_start = min(clip.timeline_start for clip in sources)
    group_end = max(clip_end(clip) for clip in sources)
    start = group_end if op.timeline_start is None else finite_number("timeline_start", op.timeline_start)
    if start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")
    target = _require_target_track(db, sequence_id, op.track_id) if op.track_id else None
    if target is not None and any(clip.track.kind != target.kind for clip in sources):
        raise SequenceDomainError("Target track kind does not match clip track kind")
    copied_groups = Counter(clip.link_group for clip in sources if clip.link_group)
    new_groups = {group: new_link_group() for group, count in copied_groups.items() if count > 1}

    journal = Journal(db, sequence)
    copies: list[Clip] = []
    for source in sources:
        track = target or _require_target_track(db, sequence_id, source.track_id)
        copies.append(journal.create(Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=track.id,
            asset_id=source.asset_id,
            timeline_start=start + (source.timeline_start - group_start),
            src_in=source.src_in,
            src_out=source.src_out,
            # 深拷贝:JSON 列共享同一个 dict 的话,改副本的调色会改到原片。
            **{field: deepcopy(getattr(source, field)) for field in INHERITED_CLIP_FIELDS},
            link_group=new_groups.get(source.link_group),
        )))
    _land(journal, copies, ripple=False)
    _record_operation(
        db,
        sequence,
        kind="duplicate_clips",
        payload={"clip_ids": list(ids), "changes": journal.entries},
        summary={"operation": "duplicate_clips", "count": len(copies)},
        actor_id=op.actor_id,
    )
    return sequence
