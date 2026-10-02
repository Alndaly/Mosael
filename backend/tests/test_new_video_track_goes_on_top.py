"""新视频轨默认建在最上面(盖在所有画面之上),也可以指定放在第几行;撤销连让位一起还回去。

position 升序就是时间线从上到下,也是画面的叠放顺序(最上面的盖住下面的,media/scene)。此前新轨
一律排在所有轨之后:新视频轨落在音频轨下面,还是**最底**的画面层 —— 最底的有画面的轨就是底图,
于是加一条轨放画中画,它反而成了底图、把原片盖住。「加花字」「拖到最上面建新层」都靠新建视频轨。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.migrations import _migrate_added_track_records_list_what_moved, migration_plan
from app.db.models import SequenceOperation
from app.domain.render import build_plan_for_sequence
from tests.util import fresh_client, insert_asset


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    return client, ws, sequence


def _rows(state: dict) -> list[str]:
    return [track["name"] for track in sorted(state["tracks"], key=lambda t: t["position"])]


def test_新视频轨在最上面_音频字幕轨在最下面() -> None:
    client, _ws, sequence = _setup()
    seq = sequence["id"]
    assert _rows(client.post(f"/api/sequences/{seq}/tracks", json={"kind": "video"}).json()) == ["V2", "V1", "A1"]
    assert _rows(client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio"}).json()) == ["V2", "V1", "A1", "A2"]
    assert _rows(client.post(f"/api/sequences/{seq}/tracks", json={"kind": "subtitle"}).json())[-1] == "S1"


def test_新轨上的画面盖在原片上_原片仍是底图() -> None:
    client, ws, sequence = _setup()
    seq = sequence["id"]
    v1 = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    asset = insert_asset(ws, kind="video", name="v", file_key="media/v.mp4", media_info={"duration": 10})
    client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": v1, "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 10})
    state = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "video"}).json()
    v2 = next(t["id"] for t in state["tracks"] if t["name"] == "V2")
    client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": v2, "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 3})
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, seq)
    assert [segment.duration for segment in plan.video_segments if segment.kind == "clip"] == [10.0]
    assert len(plan.overlays) == 1


def test_指定位置插在中间_撤销还回原来的行_重做再让一次() -> None:
    client, _ws, sequence = _setup()
    seq = sequence["id"]
    state = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio", "index": 1}).json()
    assert _rows(state) == ["V1", "A2", "A1"]
    assert _rows(client.post(f"/api/sequences/{seq}/undo").json()) == ["V1", "A1"]
    assert _rows(client.post(f"/api/sequences/{seq}/redo").json()) == ["V1", "A2", "A1"]
    assert client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio", "index": 9}).status_code == 422


def test_迁移给老的加轨记录补上_谁都没让过() -> None:
    assert "migrate-added-track-records-list-what-moved" in {s.name for s in migration_plan().steps}
    client, _ws, sequence = _setup()
    seq = sequence["id"]
    client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio"})
    with SessionLocal() as db:
        operation = db.scalars(select(SequenceOperation).where(SequenceOperation.sequence_id == seq)).one()
        operation.payload = {k: v for k, v in operation.payload.items() if k != "shifted"}
        db.commit()
    _migrate_added_track_records_list_what_moved()
    _migrate_added_track_records_list_what_moved()
    assert _rows(client.post(f"/api/sequences/{seq}/undo").json()) == ["V1", "A1"]
