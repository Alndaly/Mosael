from __future__ import annotations

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
