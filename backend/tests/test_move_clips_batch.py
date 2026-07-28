"""框选整组拖动:一次手势 = 一条操作 = 一步撤销。

为什么不是「循环调用 move_clip」:那样 N 个片段落成 N 条 SequenceOperation,撤销一次只退回
一个,用户要按 N 次 ⌘Z 才能还原一次拖动。仓库里 insert_clips_batch / set_clip_texts_batch
已经是这个范式,组拖沿用它。

用文本片段搭时间线只是为了不依赖真实素材文件——move 不关心片段是什么类型。
"""

from __future__ import annotations

from tests.util import fresh_client


def _sequence_with_clips(client, count: int = 3):
    """一条字幕轨 + count 个等距片段;返回 (sequence_id, track_id, clip_ids)。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    added = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in added["tracks"] if t["kind"] == "subtitle")
    clip_ids: list[str] = []
    for i in range(count):
        updated = client.post(
            f"/api/sequences/{sequence['id']}/text-clips",
            json={"track_id": track_id, "text": f"片段 {i}", "timeline_start": i * 10.0, "duration": 5.0},
        ).json()
        clips = next(t["clips"] for t in updated["tracks"] if t["id"] == track_id)
        clip_ids = [c["id"] for c in sorted(clips, key=lambda c: c["timeline_start"])]
    return sequence["id"], track_id, clip_ids


def _starts(payload, clip_ids: list[str]) -> list[float]:
    by_id = {c["id"]: c["timeline_start"] for track in payload["tracks"] for c in track["clips"]}
    return [by_id[cid] for cid in clip_ids]


def test_moves_every_clip_in_one_revision() -> None:
    client = fresh_client()
    seq_id, _track_id, ids = _sequence_with_clips(client)
    before = client.get(f"/api/sequences/{seq_id}").json()["revision"]

    res = client.patch(
        f"/api/sequences/{seq_id}/clips/move-batch",
        json={"moves": [{"clip_id": cid, "timeline_start": i * 10.0 + 3} for i, cid in enumerate(ids)]},
    )
    assert res.status_code == 200, res.text
    after = res.json()
    assert _starts(after, ids) == [3, 13, 23]
    assert after["revision"] == before + 1, "整组拖动必须只花一个 revision"


def test_one_undo_restores_the_whole_group() -> None:
    """核心:整组拖动撤销一次就该全部还原,而不是退回其中一个。"""
    client = fresh_client()
    seq_id, _track_id, ids = _sequence_with_clips(client)
    client.patch(
        f"/api/sequences/{seq_id}/clips/move-batch",
        json={"moves": [{"clip_id": cid, "timeline_start": i * 10.0 + 3} for i, cid in enumerate(ids)]},
    )

    undone = client.post(f"/api/sequences/{seq_id}/undo")
    assert undone.status_code == 200, undone.text
    assert _starts(undone.json(), ids) == [0, 10, 20], "撤销一次没有还原整组"

    redone = client.post(f"/api/sequences/{seq_id}/redo")
    assert redone.status_code == 200, redone.text
    assert _starts(redone.json(), ids) == [3, 13, 23], "重做一次没有重新应用整组"


def test_moves_across_tracks_in_one_go() -> None:
    """跨轨组拖:整组换到另一条同类轨上。"""
    client = fresh_client()
    seq_id, _track_id, ids = _sequence_with_clips(client)
    added = client.post(f"/api/sequences/{seq_id}/tracks", json={"kind": "subtitle"}).json()
    target = [t for t in added["tracks"] if t["kind"] == "subtitle"][-1]["id"]

    res = client.patch(
        f"/api/sequences/{seq_id}/clips/move-batch",
        json={"moves": [{"clip_id": cid, "timeline_start": i * 10.0, "track_id": target} for i, cid in enumerate(ids)]},
    )
    assert res.status_code == 200, res.text
    landed = next(t["clips"] for t in res.json()["tracks"] if t["id"] == target)
    assert sorted(c["id"] for c in landed) == sorted(ids)


def test_rejects_the_whole_group_when_one_move_is_invalid() -> None:
    """校验先于任何写入:一个非法就整组不落,不能留下改了一半的时间线。"""
    client = fresh_client()
    seq_id, _track_id, ids = _sequence_with_clips(client)
    before = _starts(client.get(f"/api/sequences/{seq_id}").json(), ids)

    res = client.patch(
        f"/api/sequences/{seq_id}/clips/move-batch",
        json={
            "moves": [
                {"clip_id": ids[0], "timeline_start": 50.0},
                {"clip_id": ids[1], "timeline_start": -1.0},  # 非法:负起点
            ]
        },
    )
    assert res.status_code == 422, res.text
    assert _starts(client.get(f"/api/sequences/{seq_id}").json(), ids) == before, "非法组被部分应用了"


def test_unknown_clip_id_writes_nothing() -> None:
    client = fresh_client()
    seq_id, _track_id, ids = _sequence_with_clips(client)
    before = _starts(client.get(f"/api/sequences/{seq_id}").json(), ids)
    res = client.patch(
        f"/api/sequences/{seq_id}/clips/move-batch",
        json={"moves": [{"clip_id": ids[0], "timeline_start": 50.0}, {"clip_id": "nope", "timeline_start": 1.0}]},
    )
    assert res.status_code in (404, 422), res.text
    assert _starts(client.get(f"/api/sequences/{seq_id}").json(), ids) == before


def test_empty_move_list_is_rejected() -> None:
    client = fresh_client()
    seq_id, _track_id, _ids = _sequence_with_clips(client)
    assert client.patch(f"/api/sequences/{seq_id}/clips/move-batch", json={"moves": []}).status_code == 422
