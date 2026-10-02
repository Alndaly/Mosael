"""把一串编辑收成撤销栈上的**一步**。

**为什么需要它**:有些动作对用户来说是一件事,落到时间线上却是几十上千个算子 —— 一次字幕配音是
「建配音轨 + 每句插一段 + 每句调一次速 + 原声处理」。此前每个算子各记一条操作,配 1000 句就是
2000 多步撤销:配错了音色想退回去,用户得按两千次 ⌘Z,而且中间任何一次都是「半配好」的状态。

**怎么收**:组里每一步照常改时间线、照常给序列加版本号(版本号是序列缓存和冲突判定的依据,
不能少),但不再各自往撤销栈里记一条 —— 第一步记一条 `operation_group`,之后每一步把自己的
`{kind, payload}` 追加进它的 `steps`。撤销 / 重做按 steps 逆序 / 正序回放各自登记的逆操作与正向
操作(见 undo/group.py),所以**组里能放什么**不需要另写一份清单:任何登记过撤销的算子都行。

**跨事务**:配音每一句各自提交(配好的那几句不因后面哪一句出错而没了),所以组是一个由调用方
攥着的对象,每个会话里 `with group.collect(db):` 接上它。中途断了的话,已经记下的那一条组操作
照样在栈上,一步就能撤掉断之前做的全部。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Sequence, SequenceOperation, SequenceRevision
from app.domain.sequences._timeline import GROUP_KIND, GROUP_SESSION_KEY, _claim_revision, _record_operation

#: 会话上挂着「这个会话里的编辑记进哪个组」的那个键(_timeline 认它,见 _record_operation)。
_SESSION_KEY = GROUP_SESSION_KEY


class OperationGroup:
    """一组编辑。`label` 说这一组是什么(`subtitle_dub`……),记在操作里,给人和日志看。"""

    def __init__(self, sequence_id: str, *, label: str, actor_id: str | None) -> None:
        self.sequence_id = sequence_id
        self.label = label
        self.actor_id = actor_id
        #: 撤销栈上那一条的 id。第一步落地时才建 —— 一步都没做成的组不该在栈上留一条空操作。
        self.operation_id: str | None = None

    @contextmanager
    def collect(self, db: Session) -> Iterator[OperationGroup]:
        """这个会话里对 `sequence_id` 的编辑都记进这个组。

        已经在别的组里(对同一条序列)时,**外面那个组说了算**:这一组的步骤并进外面那一步 —— 比如「重新生成字幕」
        自己是一组(删旧 + 插新),被一次更大的动作调用时,用户要撤销的是那次更大的动作。
        """
        outer = active_group(db, self.sequence_id)
        if outer is not None and outer is not self:
            yield outer
            return
        previous = db.info.get(_SESSION_KEY)
        db.info[_SESSION_KEY] = self
        try:
            yield self
        finally:
            if previous is None:
                db.info.pop(_SESSION_KEY, None)
            else:
                db.info[_SESSION_KEY] = previous

    def record(
        self, db: Session, sequence: Sequence, *, kind: str, payload: dict[str, Any], summary: dict[str, Any]
    ) -> SequenceOperation:
        """组里的一步落地:版本号照常加一,操作追加进组那一条的 steps。"""
        step = {"kind": kind, "payload": payload}
        operation = db.get(SequenceOperation, self.operation_id) if self.operation_id else None
        #: 已经被撤销过的组不再往里加:用户在配音中途按了 ⌘Z,撤掉的是到那一刻为止的那一组;
        #: 后面的步骤接着记进去的话,重做时会把他没见过的步骤一起"重做"出来。另起一组。
        if operation is None or operation.reverted:
            created = _open_group(db, sequence, label=self.label, step=step, summary=summary, actor_id=self.actor_id)
            self.operation_id = created.id
            return created
        before, after = _claim_revision(db, sequence)
        # 整个 dict 换掉而不是原地 append:JSON 列只认赋值才算改过。
        operation.payload = {**operation.payload, "steps": [*operation.payload.get("steps", []), step]}
        operation.revision_after = after
        db.add(
            SequenceRevision(
                workspace_id=sequence.workspace_id,
                sequence_id=sequence.id,
                revision=after,
                summary={"operation": GROUP_KIND, "label": self.label, "step": summary, "revision_before": before},
            )
        )
        db.flush()
        return operation


def _open_group(
    db: Session, sequence: Sequence, *, label: str, step: dict[str, Any], summary: dict[str, Any], actor_id: str | None
) -> SequenceOperation:
    """撤销栈上那一条:组里第一步落地时记下。之后的步骤追加进它的 steps(见 OperationGroup.record)。"""
    return _record_operation(
        db,
        sequence,
        kind="operation_group",
        payload={"label": label, "steps": [step]},
        summary={"operation": GROUP_KIND, "label": label, "first": summary},
        actor_id=actor_id,
    )


def active_group(db: Session, sequence_id: str) -> OperationGroup | None:
    """这个会话里对这条序列的编辑该记进哪个组;不在组里就是 None。"""
    group = db.info.get(_SESSION_KEY)
    if isinstance(group, OperationGroup) and group.sequence_id == sequence_id:
        return group
    return None
