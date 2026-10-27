"""QuickTime .mov 原样换成 .mp4 容器(不重编码)。

Mac 录屏的 .mov 在界面里拖进度条会卡好几秒:Chromium 每次跳转都在这种容器里来回跳读。
同样的画面和声音换成 mp4 容器后单次跳转 0.03–0.17 秒。画质不变 —— 只换包装。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset
from tests.util import fresh_client, create_asset

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _mov(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
         "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, timeout=60,
    )


def _streams(path: Path) -> list[str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,nb_frames", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


def _moov_before_mdat(path: Path) -> bool:
    data = path.read_bytes()
    return data.find(b"moov") < data.find(b"mdat")


def test_an_imported_mov_is_stored_as_mp4_with_the_same_streams(tmp_path: Path) -> None:
    source = tmp_path / "Screen Recording.mov"
    _mov(source)
    before = _streams(source)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("Screen Recording.mov", source.read_bytes(), "video/quicktime")},
    ).json()
    assert asset["kind"] == "video"
    assert asset["original_filename"] == "Screen Recording.mp4"
    assert asset["name"] == "Screen Recording.mp4"
    stored = settings.data_dir / asset["file_key"]
    assert stored.suffix == ".mp4" and stored.is_file()
    assert not stored.with_suffix(".mov").exists()
    assert _streams(stored) == before  # 同样的编码、同样的帧数:只换了包装
    assert _moov_before_mdat(stored)
    assert asset["media_info"].get("duration")


def _mov_asset(client, name: str, original: str) -> tuple[str, Path]:  # type: ignore[no-untyped-def]
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    key = f"media/rec-{name}/{original}"
    asset = create_asset(client, {"workspace_id": ws["id"], "kind": "video", "name": name, "file_key": key, "media_info": {}})
    with SessionLocal() as db:
        db.get(Asset, asset["id"]).original_filename = original
        db.commit()
    folder = settings.data_dir / "media" / f"rec-{name}"
    folder.mkdir(parents=True, exist_ok=True)
    return asset["id"], folder
