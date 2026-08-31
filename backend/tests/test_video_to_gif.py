from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from app.media.video_gif import GifEncodeError, encode_video_gif
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "GIF"}).json()["id"]


def test_ffmpeg_生成可播放的_gif_且不改源文件(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=96x64:rate=12",
            "-t", "0.5", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
    )
    before = source.read_bytes()
    target = tmp_path / "made.gif"
    encode_video_gif(source, target, fps=8, width=80, duration=0.4)
    assert target.read_bytes().startswith(b"GIF8")
    assert source.read_bytes() == before, "转换不应覆盖或重编码原视频"


def test_gif_参数在启动前校验(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(GifEncodeError):
        encode_video_gif(tmp_path / "x.mp4", tmp_path / "x.gif", fps=0)


def test_素材接口只给视频排任务且原素材不变() -> None:
    client = fresh_client()
    ws = _workspace(client)
    video = client.post(
        "/api/assets/import",
        data={"workspace_id": ws},
        files={"file": ("source.mp4", b"video", "video/mp4")},
    ).json()

    # 不让后台线程在这条 API 契约用例里读取假视频；编码器有上面的真 ffmpeg 用例覆盖。
    with patch("app.domain.assets.video_gif.threading.Thread") as thread:
        response = client.post(f"/api/assets/{video['id']}/convert-gif", json={"fps": 10, "width": 640})
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["kind"] == "video_to_gif"
    assert job["payload"]["asset_id"] == video["id"]
    assert thread.called

    unchanged = client.get(f"/api/assets?workspace_id={ws}").json()
    assert len(unchanged) == 1 and unchanged[0]["id"] == video["id"]
    assert unchanged[0]["original_filename"] == "source.mp4"

    image = client.post(
        "/api/assets/import",
        data={"workspace_id": ws},
        files={"file": ("still.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    ).json()
    rejected = client.post(f"/api/assets/{image['id']}/convert-gif", json={})
    assert rejected.status_code == 422


def test_工作流节点已注册并归为内部变更() -> None:
    from app.domain.workflows import INTERNAL_NODE_TYPES, NODE_TYPES
    from app.domain.workflows.executors import get_executor

    assert "video_to_gif" in NODE_TYPES
    assert "video_to_gif" in INTERNAL_NODE_TYPES
    assert get_executor("video_to_gif") is not None
    assert NODE_TYPES["video_to_gif"]["outputs"] == ["asset_id", "source_asset_id"]


def test_智能体转换工具先确认再创建同一类任务() -> None:
    client = fresh_client()
    ws = _workspace(client)
    video = client.post(
        "/api/assets/import",
        data={"workspace_id": ws},
        files={"file": ("source.mp4", b"video", "video/mp4")},
    ).json()
    card = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws,
            "tool": "convert_video_to_gif",
            "payload": {"asset_id": video["id"], "fps": 9, "width": 600, "start": 1, "duration": 2},
        },
    )
    assert card.status_code == 200, card.text
    pending = card.json()
    assert pending["permission"] == "render-cost"
    assert "原视频不变" in pending["summary"]
    with patch("app.domain.assets.video_gif.threading.Thread") as thread:
        approved = client.post(f"/api/confirmations/{pending['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["source_asset_id"] == video["id"]
    assert thread.called
