"""找接缝:下一段开头有一截是上一段的尾巴(可能被压缩过),新内容从紧跟它的那一帧开始。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.media.seam import SeamError, find_seam


def _clip(path: Path, *, offset: float, duration: float, speed: float = 1.0) -> Path:
    """一段往右走的测试图。`offset` 是从这个图案的第几秒开始。"""
    vf = f"trim=start={offset}:duration={duration / speed * speed},setpts=(PTS-STARTPTS)/{speed}"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=20",
                    "-vf", vf, "-r", "24", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_尾巴原样在开头(tmp_path: Path) -> None:
    previous = _clip(tmp_path / "a.mp4", offset=0, duration=4)
    following = _clip(tmp_path / "b.mp4", offset=3, duration=4)
    assert find_seam(previous, following, search_seconds=3, fps=24) == pytest.approx(1.0, abs=0.09)


def test_尾巴被压缩过_接缝比原长早(tmp_path: Path) -> None:
    previous = _clip(tmp_path / "a.mp4", offset=0, duration=4)
    following = _clip(tmp_path / "b.mp4", offset=2, duration=4, speed=1.08)
    assert find_seam(previous, following, search_seconds=3, fps=24) == pytest.approx(2 / 1.08, abs=0.1)


def test_读不出来就照实说(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(SeamError):
        find_seam(bad, bad, search_seconds=1, fps=24)
