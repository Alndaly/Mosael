from __future__ import annotations

from tests.media_fixtures import TINY_HEIC
from tests.util import make_video_asset
from tests.util import fresh_client


def test_get_single_asset_returns_metadata() -> None:
    # 单资产详情路由:前端 MediaPreview / 工具卡靠它拉元数据。缺它会 404 →「素材不可用」。
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = make_video_asset(client, ws["id"])

    got = client.get(f"/api/assets/{asset['id']}")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["id"] == asset["id"]
    assert body["name"] == "成片A"
    assert body["kind"] == "video"


def test_get_single_asset_missing_is_404() -> None:
    client = fresh_client()
    missing = client.get("/api/assets/does-not-exist")
    assert missing.status_code == 404


def test_heic_has_a_browser_compatible_full_size_preview() -> None:
    """原件可以保留 HEIC,但 `<img>` 与视觉模型拿到的必须是浏览器通用格式。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    imported = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("photo.heic", TINY_HEIC, "image/heic")},
    )
    assert imported.status_code == 200, imported.text
    asset = imported.json()
    assert asset["kind"] == "image"

    preview = client.get(f"/api/assets/{asset['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.content.startswith(b"\xff\xd8")

    # 下载仍拿原件:兼容预览是派生物,不是有损替换用户文件。
    original = client.get(f"/api/assets/{asset['id']}/file")
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("image/heic")
    assert original.content == TINY_HEIC


def test_update_asset_moves_it_between_projects() -> None:
    """智能体的 update_asset 靠这个字段归档素材。

    工作流的素材整理节点一直能改归属,而 PATCH 接口收不了 project_id —— 于是同一个能力
    在两个界面上不一样。空串是「移出项目」,不是「别动」。
    """
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "第一期"}).json()
    asset = make_video_asset(client, ws["id"])

    moved = client.patch(f"/api/assets/{asset['id']}", json={"project_id": project["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["project_id"] == project["id"]

    # 不带 project_id 的更新不该把它顺手清空
    renamed = client.patch(f"/api/assets/{asset['id']}", json={"name": "成片B"})
    assert renamed.json()["project_id"] == project["id"]

    out = client.patch(f"/api/assets/{asset['id']}", json={"project_id": ""})
    assert out.json()["project_id"] is None


def test_update_asset_rejects_a_project_from_another_workspace() -> None:
    """跨工作区归档会让素材从原工作区的列表里消失 —— 拒绝,而不是静默照做。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    other_ws = client.post("/api/workspaces", json={"name": "别处"}).json()
    elsewhere = client.post("/api/projects", json={"workspace_id": other_ws["id"], "name": "别处的"}).json()
    asset = make_video_asset(client, ws["id"])

    denied = client.patch(f"/api/assets/{asset['id']}", json={"project_id": elsewhere["id"]})
    assert denied.status_code == 422, denied.text
    assert client.get(f"/api/assets/{asset['id']}").json()["project_id"] is None
