"""每次导出 / 取帧有自己的中转目录(文字 PNG、.ass 都在里面),结束时整个删掉。

此前字幕 PNG 写在成片旁边、按**序列** id 起名:同一条时间线同时导出两份(1080p 和 720p),后起的那份把
先起的那份的 PNG 覆盖掉 —— ffmpeg 的 `-loop 1` 每一帧都重新读这张图,于是先起的成片后半段烧进去的是
另一份的字。.ass 倒是按任务起名,可从来没人删,导出目录里一直在攒。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import PHASE_PREPARE, RenderExecutionError, execute_render, render_still
from app.media.render_plan import build_render_plan
from tests.render_text_paths import use_browser, use_libass

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")


def _source(tmp_path: Path) -> Path:
    src = tmp_path / "src.mp4"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=0x336699:s=320x180:r=10:d=6",
                    "-pix_fmt", "yuv420p", str(src)], check=True, timeout=30)
    return src


def _plan(width: int, height: int, text: str, font_size: float):
    #: 两份计划**同一个 sequence_id** —— 覆盖正是从这里来的。
    return build_render_plan(
        sequence_id="same-sequence", revision=1, width=width, height=height, fps=10,
        clips=[{"id": "c1", "asset_id": "v", "timeline_start": 0, "src_in": 0, "src_out": 6}],
        assets={"v": {"file_key": "src.mp4"}},
        subtitle_clips=[{"id": "s1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 6, "text_override": text}],
        subtitle_style={"font_size": font_size, "bg_opacity": 0.9, "bg_color": "#ffffff", "color": "#000000"},
    )


def _gray_frame(path: Path, at: float, width: int, height: int) -> np.ndarray:
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-ss", f"{at}", "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True, timeout=30).stdout
    return np.frombuffer(raw, np.uint8).reshape(height, width).astype(int)


def test_同一条时间线同时导出两份_字幕互不覆盖(tmp_path, monkeypatch) -> None:
    use_browser(monkeypatch)
    _source(tmp_path)
    resolve = lambda key: tmp_path / key  # noqa: E731
    big = _plan(320, 180, "第一份的大字幕", 28)
    small = _plan(160, 90, "二", 10)

    def start_the_other_one(phase: str) -> None:
        #: 第一份**字已经渲好、ffmpeg 还没起来**的那一刻(准备阶段)把第二份整个跑完 —— 两份确定地交错,
        #: 不靠线程调度碰运气。真实里就是两次导出前后脚点下去。
        if phase == PHASE_PREPARE and not (tmp_path / "small.mp4").exists():
            execute_render(small, resolve, tmp_path / "small.mp4")

    execute_render(big, resolve, tmp_path / "big.mp4", on_phase=start_the_other_one)
    execute_render(big, resolve, tmp_path / "big_alone.mp4")

    together = _gray_frame(tmp_path / "big.mp4", 3.0, 320, 180)
    alone = _gray_frame(tmp_path / "big_alone.mp4", 3.0, 320, 180)
    assert (np.abs(together - alone) > 40).sum() < 50, "第一份成片里烧进去的是第二份的字幕"


@pytest.mark.parametrize("path", ["libass", "browser"])
def test_导出成败都不留中转文件(path, tmp_path, monkeypatch) -> None:
    (use_libass if path == "libass" else use_browser)(monkeypatch)
    _source(tmp_path)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    exports = tmp_path / "exports"
    resolve = lambda key: tmp_path / key  # noqa: E731
    plan = _plan(160, 90, "字幕", 12)

    execute_render(plan, resolve, exports / "job-1.mp4")
    assert sorted(p.name for p in exports.iterdir()) == ["job-1.mp4"], "成片旁边不该有 .ass / PNG"
    assert list(scratch.iterdir()) == [], "这次渲染的中转目录没删"

    render_still(plan, resolve, exports / "frame.jpg", 1.0)
    assert list(scratch.iterdir()) == []

    with pytest.raises(RenderExecutionError):
        execute_render(plan, lambda key: tmp_path / "missing.mp4", exports / "job-2.mp4")
    assert list(scratch.iterdir()) == [], "失败的渲染也要清掉中转目录"


def test_同时导出的两份各用各的中转目录(tmp_path, monkeypatch) -> None:
    """不依赖文字渲染的那半:两次并发渲染拿到的中转目录不同,且都在结束后消失。"""
    from app.media import render_executor

    seen: list[Path] = []
    real = render_executor.render_workdir
    barrier = threading.Barrier(2)

    def spy():
        with real() as workdir:
            seen.append(workdir)
            barrier.wait(timeout=30)
            yield workdir

    import contextlib

    monkeypatch.setattr(render_executor, "render_workdir", contextlib.contextmanager(spy))
    _source(tmp_path)
    plan = build_render_plan(
        sequence_id="same-sequence", revision=1, width=160, height=90, fps=10,
        clips=[{"id": "c1", "asset_id": "v", "timeline_start": 0, "src_in": 0, "src_out": 1}],
        assets={"v": {"file_key": "src.mp4"}},
    )
    threads = [threading.Thread(target=execute_render, args=(plan, lambda key: tmp_path / key, tmp_path / f"{n}.mp4"))
               for n in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(seen) == 2 and seen[0] != seen[1]
    assert not any(path.exists() for path in seen)
