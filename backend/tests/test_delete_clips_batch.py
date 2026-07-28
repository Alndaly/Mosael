"""多选批量删除:一次手势 = 一条操作 = 一步撤销。

与 move_clips_batch 同一条原则。之前前端是 `for clipId of ids: await deleteClip(...)`,
删 5 段就落成 5 条 SequenceOperation,⌘Z 一次只找回一段——用户得连按 5 次才回到删之前。
"""

from __future__ import annotations

from tests.util import fresh_client


def _sequence_with_clips(client, count: int = 4):
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
    return sequence["id"], clip_ids


def _clip_starts(payload) -> dict[str, float]:
    return {c["id"]: c["timeline_start"] for track in payload["tracks"] for c in track["clips"]}


def test_batch_delete_is_one_revision_and_one_undo() -> None:
    client = fresh_client()
    seq_id, ids = _sequence_with_clips(client)
    before = client.get(f"/api/sequences/{seq_id}").json()["revision"]

    res = client.post(f"/api/sequences/{seq_id}/clips/delete-batch", json={"clip_ids": ids[:3]})
    assert res.status_code == 200, res.text
    assert res.json()["revision"] == before + 1, "删三段必须只花一个 revision"
    assert set(_clip_starts(res.json())) == {ids[3]}

    undone = client.post(f"/api/sequences/{seq_id}/undo")
    assert undone.status_code == 200, undone.text
    starts = _clip_starts(undone.json())
    assert set(starts) == set(ids), "撤销一次没有把整批找回来"
    assert [starts[c] for c in ids] == [0, 10, 20, 30], "找回来的位置不对"

    redone = client.post(f"/api/sequences/{seq_id}/redo")
    assert set(_clip_starts(redone.json())) == {ids[3]}


def test_batch_delete_rejects_unknown_id_without_deleting_anything() -> None:
    """一个 id 不存在就整批不删——留下删了一半的时间线比直接报错更难收拾。"""
    client = fresh_client()
    seq_id, ids = _sequence_with_clips(client)
    res = client.post(f"/api/sequences/{seq_id}/clips/delete-batch", json={"clip_ids": [ids[0], "nope"]})
    assert res.status_code in (404, 422), res.text
    assert set(_clip_starts(client.get(f"/api/sequences/{seq_id}").json())) == set(ids)


def test_empty_list_is_rejected() -> None:
    client = fresh_client()
    seq_id, _ids = _sequence_with_clips(client)
    assert client.post(f"/api/sequences/{seq_id}/clips/delete-batch", json={"clip_ids": []}).status_code == 422


def test_ripple_batch_closes_gaps_and_undoes_in_one_step() -> None:
    """波纹批量删除:后续片段左移补位,撤销一次连位移一起还原。"""
    client = fresh_client()
    seq_id, ids = _sequence_with_clips(client)  # 起点 0/10/20/30,各长 5

    res = client.post(f"/api/sequences/{seq_id}/clips/ripple-delete-batch", json={"clip_ids": [ids[0], ids[1]]})
    assert res.status_code == 200, res.text
    starts = _clip_starts(res.json())
    assert set(starts) == {ids[2], ids[3]}
    # 删掉两段各 5s,后面两段各左移 10s。
    assert starts[ids[2]] == 10 and starts[ids[3]] == 20

    undone = client.post(f"/api/sequences/{seq_id}/undo")
    assert undone.status_code == 200, undone.text
    starts = _clip_starts(undone.json())
    assert set(starts) == set(ids), "撤销一次没有把整批找回来"
    assert [starts[c] for c in ids] == [0, 10, 20, 30], "位移没有随删除一起还原"


def test_ripple_batch_order_does_not_depend_on_input_order() -> None:
    """传入顺序不该影响结果:内部必须从后往前删,否则先删靠前的会把后面的目标带偏。"""
    client = fresh_client()
    seq_id, ids = _sequence_with_clips(client)
    res = client.post(
        f"/api/sequences/{seq_id}/clips/ripple-delete-batch",
        json={"clip_ids": [ids[1], ids[0]]},  # 故意倒着传
    )
    assert res.status_code == 200, res.text
    starts = _clip_starts(res.json())
    assert starts[ids[2]] == 10 and starts[ids[3]] == 20
