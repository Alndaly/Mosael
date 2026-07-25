"""导出进度的精细化:ffmpeg -progress 块解析(速度/ETA)+ 阶段中文文案。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.domain import render as render_domain
from app.media import render_executor as rx
from app.media.render_executor import (
    PHASE_ENCODE,
    PHASE_FALLBACK,
    PHASE_FINALIZE,
    PHASE_PREPARE,
    RenderProgress,
    execute_render,
)
from app.media.render_plan import build_render_plan

HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.mark.parametrize(
    "raw,expected",
    [("12.3x", 12.3), ("1.0x", 1.0), ("0.5x", 0.5), ("N/A", None), ("", None), ("0x", None)],
)
def test_parse_ffmpeg_speed(raw, expected):
    assert rx._parse_ffmpeg_speed(raw) == expected


def test_progress_block_fraction_speed_fps_eta():
    # 时间线 10s,已编码 5s,速度 10x ⇒ 进度 0.5,剩余媒体 5s / 10x = 0.5s 墙钟。
    prog = rx._progress_from_block(
        {"out_time_us": "5000000", "speed": "10.0x", "fps": "60"}, total_us=10_000_000
    )
    assert prog.fraction == pytest.approx(0.5)
    assert prog.speed == pytest.approx(10.0)
    assert prog.fps == pytest.approx(60.0)
    assert prog.eta_seconds == pytest.approx(0.5)


def test_progress_block_no_speed_gives_no_eta():
    prog = rx._progress_from_block({"out_time_us": "2000000", "speed": "N/A"}, total_us=10_000_000)
    assert prog.fraction == pytest.approx(0.2)
    assert prog.speed is None
    assert prog.eta_seconds is None


def test_progress_block_fraction_clamped():
    prog = rx._progress_from_block({"out_time_us": "99000000"}, total_us=10_000_000)
    assert prog.fraction == 1.0


@pytest.mark.parametrize(
    "seconds,text",
    [(0, "0 秒"), (8, "8 秒"), (59, "59 秒"), (80, "1 分 20 秒"), (120, "2 分"), (3700, "1 时 1 分")],
)
def test_format_eta(seconds, text):
    assert render_domain._format_eta(seconds) == text


def test_export_message_phases():
    assert render_domain._export_message(PHASE_PREPARE, None) == "准备导出…"
    assert "软件编码" in render_domain._export_message(PHASE_FALLBACK, None)
    assert render_domain._export_message(PHASE_FINALIZE, None) == "封装文件…"
    assert render_domain._export_message(PHASE_ENCODE, None) == "编码中…"


def test_export_message_encode_with_speed_and_eta():
    prog = RenderProgress(fraction=0.5, speed=12.3, fps=60.0, eta_seconds=8.0)
    assert render_domain._export_message(PHASE_ENCODE, prog) == "编码中 · 12.3x · 约剩 8 秒"


def test_export_message_encode_speed_only():
    prog = RenderProgress(fraction=0.5, speed=8.0, fps=None, eta_seconds=None)
    assert render_domain._export_message(PHASE_ENCODE, prog) == "编码中 · 8.0x"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_real_render_reports_phases_and_progress(tmp_path: Path, monkeypatch):
    """跑一次真 ffmpeg,验证块解析对真实 -progress 输出成立:阶段流转 + 进度到 1.0 + 拿到速度。"""
    # 软件编码,输出确定;也避开硬件编码器在 CI 上的不确定性。
    monkeypatch.setattr(rx.settings, "hw_encode", False)
    base = tmp_path / "base.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=30:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)],
        check=True, timeout=60,
    )
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": str(base)}},
    )
    phases: list[str] = []
    progresses: list[RenderProgress] = []
    execute_render(
        plan, lambda key: Path(key), tmp_path / "out.mp4",
        on_progress=progresses.append,
        on_phase=phases.append,
    )
    assert phases[0] == PHASE_PREPARE
    assert PHASE_ENCODE in phases
    assert PHASE_FINALIZE in phases
    assert progresses, "should have received at least one progress block"
    # ffmpeg 逐帧进度到不了 1.0(末帧 out_time ≈ 时长−1帧),但应逼近满。
    assert max(p.fraction for p in progresses) > 0.9
    # 真实 ffmpeg 会报速度。
    assert any(p.speed is not None for p in progresses)
