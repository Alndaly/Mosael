"""导出编码参数选择:硬件优先 + 软件回落 + 码率 / 恒定质量映射。

真机是否有硬件编码器不可控:纯逻辑(_target_bitrate_kbps 的映射、_hw_encode_args 各家参数、
_video_encode_args 在开关/探测结果下的取舍)在这里测;要真编码器的(VideoToolbox 的画质、
起不来的编码器在开跑前就被挡下)用真 ffmpeg 跑,本机没有就跳过。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.media import render_executor as rx
from app.media.render_plan import build_render_plan

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _out(width=1920, height=1080, fps=30, crf=20, preset="veryfast"):
    return SimpleNamespace(width=width, height=height, fps=fps, crf=crf, encode_preset=preset)


def test_bitrate_1080p30_is_high_quality_ballpark():
    # 1080p30 @ CRF20 ≈ 0.10 bpp ≈ 6 Mbps。
    kbps = rx._target_bitrate_kbps(_out())
    assert 5000 <= kbps <= 7500


def test_bitrate_scales_with_pixels_and_fps():
    base = rx._target_bitrate_kbps(_out(1280, 720, 30))
    four_k = rx._target_bitrate_kbps(_out(3840, 2160, 30))
    high_fps = rx._target_bitrate_kbps(_out(1280, 720, 60))
    assert four_k > base
    assert high_fps > base


def test_bitrate_crf_plus_6_roughly_halves():
    hi = rx._target_bitrate_kbps(_out(crf=20))
    lo = rx._target_bitrate_kbps(_out(crf=26))
    assert lo == pytest.approx(hi / 2, rel=0.05)


def test_bitrate_clamped_to_sane_bounds():
    assert rx._target_bitrate_kbps(_out(64, 64, 1, crf=51)) >= 500
    assert rx._target_bitrate_kbps(_out(7680, 4320, 60, crf=0)) <= 120_000


@pytest.mark.parametrize("encoder", [e for e in rx._HW_ENCODER_PRIORITY if e != "h264_videotoolbox"])
def test_hw_args_are_bitrate_mode_and_yuv420p(encoder):
    args = rx._hw_encode_args(encoder, _out())
    assert args[:2] == ["-c:v", encoder]
    assert "-b:v" in args and "-maxrate" in args and "-bufsize" in args
    # mp4 通用性:必须 yuv420p,否则部分播放器/微信等放不了。
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    # 硬件模式不能夹带软件 CRF。
    assert "-crf" not in args


def test_video_encode_args_prefers_hw_when_available(monkeypatch):
    monkeypatch.setattr(rx.settings, "hw_encode", True)
    monkeypatch.setattr(rx, "_available_hw_encoder", lambda: "h264_nvenc")
    args = rx._video_encode_args(_out())
    assert args[:2] == ["-c:v", "h264_nvenc"]
    assert "-crf" not in args


def test_video_encode_args_software_when_flag_off(monkeypatch):
    monkeypatch.setattr(rx.settings, "hw_encode", False)
    monkeypatch.setattr(rx, "_available_hw_encoder", lambda: "h264_videotoolbox")
    args = rx._video_encode_args(_out())
    assert args[:2] == ["-c:v", "libx264"]
    assert args[args.index("-crf") + 1] == "20"


def test_video_encode_args_software_when_no_hw(monkeypatch):
    monkeypatch.setattr(rx.settings, "hw_encode", True)
    monkeypatch.setattr(rx, "_available_hw_encoder", lambda: None)
    args = rx._video_encode_args(_out())
    assert args[:2] == ["-c:v", "libx264"]


def test_force_software_overrides_available_hw(monkeypatch):
    monkeypatch.setattr(rx.settings, "hw_encode", True)
    monkeypatch.setattr(rx, "_available_hw_encoder", lambda: "h264_qsv")
    args = rx._video_encode_args(_out(), force_software=True)
    assert args[:2] == ["-c:v", "libx264"]


def test_videotoolbox_是恒定质量_按_CRF_档位走():
    """固定码率下硬件「高画质」SSIM 只有 0.978,比软件「体积小」的 0.981 还低。"""
    standard = rx._hw_encode_args("h264_videotoolbox", _out(crf=20))
    compact = rx._hw_encode_args("h264_videotoolbox", _out(crf=26))
    assert "-b:v" not in standard and "-crf" not in standard
    assert standard[standard.index("-q:v") + 1] == "66"
    assert compact[compact.index("-q:v") + 1] == "50"
    assert standard[standard.index("-pix_fmt") + 1] == "yuv420p"


def _long_plan(tmp_path: Path, *, crf: int, seconds: float = 32.0, size: str = "64x36"):
    width, height = (int(v) for v in size.split("x"))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}",
         "-vf", "noise=alls=12:allf=t", "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p",
         str(tmp_path / "a.mp4")],
        check=True,
    )
    return build_render_plan(
        sequence_id="s", revision=1, width=width, height=height, fps=30, crf=crf, encode_preset="veryfast",
        clips=[{"id": "c", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": seconds}],
        assets={"a": {"file_key": "a.mp4"}},
    )


def test_高画质档和短片不走硬件(monkeypatch, tmp_path):
    monkeypatch.setattr(rx.settings, "hw_encode", True)
    monkeypatch.setattr(rx, "_available_hw_encoder", lambda: "h264_videotoolbox")
    monkeypatch.setattr(rx, "_hw_encoder_works", lambda encoder, output: True)
    long_standard = build_render_plan(
        sequence_id="s", revision=1, width=64, height=36, fps=10, crf=20,
        clips=[{"id": "c", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 60}],
        assets={"a": {"file_key": "a.mp4"}},
    )
    assert rx._choose_hw_encoder(long_standard) == "h264_videotoolbox"

    high = replace(long_standard, output=replace(long_standard.output, crf=18, encode_preset="medium"))
    short = replace(long_standard, timeline_duration=10.0)
    assert rx._choose_hw_encoder(high) is None, "「高画质」要的是画质,走软件"
    assert rx._choose_hw_encoder(short) is None, "短片硬件开会话的开销抵掉了它的速度"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_起不来的硬件编码器在开跑之前就被挡下_不再整条从_0_重来(monkeypatch, tmp_path):
    """此前整条用硬件跑挂了,才用软件从头再跑一遍 —— 读素材、建滤镜图、渲字幕全白花。"""
    plan = _long_plan(tmp_path, crf=20)
    monkeypatch.setattr(rx.settings, "hw_encode", True)
    #: 一个 ffmpeg 不认的编码器:列表里有它,开编那一刻才失败 —— 和没显卡的 NVENC 同一个形状。
    monkeypatch.setattr(rx, "_available_hw_encoder", lambda: "h264_unavailable_hw")
    phases: list[str] = []
    out = tmp_path / "o.mp4"
    with patch.object(rx, "popen_text", wraps=rx.popen_text) as spawned:
        rx.execute_render(plan, lambda key: tmp_path / key, out, on_phase=phases.append)
    assert spawned.call_count == 1, "导出跑了不止一遍"
    assert "libx264" in spawned.call_args.args[0]
    assert rx.PHASE_FALLBACK not in phases
    assert out.stat().st_size > 0


def _ssim(a: Path, b: Path) -> float:
    err = subprocess.run(["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "[0:v][1:v]ssim", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"All:(\S+)", err)[-1])


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_videotoolbox_的档位名副其实(monkeypatch, tmp_path):
    """真编一遍:硬件「标准」不比软件「标准」差,硬件「体积小」不比软件「体积小」差。"""
    monkeypatch.setattr(rx.settings, "hw_encode", True)
    probe = _long_plan(tmp_path, crf=20, seconds=2, size="640x360")
    if not rx._hw_encoder_works("h264_videotoolbox", probe.output):
        pytest.skip("这台机器没有能用的 VideoToolbox(-q:v 只有 Apple Silicon 认)")
    plan = _long_plan(tmp_path, crf=20, seconds=6, size="640x360")
    source = tmp_path / "a.mp4"

    scores: dict[tuple[int, bool], float] = {}
    for crf in (20, 26):
        tier = replace(plan, output=replace(plan.output, crf=crf))
        for software in (True, False):
            out = tmp_path / f"o-{crf}-{software}.mp4"
            command = rx.build_ffmpeg_command(tier, lambda key: tmp_path / key, out, force_software=software)
            assert ("h264_videotoolbox" in command) is not software
            subprocess.run(command, check=True, capture_output=True)
            scores[crf, software] = _ssim(out, source)
    assert scores[20, False] >= scores[20, True] - 0.002, scores
    assert scores[26, False] >= scores[26, True] - 0.002, scores
    assert scores[20, False] > scores[26, True], "硬件「标准」不该比软件「体积小」还差"
