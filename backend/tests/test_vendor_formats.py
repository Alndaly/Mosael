"""把素材转成供应商肯收的格式(可灵、HeyGen 的配音转 mp3,HeyGen 的人像转 png)。真跑一遍随包的 ffmpeg。"""

from __future__ import annotations

import subprocess

import pytest

from app.core.config import settings
from app.media.vendor_formats import VendorFormatError, speech_mp3, still_png


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
    source = tmp_path / "face.webp"
    _make(["-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1"], source)
    out = still_png(source, tmp_path / "face.png")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_转不出来说清楚(tmp_path) -> None:
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not audio")
    with pytest.raises(VendorFormatError) as caught:
        speech_mp3(broken, tmp_path / "out.mp3")
    assert caught.value.key == "mediaErr_vendorFormat"
