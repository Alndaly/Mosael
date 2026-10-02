"""升级前记下的片段级编辑,迁移成改动日志之后照样撤得回、重做得了:`_migrate_clip_edits_keep_a_change_journal`。

撤销那一侧现在只认 `changes`(sequences/journal.py)。库里已有的记录各是各的老形状 —— 移动带着让位时
右移的片段和落点切开的那一刀、分离音频带着新建的那条轨、按文字剪是「原片段 + 新片段」。每种都按
升级前的样子造一条,迁移之后按 ⌘Z / ⇧⌘Z,时间线要回到它记下的那两个状态。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import Clip, Sequence, Track
from app.domain.sequences._timeline import _record_operation
from tests.util import create_asset, fresh_client


def _setup(client):
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    asset = create_asset(client, {"workspace_id": ws, "project_id": project, "kind": "video", "name": "V",
                                  "file_key": "media/v.mp4", "media_info": {"duration": 60}})["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    video = next(t for t in sequence["tracks"] if t["kind"] == "video")["id"]
    return ws, asset, sequence["id"], video


def _place(db, ws, sequence_id, track_id, asset, clip_id, start, src_in, src_out, **extra):
    db.add(Clip(id=clip_id, workspace_id=ws, sequence_id=sequence_id, track_id=track_id, asset_id=asset,
                timeline_start=start, src_in=src_in, src_out=src_out, **extra))


def _old_operation(sequence_id: str, kind: str, payload: dict) -> None:
    with SessionLocal() as db:
        _record_operation(db, db.get(Sequence, sequence_id), kind=kind, payload=payload, summary={}, actor_id=None)
        db.commit()


def _state(client, sequence_id: str) -> dict:
    body = client.get(f"/api/sequences/{sequence_id}").json()
    return {
        track["name"]: sorted((c["id"], c["timeline_start"], c["src_in"], c["src_out"], c["muted"]) for c in track["clips"])
        for track in body["tracks"]
    }


def _payloads(sequence_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT payload FROM sequence_operations WHERE sequence_id = :s AND kind NOT IN ('undo', 'redo')"),
            {"s": sequence_id},
        ).scalars()
        return [json.loads(raw) if isinstance(raw, str) else raw for raw in rows]


def test_插入模式的移动_让位和落点那一刀都撤得回() -> None:
    from app.db.migrations import _migrate_clip_edits_keep_a_change_journal, _migrate_sequence_operation_clip_records_are_complete

    client = fresh_client()
    ws, asset, sid, video = _setup(client)
    # 做之前:A[0,5) B[6,8) C[10,12)。插入模式把 C 移到 3:A 在 3 切开,尾段 T 和 B 右移 2 秒。
    with SessionLocal() as db:
        _place(db, ws, sid, video, asset, "A", 0, 0, 3)
        _place(db, ws, sid, video, asset, "T", 5, 3, 5)
        _place(db, ws, sid, video, asset, "B", 8, 20, 22)
        _place(db, ws, sid, video, asset, "C", 3, 30, 32)
        db.commit()
    tail = {"clip_id": "T", "track_id": video, "asset_id": asset, "timeline_start": 3, "src_in": 3, "src_out": 5}
    _old_operation(sid, "move_clip", {
        "clip_id": "C", "track_id": video, "timeline_start": 3, "previous_timeline_start": 10,
        "previous_track_id": video,
        "shifted": [{"clip_id": "T", "previous_timeline_start": 3, "timeline_start": 5},
                    {"clip_id": "B", "previous_timeline_start": 6, "timeline_start": 8}],
        "split": {"clip_id": "A", "previous_src_out": 5, "tail": tail},
    })
    after = _state(client, sid)

    _migrate_clip_edits_keep_a_change_journal()
    # 启动时紧跟着的那一步:转出来的片段记录补齐撤销要按键取的字段(素材快照、脱机占位、链接组)。
    _migrate_sequence_operation_clip_records_are_complete()
    once = _payloads(sid)
    _migrate_clip_edits_keep_a_change_journal()
    # 启动时紧跟着的那一步:转出来的片段记录补齐撤销要按键取的字段(素材快照、脱机占位、链接组)。
    _migrate_sequence_operation_clip_records_are_complete()
    assert _payloads(sid) == once, "再跑一次不该再动"
    assert all(set(payload) == {"changes"} for payload in once)

    undone = client.post(f"/api/sequences/{sid}/undo")
    assert undone.status_code == 200, undone.text
    assert _state(client, sid)["V1"] == [
        ("A", 0, 0, 5, False), ("B", 6, 20, 22, False), ("C", 10, 30, 32, False)]
    assert client.post(f"/api/sequences/{sid}/redo").status_code == 200
    assert _state(client, sid) == after


def test_分离音频_新建的那条轨和静音一起撤掉() -> None:
    from app.db.migrations import _migrate_clip_edits_keep_a_change_journal, _migrate_sequence_operation_clip_records_are_complete

    client = fresh_client()
    ws, asset, sid, video = _setup(client)
    with SessionLocal() as db:
        _place(db, ws, sid, video, asset, "V", 0, 0, 4, muted=True, speed=2.0)
        db.add(Track(id="A9", sequence_id=sid, kind="audio", name="A9", position=9))
        db.flush()
        _place(db, ws, sid, "A9", asset, "AU", 0, 0, 4, speed=2.0)
        db.commit()
    _old_operation(sid, "detach_clip_audio", {
        "video_clip_id": "V", "video_muted_prev": False,
        "created_track": {"id": "A9", "name": "A9", "position": 9},
        "audio_clip": {"id": "AU", "track_id": "A9", "asset_id": asset, "timeline_start": 0, "src_in": 0,
                       "src_out": 4, "speed": 2.0, "gain": 1.0},
    })
    after = _state(client, sid)
    _migrate_clip_edits_keep_a_change_journal()
    # 启动时紧跟着的那一步:转出来的片段记录补齐撤销要按键取的字段(素材快照、脱机占位、链接组)。
    _migrate_sequence_operation_clip_records_are_complete()

    assert client.post(f"/api/sequences/{sid}/undo").status_code == 200
    state = _state(client, sid)
    assert "A9" not in state, "为放分离出的音频新建的轨跟着撤掉"
    assert state["V1"] == [("V", 0, 0, 4, False)]
    assert client.post(f"/api/sequences/{sid}/redo").status_code == 200
    assert _state(client, sid) == after


def test_按文字剪与波纹删除_原片段和左移的都还回来() -> None:
    from app.db.migrations import _migrate_clip_edits_keep_a_change_journal, _migrate_sequence_operation_clip_records_are_complete

    client = fresh_client()
    ws, asset, sid, video = _setup(client)
    # 先一步按文字剪:X[0,10) 剪掉源 2–4 → L[0,2) R[2,8);再一步波纹删除 R,后面的 Y 从 8 左移到 2。
    with SessionLocal() as db:
        _place(db, ws, sid, video, asset, "L", 0, 0, 2)
        _place(db, ws, sid, video, asset, "Y", 2, 40, 41)
        db.commit()
    piece = {"track_id": video, "asset_id": asset, "speed": 1.0, "gain": 1.0, "muted": False, "effects": {},
             "transform": {}, "text_override": None}
    original = {**piece, "clip_id": "X", "timeline_start": 0, "src_in": 0, "src_out": 10}
    left = {**piece, "clip_id": "L", "timeline_start": 0, "src_in": 0, "src_out": 2}
    right = {**piece, "clip_id": "R", "timeline_start": 2, "src_in": 4, "src_out": 10}
    _old_operation(sid, "apply_transcript_edits_batch", {"edits": [{"clip_id": "X", "original": original,
                                                                    "created": [left, right]}]})
    _old_operation(sid, "ripple_delete_clips_batch", {"entries": [{
        "original": right, "shifted": [{"clip_id": "Y", "previous_timeline_start": 8, "timeline_start": 2}]}]})
    _migrate_clip_edits_keep_a_change_journal()
    # 启动时紧跟着的那一步:转出来的片段记录补齐撤销要按键取的字段(素材快照、脱机占位、链接组)。
    _migrate_sequence_operation_clip_records_are_complete()

    assert client.post(f"/api/sequences/{sid}/undo").status_code == 200
    assert _state(client, sid)["V1"] == [("L", 0, 0, 2, False), ("R", 2, 4, 10, False), ("Y", 8, 40, 41, False)]
    assert client.post(f"/api/sequences/{sid}/undo").status_code == 200
    assert _state(client, sid)["V1"] == [("X", 0, 0, 10, False), ("Y", 8, 40, 41, False)]
    assert client.post(f"/api/sequences/{sid}/redo").status_code == 200
    assert client.post(f"/api/sequences/{sid}/redo").status_code == 200
    assert _state(client, sid)["V1"] == [("L", 0, 0, 2, False), ("Y", 2, 40, 41, False)]
