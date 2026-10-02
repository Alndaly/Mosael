"""同一条轨上的片段不重叠 —— 时间线的结构不变量,和守住它的几个原语。

预览与导出都靠它(media/scene.py 的 active_clip_on_track:「同一轨上的片段不重叠,所以 t 时刻至多
一个」)。此前没有任何算子守它:非波纹的插入 / 移动、修剪拉进邻居、慢放,都能让两段叠在一起,
而叠着的结果是**先开始的那段赢**、后放上去的那段被它盖住看不见 —— 用户把一段拖到另一段上,
看到的是「拖了没反应」。

所以放下一段(插入、移动)是**覆盖**,和 Premiere 的 overwrite 一样:落点盖住的那部分,
被盖住的片段切掉或裁掉;两头都露出来就切成两段。波纹(插入模式)则先把后面的推开再放。

这里的原语都只经由改动日志(journal.Journal)写片段,所以撤销能把被裁、被切、被删的部分原样还回来。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip
from app.domain.sequences._timeline import (
    _inherited,
    _sliced_effects,
    _sliced_transform,
    timeline_span,
    too_short,
)
from app.domain.sequences.journal import Journal

#: 时间比较的容差(秒)。浮点算出来的边界差 1e-9 不算重叠,也不算「留了缝」。
EPS = 1e-6


def clip_end(clip: Clip) -> float:
    return clip.timeline_start + timeline_span(clip)


def clips_on_track(db: Session, track_id: str) -> list[Clip]:
    """查库而不是读 `track.clips`:同一次编辑里刚删、刚建的片段,关系集合未必跟得上。"""
    return list(db.scalars(select(Clip).where(Clip.track_id == track_id).order_by(Clip.timeline_start)))


def overlaps(clip: Clip, start: float, end: float) -> bool:
    return clip.timeline_start < end - EPS and clip_end(clip) > start + EPS


def piece_appearance(
    transform: Any, effects: Any, orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> dict[str, Any]:
    """一个片段裁剩 / 切出的那一截,它的画面变换与特效:关键帧和淡入淡出按这一截自己的源区间重投影
    (和切分同一套)。覆盖时裁别的片段、迁移规整老数据时裁叠着的片段,用的都是它。"""
    return {
        "transform": _sliced_transform(transform, orig_in, orig_out, piece_in, piece_out),
        "effects": _sliced_effects(effects, orig_in, orig_out, piece_in, piece_out),
    }


def carve(journal: Journal, clip: Clip, start: float, end: float) -> Clip | None:
    """从一个片段上挖掉时间线区间 [start, end) 覆盖的部分。

    - 整段落在区间里:删掉;
    - 只露出头:裁掉尾巴;只露出尾:裁掉头(片段从 end 开始);
    - 两头都露出来:切成两段,左段留原 id,右段是新片段、从 end 开始。

    裁剩的一截短于最小余量就不留(一帧都不到的碎片只会让人点不中、看不见)。
    关键帧与淡入淡出按每一截自己的源区间重投影,和切分同一套(_sliced_transform / _sliced_effects)。
    返回切出来的右段;没有切就是 None。
    """
    if not overlaps(clip, start, end):
        return None
    speed = clip.speed or 1.0
    clip_start, clip_stop = clip.timeline_start, clip_end(clip)
    orig_in, orig_out = clip.src_in, clip.src_out
    left_out = orig_in + max(0.0, start - clip_start) * speed
    right_in = orig_in + max(0.0, end - clip_start) * speed
    keep_left = start > clip_start + EPS and not too_short(left_out - orig_in)
    keep_right = end < clip_stop - EPS and not too_short(orig_out - right_in)

    def piece(piece_in: float, piece_out: float) -> dict[str, Any]:
        return piece_appearance(clip.transform, clip.effects, orig_in, orig_out, piece_in, piece_out)

    if not keep_left and not keep_right:
        journal.delete(clip)
        return None
    right: Clip | None = None
    if keep_left and keep_right:
        right = journal.create(
            Clip(
                workspace_id=clip.workspace_id,
                sequence_id=clip.sequence_id,
                track_id=clip.track_id,
                asset_id=clip.asset_id,
                **{**_inherited(clip), **piece(right_in, orig_out)},
                timeline_start=end,
                src_in=right_in,
                src_out=orig_out,
                # 链接组员在同一刻被切开时(按文字剪、跨轨波纹删除),右半段们进同一个新组。
                link_group=journal.split_group(clip.link_group, at=end),
            )
        )
    if keep_left:
        journal.update(clip, src_out=left_out, **piece(orig_in, left_out))
    else:
        journal.update(clip, timeline_start=end, src_in=right_in, **piece(right_in, orig_out))
    return right


def clear_range(journal: Journal, track_id: str, start: float, end: float, *, keep: Iterable[str]) -> None:
    """覆盖:把这条轨上 [start, end) 让给 `keep` 里的片段,别的片段被盖住的部分挖掉。"""
    kept = set(keep)
    for other in clips_on_track(journal.db, track_id):
        if other.id not in kept:
            carve(journal, other, start, end)


def shift(journal: Journal, clips: Iterable[Clip], delta: float) -> None:
    for clip in clips:
        journal.update(clip, timeline_start=max(0.0, clip.timeline_start + delta))


def remove_time_ranges(
    journal: Journal, track_id: str, ranges: Iterable[tuple[float, float]], *, exclude: Iterable[str] = ()
) -> None:
    """把几段时间从这条轨上拿掉:区间里的挖掉,后面的左移补上(波纹删除、按文字剪)。

    **从后往前**:先拿掉靠前的一段,后面的区间就全跟着错位了。
    """
    excluded = set(exclude)
    for start, end in sorted(_merged(ranges), reverse=True):
        for other in clips_on_track(journal.db, track_id):
            if other.id in excluded:
                continue
            if _is_text(other) and other.timeline_start < start - EPS and clip_end(other) > end + EPS:
                # 跨着切口的字幕 / 花字缩短就好:切成两条一模一样的字,在成片里看着是同一条,在时间线上却是两条。
                journal.update(other, src_out=other.src_out - (end - start) * (other.speed or 1.0))
                continue
            carve(journal, other, start, end)
        followers = [
            other
            for other in clips_on_track(journal.db, track_id)
            if other.id not in excluded and other.timeline_start >= end - EPS
        ]
        shift(journal, followers, -(end - start))


def _is_text(clip: Clip) -> bool:
    """文字片段(字幕、花字):没有素材,也不是素材被删后的脱机占位。它的「源区间」只是一个时长。"""
    return clip.asset_id is None and not clip.offline_asset


def make_room(journal: Journal, track_id: str, start: float, end: float, *, exclude: Iterable[str]) -> None:
    """插入编辑让位(插入模式的插入 / 移动):

    ① 落点插进某个片段的身体里,先在落点把它切开 —— 尾段算作落点之后的片段,跟着一起让;
       切点贴着它的头(剩下的左段太短),整段跟着让;贴着它的尾,把那一点尾巴裁掉。
    ② 落点及之后的片段整体右移**实际重叠量**,彼此的间距保留;没碰上就不动,
       免得轻轻一拖整条时间线炸开。
    """
    excluded = set(exclude)
    others = [clip for clip in clips_on_track(journal.db, track_id) if clip.id not in excluded]
    straddler = next(
        (clip for clip in others if clip.timeline_start < start - EPS and clip_end(clip) > start + EPS), None
    )
    pushed_along: list[Clip] = []
    if straddler is not None:
        if too_short((start - straddler.timeline_start) * (straddler.speed or 1.0)):
            pushed_along.append(straddler)
        else:
            # 零宽的区间 = 在落点切一刀;尾巴太短时 carve 自己会把它裁掉而不是切出一段碎片。
            carve(journal, straddler, start, start)
    downstream = pushed_along + [
        clip
        for clip in clips_on_track(journal.db, track_id)
        if clip.id not in excluded and clip.timeline_start >= start - EPS
    ]
    if not downstream:
        return
    room = end - min(clip.timeline_start for clip in downstream)
    if room > EPS:
        shift(journal, downstream, room)


def neighbours(db: Session, clip: Clip, *, exclude: Iterable[str] = ()) -> tuple[float, float]:
    """同轨上一段的终点和下一段的起点(没有就是 0 和 ∞)。按片段**现在**的位置分前后。"""
    excluded = {clip.id, *exclude}
    previous_end, next_start = 0.0, float("inf")
    for other in clips_on_track(db, clip.track_id):
        if other.id in excluded:
            continue
        if other.timeline_start < clip.timeline_start:
            previous_end = max(previous_end, clip_end(other))
        else:
            next_start = min(next_start, other.timeline_start)
    return previous_end, next_start


def _merged(ranges: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted((float(a), float(b)) for a, b in ranges if b > a):
        if merged and start <= merged[-1][1] + EPS:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]
