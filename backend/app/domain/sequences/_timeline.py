"""时间线操作的共用底座:取序列/片段、校验、记操作日志,以及切分时的字段继承与关键帧重投影。"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, SequenceOperation, SequenceRevision
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound, SequenceRevisionConflict
from app.domain.sequences.offline import offline_snapshot


MIN_CUT_REMAINDER = 0.05

#: 片段倍速的范围。插入时就给倍速(配音、旁白按位置定速)和事后改速是同一条规矩。
SPEED_RANGE = (0.25, 4.0)


def require_speed(speed: float) -> float:
    low, high = SPEED_RANGE
    if not (math.isfinite(speed) and low <= speed <= high):
        raise SequenceDomainError("Speed must be between 0.25 and 4")
    return float(speed)


def _clip_payload(clip: Clip) -> dict[str, Any]:
    """重建这个片段所需的一切。改动日志的 create / delete 条目存的就是它,撤销 / 重做按它原样还原
    (见 undo/rows.restore_clip_row)。

    `asset_snapshot` 是素材**此刻**的名字、类型和时长。撤销可能发生在素材被删掉之后 —— 那时
    asset_id 已经指不到任何东西(外键是 RESTRICT,按它重建当场 IntegrityError,撤销栈卡死在
    这一条上),而素材的名字也已经无处可查。这里先记下,重建时才能还成一个说得出原来是谁的脱机占位。
    """
    payload = {
        "clip_id": clip.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
        "asset_snapshot": offline_snapshot(clip.asset) if clip.asset is not None else None,
    }
    for field in RESTORABLE_CLIP_FIELDS:
        payload[field] = getattr(clip, field)
    return payload


#: Everything about a clip beyond where it sits. Recorded on every operation that may have to
#: rebuild the clip later, because none of it can be recovered from anywhere else — undoing a
#: delete used to hand back a clip at 1x, unity gain, unmuted and ungraded, and a subtitle with
#: no text at all. 早于某个字段记下的老记录由迁移补齐(complete-sequence-operation-clip-records),
#: 重放时一律按键取,不在重放那里猜默认值。
#:
#: `offline_asset` 也在里面:撤销一个脱机片段的删除,还回来的必须仍是那个脱机占位 —— 不然它
#: 和一行没有字的文字片段长得一模一样(两者的 asset_id 都是空)。
RESTORABLE_CLIP_FIELDS = (
    "speed", "gain", "muted", "effects", "transform", "text_override", "link_group", "offline_asset",
)

#: What a piece carved out of a clip inherits. A half is still the same footage at the same
#: speed with the same grade, and half a caption still says what the caption said — rebuilding a
#: piece from position alone reset all of it.
#:
#: 这里曾经还排除过一个 `linked_clip_id`,理由写得很认真(「那配对的是两个具体的行,而切出来
#: 的是新行」)—— 而那个字段**从来没有任何一处写过它**,永远是 null:一个不存在的配对,
#: 被精心地排除在继承之外。已连列带 schema 一起删掉(见迁移 drop-clip-linked-clip-id)。
#:
#: 链接组(link_group)**不**在里面:切出来的每一截和谁链接,由切它的那一步说清楚(左半跟左半、
#: 右半跟右半),不能一律照抄 —— 照抄的话右半段会和链接音频的左半段一组,动一段拖走两段不相干的。
#:
#: `offline_asset` 曾经也不在这里:切开一个脱机片段,两段都成了 asset_id 为空、又没有脱机标记
#: 的东西 —— 导出前的脱机检查认不出它们,成片静默地少一段。
#:
#: Clip 加列时,tests/test_clip_fields_are_carried.py 会要求它出现在这里或 RESTORABLE_CLIP_FIELDS
#: (或者写明为什么都不在)。
INHERITED_CLIP_FIELDS = ("speed", "gain", "muted", "effects", "transform", "text_override", "offline_asset")


def _inherited(clip: Clip) -> dict[str, Any]:
    return {field: getattr(clip, field) for field in INHERITED_CLIP_FIELDS}


_KEYFRAME_PROPS = ("scale", "x", "y", "opacity", "rotation")


def _sample_keyframe_track(points: list[tuple[float, float]], t: float) -> float:
    """分段线性 + 端点保持 —— 与前端 sampleProp、导出端 _kf_sample 同语义。"""
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            factor = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return v0 + (v1 - v0) * factor
    return points[-1][1]


def _slice_keyframes(
    raw: Any, props: tuple[str, ...], orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> list[dict[str, Any]] | None:
    """关键帧列表 → 裁到 [piece_in, piece_out] 后的列表;无可切内容时返回 None。

    关键帧的 t 是**片段内归一化进度**(0=片段头、1=片段尾)。按源时间把动画重投影到新片段的
    进度轴:段首/段尾取原动画在该处的采样值(跨切点连续、接得上),中间落在本段内的关键帧
    按比例重映射。
    """
    if not isinstance(raw, list) or not raw:
        return None
    span = orig_out - orig_in
    piece_span = piece_out - piece_in
    if span <= 0 or piece_span <= 0:
        return None

    sliced: list[dict[str, Any]] = []
    for prop in props:
        points = sorted(
            (float(kf["t"]), float(kf[prop]))
            for kf in raw
            if isinstance(kf, dict)
            and isinstance(kf.get("t"), (int, float))
            and isinstance(kf.get(prop), (int, float))
        )
        if not points:
            continue
        values: dict[float, float] = {}
        # 两端必取:它们承接上一段的结尾 / 下一段的开头。
        for edge_q, edge_src in ((0.0, piece_in), (1.0, piece_out)):
            values[edge_q] = _sample_keyframe_track(points, (edge_src - orig_in) / span)
        for progress, value in points:
            q = (orig_in + progress * span - piece_in) / piece_span
            if 1e-6 < q < 1 - 1e-6:
                values[round(q, 6)] = value
        sliced.extend({"t": q, prop: values[q]} for q in sorted(values))
    return sliced or None


def _sliced_transform(
    transform: Any, orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> Any:
    """画面变换(位置/缩放/旋转/透明度)动画裁到某一段;无关键帧则原样返回。

    不裁的话每段都会从头重播整段动画 —— 用户看到的是"切一刀,画面在切点跳回动画起点"。
    """
    if not isinstance(transform, dict):
        return transform
    sliced = _slice_keyframes(transform.get("keyframes"), _KEYFRAME_PROPS, orig_in, orig_out, piece_in, piece_out)
    return transform if sliced is None else {**transform, "keyframes": sliced}


def _sliced_effects(
    effects: Any, orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> Any:
    """effects 里同样按片段计时的东西,也要跟着切:

    · **音量关键帧**(gain_keyframes)与 transform 关键帧同构(t 为片段内进度)——不裁则每段
      重播整条音量曲线。
    · **淡入淡出**(fade_in/out、video_fade_in/out)是相对片段首尾的绝对秒数。原样复制会让
      每一段都在自己的首尾淡一次 —— 切一刀,切点处画面黑一下、声音断一下(段落切换处的
      "黑屏/断音"多半来源于此)。淡入只属于**首段**、淡出只属于**末段**,中间的切点不该有。
    """
    if not isinstance(effects, dict):
        return effects
    updated = dict(effects)
    sliced = _slice_keyframes(effects.get("gain_keyframes"), ("gain",), orig_in, orig_out, piece_in, piece_out)
    if sliced is not None:
        updated["gain_keyframes"] = sliced
    epsilon = 1e-6
    if piece_in > orig_in + epsilon:  # 不是首段 → 不该再淡入
        for key in ("fade_in", "video_fade_in"):
            if updated.get(key):
                updated[key] = 0.0
    if piece_out < orig_out - epsilon:  # 不是末段 → 不该在切点淡出
        for key in ("fade_out", "video_fade_out"):
            if updated.get(key):
                updated[key] = 0.0
    return updated


def _sliced_inherited(
    inherited: dict[str, Any], orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> dict[str, Any]:
    """切分出的一段应继承的字段:transform / effects 里按片段计时的部分都投影到该段。"""
    return {
        **inherited,
        "transform": _sliced_transform(inherited.get("transform"), orig_in, orig_out, piece_in, piece_out),
        "effects": _sliced_effects(inherited.get("effects"), orig_in, orig_out, piece_in, piece_out),
    }


def timeline_span(clip: Clip) -> float:
    """How long the clip occupies the TIMELINE. src_out - src_in is a duration in SOURCE time;
    at 2x that footage takes half as long to play. Confusing the two put split/cut pieces and
    ripple-shifted followers at the wrong times and let them overwrite their neighbours."""
    return (clip.src_out - clip.src_in) / (clip.speed or 1.0)


def _require_sequence(db: Session, sequence_id: str) -> Sequence:
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise SequenceNotFound("Sequence not found")
    return sequence


def _require_clip(db: Session, sequence_id: str, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None or clip.sequence_id != sequence_id:
        raise SequenceNotFound("Clip not found")
    return clip


def _validate_clip_range(timeline_start: float, src_in: float, src_out: float) -> None:
    """片段在时间线上和素材内的位置。

    **先要求有限,再比大小。** 任何和 NaN 的比较都是 False —— 只靠 `< 0` / `<= src_in`
    这几条,NaN 会把它们全部"满足"而畅通无阻;Infinity 同理(inf < 0 是 False,而
    src_out=inf 比任何 src_in 都大,于是"出点要晚于入点"也成立)。

    放进去的代价不对称:NaN 存下之后,这条时间线序列化出的 `{"timeline_start": NaN}`
    不是合法 JSON,浏览器再也打不开它;src_out=inf 则是一段**无限长**的片段,会一路进到
    渲染计划里。而来源不必是恶意客户端 —— 前端算时间码时一次除以零(时长为 0 的素材、
    缩放为 0)就是 NaN,智能体的 edit_timeline 也直接收这几个数。
    """
    for name, value in (("timeline_start", timeline_start), ("src_in", src_in), ("src_out", src_out)):
        if not math.isfinite(value):
            raise SequenceDomainError(f"{name} must be a finite number")
    if timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")
    if src_in < 0:
        raise SequenceDomainError("src_in must be non-negative")
    if src_out <= src_in:
        raise SequenceDomainError("src_out must be greater than src_in")


#: 操作组(grouping.OperationGroup)挂在会话的 info 上用的键,以及撤销栈上那一条的 kind。
GROUP_SESSION_KEY = "sequence_operation_group"
GROUP_KIND = "operation_group"


def _claim_revision(db: Session, sequence: Sequence) -> tuple[int, int]:
    """序列版本号加一,返回 (改之前, 改之后)。

    版本号自增走**条件 UPDATE**,不是读出来加一再写回去。

    后者是 check-then-act:两个写入方都读到 5,都写 6,于是两条编辑共用一个版本号 —— 而
    版本号是撤销栈排序的依据(revision_after)、也是序列 JSON 缓存的键,两处都会因此错乱。
    让数据库来挑赢家,输的那个改动 0 行,当场知道自己晚了一步。

    这条路径以前基本只有一个人在走,现在不是了:智能体批准一张确认卡就会改时间线,而用户
    同时还在拖片段 —— 两个写入方同时存在已经是常态。
    (和 domain/agent/confirmations.py 的 _claim 同一个手法。)
    """
    before = sequence.revision
    after = before + 1
    claimed = db.execute(
        update(Sequence).where(Sequence.id == sequence.id, Sequence.revision == before).values(revision=after)
    ).rowcount
    if claimed == 0:
        # 409,和「照着过时的一版做」是同一种拒绝(见 concurrency):边界把最新的那一版交回去,而不是一句 422。
        raise SequenceRevisionConflict("seqErr_revisionConflict", base_revision=before)
    return before, after


def _record_operation(
    db: Session,
    sequence: Sequence,
    *,
    kind: str,
    payload: dict[str, Any],
    summary: dict[str, Any],
    actor_id: str | None,
    undo_of: str | None = None,
) -> SequenceOperation:
    #: 在一个操作组里(见 grouping.py,比如一次字幕配音):这一步并进组里那一条,撤销栈上不另记一步。
    #: 撤销 / 重做自己的记账(带 undo_of)和组那一条本身不并。组是挂在会话上的(GROUP_SESSION_KEY),
    #: 这里只认会话上的那个对象,不 import grouping —— 那边要 import 这里的记账,反过来就成了环。
    group = db.info.get(GROUP_SESSION_KEY) if undo_of is None and kind != GROUP_KIND else None
    if group is not None and group.sequence_id == sequence.id:
        return group.record(db, sequence, kind=kind, payload=payload, summary=summary)
    before, after = _claim_revision(db, sequence)
    operation = SequenceOperation(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision_before=before,
            revision_after=after,
            kind=kind,
            payload=payload,
            actor_id=actor_id,
            undo_of=undo_of,
        )
    db.add(operation)
    db.flush()
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=sequence.workspace_id,
        actor_id=actor_id,
        action="sequence.operation",
        subject_type="sequence",
        subject_id=sequence.id,
        summary="编辑了时间线",
        payload={"kind": kind, "revision_before": before, "revision_after": after},
        source_type="sequence_operation",
        source_id=operation.id,
    )
    db.add(
        SequenceRevision(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision=after,
            summary=summary,
        )
    )
    # 每个编辑算子都以记账收尾,**不提交** —— 提交是入口层的事(路由的 Tx、节点、后台任务)。
    # 这里 flush 一次:同一事务里接着组合的下一个算子(apply_edit_operations、配音任务)
    # 查到的就是这一步之后的时间线,冲突也在这一步当场报出来。
    db.flush()
    return operation
