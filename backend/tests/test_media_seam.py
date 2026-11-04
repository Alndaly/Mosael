"""找接缝:下一段开头有一截是上一段的尾巴(可能被压缩过),新内容从紧跟它的那一帧开始。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.seam import SeamError, _end_of_best_match, find_seam


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


def test_尾巴几乎不动时_取那一段的末尾() -> None:
    """实测曲线(每 0.2 秒一个点):真接缝在 1.9 秒,最小值却在 0.5 秒。"""
    plateau = np.array([7.8, 5.0, 4.2, 4.1, 4.1, 4.4, 4.6, 4.5, 4.7, 4.8, 5.9, 7.5, 8.4, 9.2])
    assert _end_of_best_match(plateau) == 9


def test_尖的那一帧不往后挪() -> None:
    assert _end_of_best_match(np.array([30.0, 20.0, 8.4, 8.2, 17.4, 21.5])) == 3
