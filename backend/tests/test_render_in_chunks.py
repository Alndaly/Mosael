"""层多的时间线分块渲染,再无损接起来 —— 接出来的和一次渲完的逐帧、逐采样一样。

一次 ffmpeg 挂的每一层(底轨片段、上层片段、音频轨片段、花字)是一路输入加一条滤镜链,1080p 下二三十 MB:
300 段不同素材的时间线一次渲要 6.4 GB 内存;macOS 从图形界面起的进程默认只能开 256 个文件,250 段以上
ffmpeg 直接「Too many open files」,导出失败。分块之后每块各起一次 ffmpeg(300 段:2.3 GB,开得起)。

分块最怕的是**接缝**:跨过切点的上层片段(关键帧、淡入)、音频轨片段(淡入淡出)、字幕要在两块里接得严丝合缝;
声音的限幅 / 响度标准化是跨整条的状态,不能每块各算各的。这里拿同一条时间线一次渲、分块渲各出一份
(无损编码),逐帧逐采样比。
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from app.core.config import settings
from app.media import render_executor
from app.media.render_executor import _chunk_windows, execute_render
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

W, H, FPS, RATE = 96, 54, 30, 48000


def _sources(tmp_path: Path) -> None:
    #: 底轨素材每一帧亮度不同,声音 440 Hz;上层素材是测试图;音频轨是 660 Hz。
    #:
    #: 底轨的 AAC 关掉 PNS(感知噪声替代)。PNS 的频带里没有编码采样,解码器拿一个随机数发生器现造噪声,而发生器
    #: 的状态从解码器打开那一刻起一帧帧往下传 —— 同一段声音从哪里开始解,造出来的噪声就不一样。分块渲时每块的
    #: 底轨从这一块的第一段起解,整条渲时从整条的第一段起解,两边在 PNS 频带上差一点噪声(实测最大 1.3e-5,约
    #: −98 dBFS),逐采样比就过不了;整条渲换个起点也一样会变,这不是接缝的毛病。ffmpeg 6.1 / 7.1 的编码器给这段
    #: 440 Hz 用了 PNS,9.0 的没用 —— 所以这条测试此前只在旧版上红。关掉它,解码和从哪里起解无关,逐采样相等
    #: 才量得到接缝本身。
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=s={W}x{H}:r={FPS}:d=30",
                    "-f", "lavfi", "-i", f"sine=f=440:r={RATE}:d=30", "-vf", "geq=lum='mod(N*7,200)+20':cb=128:cr=128",
                    "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-aac_pns", "0", str(tmp_path / "base.mp4")], check=True, timeout=60)
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={FPS}:d=8",
                    "-pix_fmt", "yuv420p", str(tmp_path / "pip.mp4")], check=True, timeout=60)
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=660:r={RATE}:d=10",
                    str(tmp_path / "music.wav")], check=True, timeout=60)


def _plan():
    #: 底轨 12 段跳剪,段长 0.9 秒(不在帧格上的也有:第 5 段 0.95 秒),第 6 段长 4 秒、有一个切点落在它中间
    #: (那一块从段内跳过一截开始解);上层两段带关键帧和淡入;音频轨一段带淡入淡出、跨好几块;字幕若干。
    #: 分块阈值调到 6 层,切成好几块,每个切点都有东西跨过去。
    clips = []
    at = 0.0
    for i in range(12):
        length = {5: 0.95, 6: 4.0}.get(i, 0.9)
        clips.append({"id": f"c{i}", "asset_id": "b", "timeline_start": round(at, 6),
                      "src_in": 1.0 + i * 2.0, "src_out": round(1.0 + i * 2.0 + length, 6)})
        at += length
    return build_render_plan(
        sequence_id="s", revision=1, width=W, height=H, fps=FPS, crf=0, encode_preset="ultrafast",
        clips=clips,
        overlay_clips=[
            {"id": f"o{i}", "asset_id": "p", "timeline_start": start, "src_in": 0.5, "src_out": 3.5,
             "transform": {"scale": 0.4, "x": 0.5, "y": -0.4, "keyframes": [{"t": 0, "opacity": 0.3}, {"t": 1, "opacity": 1.0}]},
             "effects": {"video_fade_in": 0.6}}
            for i, start in enumerate((1.2, 7.4))
        ],
        audio_clips=[{"id": "m", "asset_id": "w", "timeline_start": 0.5, "src_in": 0.0, "src_out": 10.0, "gain": 0.5,
                      "effects": {"fade_in": 1.0, "fade_out": 2.0}}],
        subtitle_clips=[{"id": f"t{i}", "asset_id": None, "timeline_start": i * 1.1, "src_in": 0, "src_out": 1.0,
                         "text_override": f"第{i}句"} for i in range(9)],
        assets={"b": {"file_key": "base.mp4"}, "p": {"file_key": "pip.mp4"}, "w": {"file_key": "music.wav"}},
    )


def _rasterize(plan, workdir: Path) -> dict:
    """浏览器那一步换成直接画 PNG(这里测的是分块,不是排版)。"""
    def png(name: str, size: tuple[int, int], rgba: tuple[int, int, int, int]) -> tuple[Path, int, int]:
        Image.new("RGBA", size, rgba).save(workdir / name)
        return workdir / name, *size

    return {"subtitles": [png(f"s{i}.png", (30 + 2 * i, 8), (255, 255, 255, 200)) for i in range(len(plan.subtitles))],
            "text_overlays": [], "ai_labels": []}


def _decode(path: Path) -> tuple[np.ndarray, np.ndarray]:
    video = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True, timeout=60).stdout
    audio = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a", "-f", "f32le", "-"],
                           capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(video, np.uint8).reshape(-1, H, W, 3), np.frombuffer(audio, np.float32)


def test_层不多不分块_层多时切在帧格上_每块挂的层不超过上限(monkeypatch) -> None:
    plan = _plan()
    assert _chunk_windows(plan) is None, "26 层以下一次渲得下,不该分块"
    monkeypatch.setattr(render_executor, "_CHUNK_LAYERS", 6)
    windows = _chunk_windows(plan)
    assert windows is not None and len(windows) >= 3
    assert windows[0][0] == 0 and windows[-1][1] == plan.timeline_duration
    for (_a, b), (c, _d) in zip(windows, windows[1:]):
        assert b == c, "块与块之间要接上"
        assert abs(b * FPS - round(b * FPS)) < 1e-9, "切点要在帧格上"


def test_分块渲出来的和一次渲完的逐帧逐采样一样(monkeypatch, tmp_path: Path) -> None:
    _sources(tmp_path)
    plan = _plan()
    resolve = lambda key: tmp_path / key  # noqa: E731
    monkeypatch.setattr(render_executor, "_rasterize_text", _rasterize)

    whole = tmp_path / "whole.mp4"
    execute_render(plan, resolve, whole)

    monkeypatch.setattr(render_executor, "_CHUNK_LAYERS", 6)
    chunked = tmp_path / "chunked.mp4"
    with patch.object(render_executor, "popen_text", wraps=render_executor.popen_text) as spawned:
        execute_render(plan, resolve, chunked)
    runs = [call.args[0] for call in spawned.call_args_list]
    windows = _chunk_windows(plan)
    assert windows is not None and len(runs) == len(windows) + 1, "每块一次 ffmpeg,最后接一次"
    #: 每块只挂这一截用得上的层:底轨一路(同一素材共用;段内跳过一截时声音另一路)+ 跨进来的上层片段
    #: + 音频轨 + 字幕轨。
    assert all(run.count("-i") <= 6 for run in runs[:-1]), [run.count("-i") for run in runs]
    #: 有一块从长段中间开始:画面从段内跳过一截起解,声音另开一路从段头解(只有声音、没有画面的那一路)。
    start, end = next((a, b) for a, b in windows if render_executor._window(plan, a, b).skip > 0)
    command = render_executor.build_ffmpeg_command(plan, resolve, tmp_path / "c.mp4", chunk=(start, end),
                                                   audio_path=tmp_path / "c.wav", workdir=tmp_path)
    inputs = [command[k + 1] for k, arg in enumerate(command) if arg == "-i"]
    graph = command[command.index("-filter_complex") + 1]
    assert any(f"[{n}:a]" in graph and f"[{n}:v]" not in graph for n, path in enumerate(inputs)
               if path.endswith("base.mp4")), graph

    whole_video, whole_audio = _decode(whole)
    chunked_video, chunked_audio = _decode(chunked)
    assert len(chunked_video) == len(whole_video) == math.ceil(plan.timeline_duration * FPS - 1e-6), "片长之前的每一帧都在"
    differ = [k for k in range(len(whole_video)) if not np.array_equal(whole_video[k], chunked_video[k])]
    assert not differ, f"这些帧和一次渲完的不一样:{differ}(切点在 {[round(a * FPS) for a, _ in windows]})"
    assert len(chunked_audio) == len(whole_audio)
    assert np.array_equal(chunked_audio, whole_audio), "声音和一次渲完的不一样"
