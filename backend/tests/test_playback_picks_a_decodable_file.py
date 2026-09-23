"""界面上放视频,原片放不动就放预览代理。

Retina 录屏 3456×2234@120fps 每秒 9.3 亿像素,超出硬件解码器的规格,浏览器落到软解:
每拖一下进度条都要从上一个关键帧软解一百多帧超大画面,卡好几秒。代理早就转好了却没人用。
"""
from __future__ import annotations

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset
from tests.util import fresh_client


def _video(client, media_info: dict) -> str:  # type: ignore[no-untyped-def]
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "video", "name": "rec",
              "file_key": "media/rec/original.mov", "media_info": {}},
    ).json()
    folder = settings.data_dir / "media" / "rec"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "original.mov").write_bytes(b"original")
    (folder / "proxy.mp4").write_bytes(b"proxy")
    with SessionLocal() as db:
        row = db.get(Asset, asset["id"])
        row.media_info = media_info
        db.commit()
    return asset["id"]


def test_an_oversized_original_plays_from_the_proxy() -> None:
    client = fresh_client()
    asset_id = _video(client, {"width": 3456, "height": 2234, "fps": 120, "proxy_status": "ready"})
    res = client.get(f"/api/assets/{asset_id}/playback")
    assert res.status_code == 200
    assert res.content == b"proxy"
    assert res.headers["content-type"] == "video/mp4"
    # 下载仍然是原文件。
    assert client.get(f"/api/assets/{asset_id}/file").content == b"original"


def test_an_ordinary_original_plays_itself() -> None:
    client = fresh_client()
    asset_id = _video(client, {"width": 1920, "height": 1080, "fps": 30, "proxy_status": "ready"})
    assert client.get(f"/api/assets/{asset_id}/playback").content == b"original"


def test_without_a_ready_proxy_it_falls_back_to_the_original() -> None:
    client = fresh_client()
    asset_id = _video(client, {"width": 3456, "height": 2234, "fps": 120, "proxy_status": "pending"})
    assert client.get(f"/api/assets/{asset_id}/playback").content == b"original"
