"""操作组:一串编辑在撤销栈上是一步(见 domain/sequences/grouping.py)。

跨会话(配音每一句各自提交)也是同一组;组被撤销之后接着做的另起一组;组里每一步照常加版本号。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Clip, Sequence, SequenceOperation
from app.domain.sequences.grouping import OperationGroup
from app.domain.sequences.history import can_redo, redo, undo
from app.domain.sequences.operations import AddTrack, InsertTextClip, add_track, insert_text_clip
from tests.util import fresh_client


def _sequence(client) -> str:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    return client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]


def _texts(sid: str) -> list[str]:
    with SessionLocal() as db:
        return sorted(clip.text_override for clip in db.scalars(select(Clip).where(Clip.sequence_id == sid)))


def test_跨会话的一组编辑_一次撤销全部退回_一次重做全部回来() -> None:
    client = fresh_client()
    sid = _sequence(client)
    group = OperationGroup(sid, label="test", actor_id=None)
    with SessionLocal() as db, group.collect(db):
        start = db.get(Sequence, sid).revision
        add_track(db, sid, AddTrack(kind="subtitle"))
        track_id = db.get(Sequence, sid).tracks[-1].id
        insert_text_clip(db, sid, InsertTextClip(track_id=track_id, text="一", timeline_start=0, duration=1))
        db.commit()
    with SessionLocal() as db, group.collect(db):
        insert_text_clip(db, sid, InsertTextClip(track_id=track_id, text="二", timeline_start=2, duration=1))
        db.commit()
    with SessionLocal() as db:
        ops = list(db.scalars(select(SequenceOperation).where(SequenceOperation.sequence_id == sid)))
        assert [op.kind for op in ops] == ["operation_group"]
        assert [step["kind"] for step in ops[0].payload["steps"]] == ["add_track", "insert_clip", "insert_clip"]
        assert db.get(Sequence, sid).revision == start + 3, "每一步照常加版本号(序列缓存和冲突判定靠它)"
        assert (ops[0].revision_before, ops[0].revision_after) == (start, start + 3)
        undo(db, sid)
        db.commit()
    assert _texts(sid) == []
    with SessionLocal() as db:
        assert not [t for t in db.get(Sequence, sid).tracks if t.kind == "subtitle"], "建的轨也一起退回"
        redo(db, sid)
        db.commit()
    assert _texts(sid) == ["一", "二"]


def test_组被撤销后接着做的另起一组_重做不会带出没见过的步骤() -> None:
    client = fresh_client()
    sid = _sequence(client)
    group = OperationGroup(sid, label="test", actor_id=None)
    with SessionLocal() as db, group.collect(db):
        add_track(db, sid, AddTrack(kind="subtitle"))
        db.commit()
    with SessionLocal() as db:
        undo(db, sid)
        db.commit()
    with SessionLocal() as db, group.collect(db):
        add_track(db, sid, AddTrack(kind="subtitle"))
        db.commit()
    with SessionLocal() as db:
        groups = list(db.scalars(select(SequenceOperation).where(SequenceOperation.kind == "operation_group")))
        assert len(groups) == 2 and [len(g.payload["steps"]) for g in groups] == [1, 1]
        assert not can_redo(db, sid), "撤销之后又做了新的编辑:重做栈失效"


def test_不在组里的编辑照旧各记一步() -> None:
    client = fresh_client()
    sid = _sequence(client)
    with SessionLocal() as db:
        add_track(db, sid, AddTrack(kind="subtitle"))
        add_track(db, sid, AddTrack(kind="audio"))
        db.commit()
        kinds = [op.kind for op in db.scalars(select(SequenceOperation).where(SequenceOperation.sequence_id == sid))]
    assert kinds == ["add_track", "add_track"]


def test_组里再开一组_外面那组说了算() -> None:
    """「重新生成字幕」自己是一组(删旧 + 铺新);被更大的动作调用时,用户撤销的是那个更大的动作。"""
    client = fresh_client()
    sid = _sequence(client)
    outer = OperationGroup(sid, label="outer", actor_id=None)
    inner = OperationGroup(sid, label="inner", actor_id=None)
    with SessionLocal() as db, outer.collect(db):
        add_track(db, sid, AddTrack(kind="subtitle"))
        with inner.collect(db):
            add_track(db, sid, AddTrack(kind="audio"))
        add_track(db, sid, AddTrack(kind="video"))
        db.commit()
    with SessionLocal() as db:
        [op] = db.scalars(select(SequenceOperation).where(SequenceOperation.sequence_id == sid))
        assert op.payload["label"] == "outer" and len(op.payload["steps"]) == 3
