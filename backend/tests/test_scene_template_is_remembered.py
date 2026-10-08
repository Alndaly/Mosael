"""A scene made from the sample remembers which sample it came from.

The scenes page offered 「打开三间展厅示例」 and created a fresh copy on every click: four clicks, four
identically named scenes. The content now carries ``template``; the list hands it out so the page can open the
copy that already exists instead.
"""

from __future__ import annotations

from tests.util import fresh_client


def test_the_sample_marker_round_trips_and_shows_up_in_the_list() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sample = client.post("/api/scenes", json={"workspace_id": ws, "name": "三间展厅", "content": {"template": "three_halls"}})
    assert sample.status_code == 200, sample.text
    assert sample.json()["content"]["template"] == "three_halls"
    plain = client.post("/api/scenes", json={"workspace_id": ws, "name": "空场景"}).json()
    assert plain["content"]["template"] is None

    # 改过的示例还是那一份:保存之后标记还在。
    edited = {**sample.json()["content"], "background": "#101010"}
    saved = client.patch(f"/api/scenes/{sample.json()['id']}", json={"workspace_id": ws, "name": "我的展厅", "content": edited, "base_revision": 1})
    assert saved.status_code == 200, saved.text
    assert saved.json()["content"]["template"] == "three_halls"

    listed = {row["id"]: row for row in client.get("/api/scenes", params={"workspace_id": ws}).json()}
    assert listed[sample.json()["id"]]["template"] == "three_halls"
    assert listed[plain["id"]]["template"] is None


def test_an_unknown_template_is_refused() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    refused = client.post("/api/scenes", json={"workspace_id": ws, "content": {"template": "somewhere"}})
    assert refused.status_code == 422, refused.text
