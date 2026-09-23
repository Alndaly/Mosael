"""缩略图留住透明。

JPEG 没有透明通道:带透明的 PNG(图标、抠图)转成 JPEG 缩略图时,四角一块黑、边缘一圈白色
毛刺 —— 而原图和大图预览明明是透明的。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.media.thumbnails import THUMBNAIL_WIDTH, generate_thumbnail, migrate_jpeg_thumbnail, thumbnail_path


def _transparent_icon(path: Path) -> None:
    image = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
    for x in range(200, 600):
        for y in range(150, 450):
            image.putpixel((x, y), (120, 80, 240, 255))
    image.save(path)


def test_a_transparent_png_keeps_its_transparency(tmp_path: Path) -> None:
    source = tmp_path / "icon.png"
    _transparent_icon(source)
    thumb = generate_thumbnail(source, "image", tmp_path)
    assert thumb == thumbnail_path(tmp_path)
    with Image.open(thumb) as image:
        assert image.format == "WEBP"
        assert image.width == THUMBNAIL_WIDTH
        rgba = image.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0  # 角上仍是透明,不是黑的
        assert rgba.getpixel((THUMBNAIL_WIDTH // 2, rgba.height // 2))[3] == 255


def test_a_small_image_is_not_upscaled(tmp_path: Path) -> None:
    source = tmp_path / "small.png"
    Image.new("RGB", (100, 50), (10, 20, 30)).save(source)
    with Image.open(generate_thumbnail(source, "image", tmp_path)) as image:
        assert image.size == (100, 50)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_video_thumbnail_is_webp_too(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=1",
                    "-pix_fmt", "yuv420p", str(source)], check=True, timeout=60)
    with Image.open(generate_thumbnail(source, "video", tmp_path)) as image:
        assert image.format == "WEBP" and image.size == (THUMBNAIL_WIDTH, 180)


def test_old_jpeg_thumbnails_are_replaced(tmp_path: Path) -> None:
    # 图片:旧 JPEG 里透明已经丢了,从原图重做。
    image_dir = tmp_path / "img"
    image_dir.mkdir()
    source = image_dir / "icon.png"
    _transparent_icon(source)
    Image.new("RGB", (320, 240), (0, 0, 0)).save(image_dir / "thumbnail.jpg")
    migrate_jpeg_thumbnail(source, "image", image_dir)
    assert not (image_dir / "thumbnail.jpg").exists()
    with Image.open(thumbnail_path(image_dir)) as image:
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0

    # 视频:直接转那张 JPEG,不再取一次帧(原视频这里根本不存在)。
    video_dir = tmp_path / "vid"
    video_dir.mkdir()
    Image.new("RGB", (320, 180), (200, 10, 10)).save(video_dir / "thumbnail.jpg")
    migrate_jpeg_thumbnail(video_dir / "missing.mp4", "video", video_dir)
    assert not (video_dir / "thumbnail.jpg").exists()
    with Image.open(thumbnail_path(video_dir)) as image:
        assert image.format == "WEBP" and image.size == (320, 180)


def test_the_migration_replaces_old_thumbnails_of_real_assets() -> None:
    """迁移 migrate-thumbnails-keep-transparency:库里的素材、盘上的旧 JPEG 缩略图 → WebP;再跑一次什么都不做。"""
    from app.core.config import settings
    from app.db.migrations import _migrate_thumbnails_keep_transparency
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "image", "name": "icon", "file_key": "media/icon/icon.png", "media_info": {}},
    )
    folder = settings.data_dir / "media" / "icon"
    folder.mkdir(parents=True, exist_ok=True)
    _transparent_icon(folder / "icon.png")
    Image.new("RGB", (320, 240), (0, 0, 0)).save(folder / "thumbnail.jpg")

    _migrate_thumbnails_keep_transparency()
    assert not (folder / "thumbnail.jpg").exists()
    first = thumbnail_path(folder).read_bytes()
    with Image.open(thumbnail_path(folder)) as image:
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0

    _migrate_thumbnails_keep_transparency()
    assert thumbnail_path(folder).read_bytes() == first
