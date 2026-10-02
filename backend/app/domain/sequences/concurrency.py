"""时间线的并发协议:一次编辑说清「我是在第几版上做的」,服务端决定还能不能照做。

同一条时间线上同时有好几个写入方是常态:剪辑页里拖片段的人、批准了一张确认卡的智能体、画板上的时间线格、
同一工作区里的另一个人。此前每个写入方都只管「在现在这一版上做」,看到的是第 5 版、做的时候已经是第 7 版,
它也照做 —— 拖到的那个落点、切的那一刀,算的是自己屏幕上那份已经过时的时间线。

协议:

- 编辑请求带 `base_revision`(客户端看到的那一版)。和现在一致就照做。
- 落后了:看中间那几步和这一步**能不能交换**。能 —— 两步各改各的、谁先谁后结果一样 —— 就在最新一版上照做
  (这就是「重放」:算子本来就是按现状算的);不能,拒(409),附上最新的那一版和**是谁改的**。
- 能交换的判断刻意保守,只认一种情形:至少一方**不依赖坐标**(只改某个片段 / 轨道 / 序列自己的一项属性,
  不读也不改任何片段在时间线上的位置和长短),而且两步碰的东西(片段、轨道)没有交集。两边都在挪位置、
  切片段的,一律当冲突。
- 「碰的东西」按**实际改到的**算,不按请求点名的算:挪一段会带上它的链接组员,放下会覆盖切掉邻居,
  跨轨波纹会挪动别的轨 —— 这些都记在那一步的改动日志里(sequences/journal),做完再比。

撤销同一套判断:撤掉某一步 = 对它涉及的那些东西做一次它的逆操作,这一步之后别人做过的每一步都得和它能交换。
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from typing import Any, Callable, Iterable, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.db.models import Sequence, SequenceOperation, User
from app.domain.sequences._timeline import _require_sequence
from app.domain.sequences.clip_properties import SetClipEffects, SetClipGain, SetClipTransform
from app.domain.sequences.errors import SequenceDomainError, SequenceRevisionConflict
from app.domain.sequences.media_swap import ReplaceClipMedia
from app.domain.sequences.text import SetClipText, SetClipTextsBatch, SetSubtitleStyle
from app.domain.sequences.tracks import SetTrackState

#: 不依赖坐标的编辑 → 它记进操作日志时的 kind。只在这张表里的才算;新加的操作默认**依赖坐标**,
#: 宁可多拒一次让人再做一遍,也不能在一份过时的时间线上替人做决定。
#: 变速不在里面:它改片段占多长,后面的片段跟着变了处境。
COORDINATE_FREE_REQUESTS: dict[type, str] = {
    SetClipGain: "set_clip_gain",
    SetClipEffects: "set_clip_effect",
    SetClipTransform: "set_clip_transform",
    SetClipText: "set_clip_text",
    SetClipTextsBatch: "set_clip_texts_batch",
    SetTrackState: "set_track_state",
    SetSubtitleStyle: "set_subtitle_style",
    #: 换素材:片段的位置和长短都不动(media_swap 先验过新素材覆盖得了出点)。
    ReplaceClipMedia: "replace_clip_media",
}
COORDINATE_FREE_KINDS = frozenset(COORDINATE_FREE_REQUESTS.values())

T = TypeVar("T")

#: 字幕样式是**整条序列**的一项属性,不属于哪个片段或轨道 —— 两次改样式要撞上,得有个共同的「东西」。
_SUBTITLE_STYLE = "@subtitle_style"

#: 只是「用到了哪份素材」,不是这一步改动的东西:两段片段用同一份素材,互不相干。
_NOT_TOUCHED = frozenset({"asset_id", "audio_asset_id", "actor_id"})


@dataclass(frozen=True)
class Footprint:
    """一步编辑碰了什么:涉及的片段 / 轨道 id,以及它依不依赖坐标。"""

    coordinate_free: bool
    ids: frozenset[str]

    def touching(self, *more: Iterable[str]) -> "Footprint":
        """再加上做的时候才知道碰到的那些(改动日志里的片段 / 轨道)。"""
        ids = set(self.ids)
        for some in more:
            ids.update(some)
        return Footprint(coordinate_free=self.coordinate_free, ids=frozenset(ids))

    def clashes_with(self, other: "Footprint") -> bool:
        if not (self.coordinate_free or other.coordinate_free):
            return True
        return bool(self.ids & other.ids)


#: 依赖坐标、不点名任何东西的一步(接素材到末尾这类):和任何依赖坐标的一步都冲突,和属性修改都不冲突。
POSITIONAL = Footprint(coordinate_free=False, ids=frozenset())


def footprint_of_request(op: Any) -> Footprint:
    """一个还没做的编辑请求(序列域的那些 dataclass)碰了什么。"""
    if isinstance(op, SetClipTextsBatch):
        ids = frozenset(clip_id for clip_id, _text in op.texts)
    elif isinstance(op, SetSubtitleStyle):
        ids = frozenset({_SUBTITLE_STYLE})
    else:
        ids = frozenset(_request_ids(op))
    return Footprint(coordinate_free=type(op) in COORDINATE_FREE_REQUESTS, ids=ids)


def _request_ids(value: Any) -> Iterable[str]:
    """请求里点名的片段 / 轨道:`*_id`、`*_ids` 字段,连同 moves / cuts 这类嵌套的条目。"""
    if is_dataclass(value):
        for field in fields(value):
            item = getattr(value, field.name)
            if field.name in _NOT_TOUCHED:
                continue
            if field.name.endswith("_id") and isinstance(item, str):
                yield item
            elif field.name.endswith("_ids") and isinstance(item, (list, tuple)):
                yield from (one for one in item if isinstance(one, str))
            elif isinstance(item, (list, tuple)):
                for one in item:
                    yield from _request_ids(one)


def footprint_of_operation(db: Session, operation: SequenceOperation) -> Footprint:
    """操作日志里已经做了的一步碰了什么。撤销 / 重做的记账按**被撤 / 被重做的那一步**算 —— 撤掉一次移动,
    动的还是那个片段。"""
    if operation.kind in ("undo", "redo"):
        original_id = (operation.payload or {}).get("undo_of") or (operation.payload or {}).get("redo_of")
        original = db.get(SequenceOperation, original_id) if original_id else None
        if original is None:
            return POSITIONAL
        operation = original
    ids = set(_payload_ids(operation.payload))
    if operation.kind == "set_subtitle_style":
        ids.add(_SUBTITLE_STYLE)
    return Footprint(coordinate_free=operation.kind in COORDINATE_FREE_KINDS, ids=frozenset(ids))


def _payload_ids(value: Any, key: str = "") -> Iterable[str]:
    """操作记录里出现过的片段 / 轨道 id:键叫 `id` 或以 `_id` / `_ids` 结尾的那些(切出来的新片段、
    被让位挪动的邻居都在里面)。"""
    if isinstance(value, dict):
        for name, item in value.items():
            yield from _payload_ids(item, name)
    elif isinstance(value, list):
        for item in value:
            yield from _payload_ids(item, key)
    elif isinstance(value, str) and key not in _NOT_TOUCHED and (key == "id" or key.endswith(("_id", "_ids"))):
        yield value


def effective_after(db: Session, sequence_id: str, revision: int) -> list[SequenceOperation]:
    """第 `revision` 版之后**还算数**的那些步骤。

    做了又撤掉的一步不算:它和撤掉它的那条记账都在这段里,两者相抵,时间线上没有留下任何东西。不剔掉的话,
    自己刚撤销过一次挪动,再撤更早的一步就会被「之后有人挪过片段」挡住 —— 挡它的正是已经不存在的那一下。
    """
    rows = list(
        db.scalars(
            select(SequenceOperation)
            .where(SequenceOperation.sequence_id == sequence_id, SequenceOperation.revision_after > revision)
            .order_by(SequenceOperation.revision_after)
        )
    )
    cancelled = {row.id for row in rows if row.reverted and row.kind not in ("undo", "redo")}
    return [
        row
        for row in rows
        if not row.reverted and not (row.kind == "undo" and row.undo_of in cancelled)
    ]


def clashing(db: Session, footprint: Footprint, later: list[SequenceOperation]) -> list[SequenceOperation]:
    return [operation for operation in later if footprint.clashes_with(footprint_of_operation(db, operation))]


def run_on_base(
    db: Session,
    sequence: Sequence,
    run: Callable[[], T],
    *,
    base_revision: int | None,
    footprint: Footprint,
    actor_id: str | None,
) -> T:
    """这一步是照着第 `base_revision` 版做的。现在已经不是那一版了:中间每一步都和它能交换就照做,否则拒。

    **判断在做完之后**:一步编辑碰了谁,很多时候要做了才知道 —— 链接组员跟着动、放下时覆盖切掉的邻居、
    波纹推开的后续片段、跨轨波纹挖掉的别的轨。这些都记在它自己的改动日志里(sequences/journal),
    所以先在最新一版上做,再拿「请求点名的 + 日志里改到的」去和中间那几步比;对不上就抛,入口回滚整个事务,
    这一步等于没做。`footprint` 是请求本身就知道的那部分(点名的片段 / 轨道、依不依赖坐标)。

    `base_revision` 为 None 是调用方没说(工作流节点、领域内部的组合)—— 照现状做,和以前一样。
    """
    if base_revision is None or base_revision == sequence.revision:
        return run()
    if base_revision > sequence.revision:
        # 客户端说它看到的是一版还不存在的时间线:不是落后,是对不上。没有可比的中间步骤,只能拒。
        raise conflict(db, sequence, base_revision, [], actor_id=actor_id)
    later = effective_after(db, sequence.id, base_revision)
    before = sequence.revision
    try:
        result = run()
    except SequenceRevisionConflict:
        raise
    except SequenceDomainError:
        # 照最新一版做不下去(要动的那段被别人删了、切了):中间那几步碰过它的话,该说的是「谁改了」并交回最新的一版,
        # 而不是一句「片段不存在」—— 后者让人以为是自己点错了。
        blocking = clashing(db, footprint, later)
        if blocking:
            raise conflict(db, sequence, base_revision, blocking, actor_id=actor_id) from None
        raise
    done = db.scalars(
        select(SequenceOperation).where(
            SequenceOperation.sequence_id == sequence.id, SequenceOperation.revision_after > before
        )
    )
    touched = footprint.touching(*(_payload_ids(operation.payload) for operation in done))
    blocking = clashing(db, touched, later)
    if blocking:
        raise conflict(db, sequence, base_revision, blocking, actor_id=actor_id)
    return result


def conflict(
    db: Session,
    sequence: Sequence,
    base_revision: int | None,
    operations: list[SequenceOperation],
    *,
    actor_id: str | None,
    key: str = "seqErr_changedBy",
) -> SequenceRevisionConflict:
    """拒的时候说清是谁改的。"""
    return SequenceRevisionConflict(
        key,
        base_revision=base_revision,
        current_revision=sequence.revision,
        who=who_changed(db, operations, actor_id=actor_id),
    )


def who_changed(db: Session, operations: list[SequenceOperation], *, actor_id: str | None) -> list[Any]:
    """改了这几步的人,按先后、去重。自己(另一个窗口、自己批准的智能体卡)说「你」;没记下是谁的说「有人」。"""
    names: list[Any] = []
    seen: set[str | None] = set()
    for operation in operations:
        if operation.actor_id in seen:
            continue
        seen.add(operation.actor_id)
        if operation.actor_id is None:
            names.append(fragment("seqWho_someone"))
        elif operation.actor_id == actor_id:
            names.append(fragment("seqWho_you"))
        else:
            user = db.get(User, operation.actor_id)
            names.append((user.display_name or user.username) if user is not None else fragment("seqWho_someone"))
    return names or [fragment("seqWho_someone")]


def apply_on_base(
    db: Session,
    sequence_id: str,
    handler: Callable[[Session, str, Any], Sequence],
    op: Any,
    *,
    base_revision: int | None,
    actor_id: str | None,
) -> Sequence:
    """一次编辑请求的统一形状:记下是谁做的,照着它看到的那一版判断还能不能做,能就做。

    `actor_id` 由入口给(路由里是登录的那个人),**不从请求体里来** —— 撤销「只撤我自己的」和冲突时「是谁改的」
    都靠它,让请求自己报就能冒充别人。
    """
    sequence = _require_sequence(db, sequence_id)
    op = replace(op, actor_id=actor_id)
    return run_on_base(
        db,
        sequence,
        lambda: handler(db, sequence_id, op),
        base_revision=base_revision,
        footprint=footprint_of_request(op),
        actor_id=actor_id,
    )
