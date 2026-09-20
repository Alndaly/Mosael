from __future__ import annotations

from tests.util import fresh_client


def test_project_rename_and_delete() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "Old"}).json()

    renamed = client.patch(f"/api/projects/{project['id']}", json={"name": "New name"}).json()
    assert renamed["name"] == "New name"

    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/projects?workspace_id={ws['id']}").json() == []


def test_project_asset_list_includes_workspace_level_assets() -> None:
    """工作区级素材(project_id 为空)在项目内也要能看到 —— 否则「素材」页导入的东西
    在剪辑页的素材面板里不显示。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    proj = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    other = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "Other"}).json()

    def mk(name: str, project_id: str | None) -> None:
        body = {"workspace_id": ws["id"], "kind": "video", "name": name, "file_key": f"m/{name}"}
        if project_id:
            body["project_id"] = project_id
        client.post("/api/assets", json=body)

    mk("workspace-level", None)  # 从「素材」页导入的那种
    mk("mine", proj["id"])
    mk("theirs", other["id"])

    names = {a["name"] for a in client.get(f"/api/assets?workspace_id={ws['id']}&project_id={proj['id']}").json()}
    assert names == {"workspace-level", "mine"}, names  # 别的项目的素材仍然不串场


def test_asset_rename_and_delete_takes_referencing_clips_offline() -> None:
    """删得掉,而引用它的片段**留在原位**变成脱机占位 —— 达芬奇的做法。

    此前这里是 422「请先从时间线移除」:想删一个素材,得先自己在十几条序列里翻出每一段。
    现在删除是删除,时间线上留下一个看得见的占位,用户随时知道是哪一段、原来是哪个文件。
    """
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "A",
              "file_key": "media/a.mp4", "media_info": {"duration": 5}},
    ).json()

    renamed = client.patch(f"/api/assets/{asset['id']}", json={"name": "B-roll"}).json()
    assert renamed["name"] == "B-roll"

    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 5},
    ).json()

    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]
    assert client.delete(f"/api/assets/{asset['id']}").status_code == 204

    after = client.get(f"/api/sequences/{sequence['id']}").json()
    offline = next(t for t in after["tracks"] if t["kind"] == "video")["clips"][0]
    assert offline["id"] == clip["id"], "片段不该跟着素材一起消失 —— 消失了就没人知道这里少了什么"
    assert offline["asset_id"] is None
    # 快照里留着名字:占位上写不出原来是哪个文件的话,用户没法把它对回去。
    assert offline["offline_asset"]["name"] == "B-roll"
    assert offline["offline_asset"]["asset_id"] == asset["id"]
    assert offline["asset_kind"] == "video", "轨道还是那条轨道"
    # 时长不变 —— 后面的片段不该因为这次删除整体前移。
    assert offline["src_out"] == 5

    # **导出挡在这里**:脱机片段既不是画面也不是文字,再往下每一条筛选都会漏掉它,
    # 于是成片会静默地短一截。宁可拒,也不要交一个少了一段的成片。
    refused = client.post(f"/api/sequences/{sequence['id']}/export")
    assert refused.status_code == 422
    assert "B-roll" in refused.json()["detail"]

    # 把那一段删掉,挡住导出的理由就没了(空序列还会因为别的理由被拒,那是另一回事)。
    client.delete(f"/api/sequences/{sequence['id']}/clips/{clip['id']}")
    assert "已被删除" not in client.post(f"/api/sequences/{sequence['id']}/export").text


def test_asset_tags_update_dedupes_and_trims() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "video", "name": "A", "file_key": "media/a.mp4"},
    ).json()
    assert asset["tags"] == []

    updated = client.patch(
        f"/api/assets/{asset['id']}",
        json={"tags": [" b-roll ", "b-roll", "海边", "", "  "]},
    ).json()
    assert updated["tags"] == ["b-roll", "海边"]

    # 只改名不带 tags 字段:标签保持不变。
    renamed = client.patch(f"/api/assets/{asset['id']}", json={"name": "A2"}).json()
    assert renamed["tags"] == ["b-roll", "海边"]

    listed = client.get(f"/api/assets?workspace_id={ws['id']}").json()
    assert listed[0]["tags"] == ["b-roll", "海边"]


def test_agent_session_rename_and_delete() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()

    renamed = client.patch(f"/api/agent/sessions/{session['id']}", json={"title": "剪辑讨论"}).json()
    assert renamed["title"] == "剪辑讨论"

    assert client.delete(f"/api/agent/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/agent/sessions/{session['id']}").status_code == 404
