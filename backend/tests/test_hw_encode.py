"""导出编码参数选择:硬件优先 + 软件回落 + 码率映射。

真机是否有硬件编码器不可控,所以这里只测纯逻辑:_target_bitrate_kbps 的映射、
_hw_encode_args 各家参数、以及 _video_encode_args 在 hw_encode 开关/探测结果下的取舍。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.media import render_executor as rx


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


@pytest.mark.parametrize("encoder", rx._HW_ENCODER_PRIORITY)
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
