from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.db import Base, engine, init_db
from app.main import app
from tests.util import fresh_client


def setup_sequence(client: TestClient) -> tuple[dict, dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={
            "workspace_id": ws["id"],
            "project_id": project["id"],
            "kind": "video",
            "name": "Src",
            "file_key": "media/src.mp4",
            "media_info": {"duration": 10},
        },
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    return ws, asset, sequence


def video_clips(sequence: dict) -> list[dict]:
    return next(track for track in sequence["tracks"] if track["kind"] == "video")["clips"]


def insert(client: TestClient, sequence: dict, asset: dict, start: float) -> dict:
    track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    return client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": start, "src_in": 0, "src_out": 5},
    ).json()


def reset() -> TestClient:
    return fresh_client()


def test_undo_insert_removes_clip_and_redo_restores(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    assert state["can_undo"] is True and state["can_redo"] is False

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(undone) == []
    assert undone["can_redo"] is True

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert len(video_clips(redone)) == 1
    assert redone["can_undo"] is True and redone["can_redo"] is False


def test_undo_move_and_trim_restore_previous_values(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    clip = video_clips(state)[0]

    client.patch(f"/api/sequences/{sequence['id']}/clips/{clip['id']}/move", json={"timeline_start": 3})
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(undone)[0]["timeline_start"] == 0

    client.patch(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/trim",
        json={"timeline_start": 0, "src_in": 1, "src_out": 4},
    )
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    restored = video_clips(undone)[0]
    assert restored["src_in"] == 0 and restored["src_out"] == 5


def test_undo_delete_restores_clip_with_same_id(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    clip = video_clips(state)[0]

    client.delete(f"/api/sequences/{sequence['id']}/clips/{clip['id']}")
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(undone)[0]["id"] == clip["id"]


def test_new_edit_after_undo_invalidates_redo(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    insert(client, sequence, asset, 0)
    client.post(f"/api/sequences/{sequence['id']}/undo")
    state = insert(client, sequence, asset, 6)
    assert state["can_redo"] is False
    res = client.post(f"/api/sequences/{sequence['id']}/redo")
    assert res.status_code == 422


def test_multiple_undos_walk_back_in_lifo_order(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    insert(client, sequence, asset, 0)
    state = insert(client, sequence, asset, 6)
    assert len(video_clips(state)) == 2

    one = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert len(video_clips(one)) == 1
    assert video_clips(one)[0]["timeline_start"] == 0

    zero = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(zero) == []
    assert zero["can_undo"] is False

    empty = client.post(f"/api/sequences/{sequence['id']}/undo")
    assert empty.status_code == 422


def test_revision_increments_on_undo_and_redo(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    assert state["revision"] == 2
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert undone["revision"] == 3
    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert redone["revision"] == 4


def test_两个写入方抢同一个版本号时后到的那个被挡下() -> None:
    """版本号自增走条件 UPDATE,不是读出来加一再写回去。

    后者是 check-then-act:两个写入方都读到 5,都写 6,于是两条编辑共用一个版本号 —— 而版本号
    是撤销栈的排序依据(revision_after),也是序列 JSON 缓存的键,两处都会因此错乱:撤销可能
    退回错的那一条,而缓存会把旧的时间线当成新的发出去。

    这条路径以前基本只有一个人在走,现在不是了:智能体批准一张确认卡就会改时间线,而用户
    同时还在拖片段。
    """
    from app.core.db import SessionLocal
    from app.db.models import Sequence
    from app.domain.sequences.errors import SequenceDomainError
    from app.domain.sequences.operations import _record_operation

    client = fresh_client()
    _, _, sequence = setup_sequence(client)

    first, second = SessionLocal(), SessionLocal()
    try:
        a = first.get(Sequence, sequence["id"])
        b = second.get(Sequence, sequence["id"])
        assert a.revision == b.revision  # 两边都读到了同一个版本号

        _record_operation(first, a, kind="set_subtitle_style", payload={"previous": {}, "style": {}},
                          summary={"operation": "set_subtitle_style"}, actor_id=None)
        first.commit()

        # 后到的那个改 0 行,当场知道自己晚了一步,而不是悄悄写出第二条同版本号的操作
        try:
            _record_operation(second, b, kind="set_subtitle_style", payload={"previous": {}, "style": {}},
                              summary={"operation": "set_subtitle_style"}, actor_id=None)
            second.commit()
            raise AssertionError("第二个写入方应当被挡下")
        except SequenceDomainError as exc:
            assert "刚被改过" in str(exc)
            second.rollback()
    finally:
        first.close()
        second.close()

    # 版本号只前进了一步,操作日志里也只有一条
    assert client.get(f"/api/sequences/{sequence['id']}").json()["revision"] == a.revision
