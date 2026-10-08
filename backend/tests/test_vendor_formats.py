"""把素材转成供应商肯收的格式(可灵、HeyGen 的配音转 mp3,HeyGen 的人像转 png)。真跑一遍随包的 ffmpeg。"""

from __future__ import annotations

import subprocess

import pytest

from app.core.config import settings
from app.media.vendor_formats import VendorFormatError, speech_mp3, still_png, video_sides_within


def _make(arguments: list[str], target) -> None:
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", *arguments, str(target)], check=True, capture_output=True)


def test_配音转单声道_mp3(tmp_path) -> None:
    source = tmp_path / "voice.flac"
    _make(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ac", "2"], source)
    out = speech_mp3(source, tmp_path / "voice.mp3")
    probe = subprocess.run([settings.ffprobe, "-v", "error", "-show_entries", "stream=codec_name,channels",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True, encoding="utf-8", check=True)
    assert probe.stdout.strip() == "mp3,1"


def test_图片转_png(tmp_path) -> None:
    #: 原图用 Pillow 造:要测的是「ffmpeg 把 webp 转成 png」(读 webp 用的是 ffmpeg 自带的解码器),
    #: 而**写** webp 要 libwebp 编码器 —— Homebrew 的 core ffmpeg 没有它,此前用 ffmpeg 造原图,在没有 backend/.env
    #: 指向完整版 ffmpeg 的 worktree 里这条必红。
    from PIL import Image

    source = tmp_path / "face.webp"
    Image.new("RGB", (64, 64), "red").save(source, "WEBP")
    out = still_png(source, tmp_path / "face.png")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_转不出来说清楚(tmp_path) -> None:
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not audio")
    with pytest.raises(VendorFormatError) as caught:
        speech_mp3(broken, tmp_path / "out.mp3")
    assert caught.value.key == "mediaErr_vendorFormat"


def _size(path) -> tuple[int, int]:
    probe = subprocess.run([settings.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, encoding="utf-8", check=True)
    width, height = probe.stdout.strip().split(",")
    return int(width), int(height)


@pytest.mark.parametrize(("source_size", "expected"), [("512x512", (640, 640)), ("3000x1000", (2048, 682)), ("480x852", (640, 1136))])
def test_视频每边缩放进范围_长宽比不变(tmp_path, source_size: str, expected: tuple[int, int]) -> None:
    """百炼改口型只收每边 640–2048 像素的原视频;说话照片交回的是 512×512,直接交过去被拒。"""
    source = tmp_path / "source.mp4"
    _make(["-f", "lavfi", "-i", f"color=c=gray:s={source_size}:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p"], source)
    out = video_sides_within(source, tmp_path / "fit.mp4", min_side=640, max_side=2048)
    assert out != source and _size(out) == expected


def test_已经在范围里的原样交回(tmp_path) -> None:
    source = tmp_path / "source.mp4"
    _make(["-f", "lavfi", "-i", "color=c=gray:s=720x1280:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p"], source)
    assert video_sides_within(source, tmp_path / "fit.mp4", min_side=640, max_side=2048) == source


def test_长宽比太极端_怎么缩都放不进范围_说清楚(tmp_path) -> None:
    source = tmp_path / "source.mp4"
    _make(["-f", "lavfi", "-i", "color=c=gray:s=4000x400:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p"], source)
    with pytest.raises(VendorFormatError) as caught:
        video_sides_within(source, tmp_path / "fit.mp4", min_side=640, max_side=2048)
    assert caught.value.key == "mediaErr_videoSidesOutOfRange"
