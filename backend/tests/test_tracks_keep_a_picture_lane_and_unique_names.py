"""轨道:最后一条视频轨删不掉,新轨的名字不和已有的撞。

此前轨道可以删光:删掉唯一的视频轨之后,接素材报「没有放视频的轨道」,画板连线、工作流都接不上,
用户想不到是刚才那一下。新轨名是「同类条数 + 1」:有 V1、V2,删掉 V1 再加一条,新的又叫 V2。
"""

from __future__ import annotations

from tests.util import fresh_client


def _sequence():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    return client, sequence


def _names(state: dict) -> list[str]:
    return [track["name"] for track in state["tracks"]]


def test_最后一条视频轨删不掉_有了第二条就能删() -> None:
    client, sequence = _sequence()
    seq = sequence["id"]
    v1 = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    refused = client.delete(f"/api/sequences/{seq}/tracks/{v1}")
    assert refused.status_code == 422
    assert "视频轨" in refused.json()["detail"] or "video track" in refused.json()["detail"]
    client.post(f"/api/sequences/{seq}/tracks", json={"kind": "video"})
    assert client.delete(f"/api/sequences/{seq}/tracks/{v1}").status_code == 200


def test_删了一条再加_新轨不和留下的同名() -> None:
    client, sequence = _sequence()
    seq = sequence["id"]
    state = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio"}).json()
    a1 = next(t["id"] for t in state["tracks"] if t["name"] == "A1")
    client.delete(f"/api/sequences/{seq}/tracks/{a1}")
    state = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio"}).json()
    names = _names(state)
    assert len(names) == len(set(names)), names
    assert sorted(n for n in names if n.startswith("A")) == ["A2", "A3"]
