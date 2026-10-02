"""素材删掉之后,撤销栈还走得动。

删素材时,时间线上还在的片段转成脱机占位;而**撤销历史里**的片段记录还指着那个素材。按旧
asset_id 重建一行,撞上 RESTRICT 外键 → IntegrityError → 500;撤销是按顺序往回走的,这一条撤不掉,
它前面的全部历史也就永远撤不到了。现在重建的是一个脱机占位,名字取自记录那一步时留下的素材快照。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.migrations import _migrate_sequence_operation_clip_records_are_complete, migration_plan
from app.db.models import Clip, SequenceOperation
from tests.util import fresh_client, insert_asset


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    track = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    keep = insert_asset(ws, kind="video", name="keep.mp4", file_key="", media_info={"duration": 30})
    gone = insert_asset(ws, kind="video", name="gone.mp4", file_key="", media_info={"duration": 10})
    return client, sequence["id"], track, keep, gone


def _video(state: dict) -> list[dict]:
    return sorted(next(t for t in state["tracks"] if t["kind"] == "video")["clips"], key=lambda c: c["timeline_start"])


def _insert(client, seq, track, asset, start, src_out) -> dict:
    res = client.post(
        f"/api/sequences/{seq}/clips",
        json={"track_id": track, "asset_id": asset, "timeline_start": start, "src_in": 0, "src_out": src_out},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_切开后删素材_连按三次撤销都成功_更早的历史也撤得到() -> None:
    client, seq, track, keep, gone = _setup()
    _insert(client, seq, track, keep, 20, 5)
    state = _insert(client, seq, track, gone, 0, 10)
    target = next(c for c in _video(state) if c["asset_id"] == gone)["id"]
    assert client.post(f"/api/sequences/{seq}/clips/{target}/split", json={"src_time": 5}).status_code == 200
    assert client.delete(f"/api/assets/{gone}").status_code == 204

    undone = client.post(f"/api/sequences/{seq}/undo")
    assert undone.status_code == 200, undone.text
    restored = next(c for c in _video(undone.json()) if c["id"] == target)
    assert restored["asset_id"] is None
    assert restored["offline_asset"] == {"asset_id": gone, "name": "gone.mp4", "kind": "video", "duration": 10}
    assert restored["asset_kind"] == "video"

    second = client.post(f"/api/sequences/{seq}/undo")
    assert second.status_code == 200, second.text
    third = client.post(f"/api/sequences/{seq}/undo")
    assert third.status_code == 200, third.text
    assert _video(third.json()) == [] and third.json()["can_undo"] is False


def test_删了片段再删素材_撤销还回脱机占位_重做撤销来回都走得通() -> None:
    client, seq, track, _keep, gone = _setup()
    state = _insert(client, seq, track, gone, 0, 10)
    clip_id = _video(state)[0]["id"]
    assert client.patch(f"/api/sequences/{seq}/clips/{clip_id}/gain", json={"gain": 0.5, "muted": False}).status_code == 200
    assert client.delete(f"/api/sequences/{seq}/clips/{clip_id}").status_code == 200
    # 时间线上已经没有引用它的片段:删素材不会留下任何脱机占位,只有撤销历史还记着它。
    assert client.delete(f"/api/assets/{gone}").status_code == 204

    undone = client.post(f"/api/sequences/{seq}/undo")
    assert undone.status_code == 200, undone.text
    (clip,) = _video(undone.json())
    assert clip["id"] == clip_id and clip["gain"] == 0.5
    assert clip["offline_asset"]["name"] == "gone.mp4"

    assert client.post(f"/api/sequences/{seq}/redo").status_code == 200
    again = client.post(f"/api/sequences/{seq}/undo")
    assert again.status_code == 200 and _video(again.json())[0]["offline_asset"]["name"] == "gone.mp4"
    # 再往前:撤掉音量、撤掉插入 —— 历史没有卡在删素材那一刻。
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200
    last = client.post(f"/api/sequences/{seq}/undo")
    assert last.status_code == 200 and _video(last.json()) == []


def test_撤销插入后删素材_重做还回脱机占位() -> None:
    client, seq, track, _keep, gone = _setup()
    _insert(client, seq, track, gone, 0, 10)
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200
    assert client.delete(f"/api/assets/{gone}").status_code == 204
    redone = client.post(f"/api/sequences/{seq}/redo")
    assert redone.status_code == 200, redone.text
    assert _video(redone.json())[0]["offline_asset"]["asset_id"] == gone


def test_迁移把老的片段记录补齐_老记录照样撤得动() -> None:
    assert "migrate-sequence-operation-clip-records-are-complete" in {s.name for s in migration_plan().steps}
    client, seq, track, _keep, gone = _setup()
    state = _insert(client, seq, track, gone, 0, 10)
    clip_id = _video(state)[0]["id"]
    assert client.delete(f"/api/sequences/{seq}/clips/{clip_id}").status_code == 200
    with SessionLocal() as db:
        operation = db.scalars(
            select(SequenceOperation).where(SequenceOperation.sequence_id == seq, SequenceOperation.kind == "delete_clip")
        ).one()
        # 退回成补齐之前的老形状:改动日志里那份片段记录只有位置(老记录转成日志后就是这样)。
        (entry,) = operation.payload["changes"]
        position = {key: entry["clip"][key] for key in
                    ("clip_id", "track_id", "asset_id", "timeline_start", "src_in", "src_out")}
        operation.payload = {**operation.payload, "changes": [{**entry, "clip": position}]}
        db.commit()
    assert client.delete(f"/api/assets/{gone}").status_code == 204

    _migrate_sequence_operation_clip_records_are_complete()
    _migrate_sequence_operation_clip_records_are_complete()  # 幂等

    with SessionLocal() as db:
        payload = db.scalars(
            select(SequenceOperation).where(SequenceOperation.sequence_id == seq, SequenceOperation.kind == "delete_clip")
        ).one().payload["changes"][0]["clip"]
    assert payload["speed"] == 1.0 and payload["offline_asset"] is None and payload["link_group"] is None
    # 素材在迁移之前就删了、时间线上也没有它的脱机片段:名字已经无处可查,只留下 id。
    assert payload["asset_snapshot"] == {"asset_id": gone, "name": "", "kind": "", "duration": None}

    undone = client.post(f"/api/sequences/{seq}/undo")
    assert undone.status_code == 200, undone.text
    with SessionLocal() as db:
        assert db.get(Clip, clip_id).offline_asset["asset_id"] == gone
