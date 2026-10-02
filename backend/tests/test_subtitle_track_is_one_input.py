"""字幕(和能并进来的静止花字)合成**一路**透明轨叠一次,不再每条一路 PNG 输入 + 一个整幅 overlay。

此前每条字幕是一路 `-loop` 的 PNG 加一个 overlay;overlay 不在自己的时间窗里也要逐帧走一遍,字幕越多
每一帧越慢 —— 审查估算 1 小时 1000 条字幕多花约 50 分钟,同一条 270 秒、200 条字幕的时间线实测导出
105.9 秒,合成一条轨后 16.9 秒。

合成之后最怕的是**画面悄悄变了**:哪一帧出现、哪一帧消失(右开、挪半帧的边界),叠在谁上面(字幕在
所有花字下面;带动画的花字压在它前面的静止花字上面),落在哪个像素上。这里用真 ffmpeg 逐帧看。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.core.config import settings
from app.media import render_executor
from app.media.render_executor import _subtitle_overlay_pos, build_ffmpeg_command, compose_text_layers
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

W, H, FPS = 320, 180, 10


def _png(path: Path, size: tuple[int, int], rgba: tuple[int, int, int, int]) -> tuple[Path, int, int]:
    Image.new("RGBA", size, rgba).save(path)
    return path, *size


def _frames(path: Path) -> np.ndarray:
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(int)


def _is(pixel: np.ndarray, rgb: tuple[int, int, int]) -> bool:
    return bool(np.abs(pixel - np.array(rgb)).max() < 40)


def _render(tmp_path: Path, plan, pngs: dict) -> np.ndarray:
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={FPS}:d=6",
                    "-pix_fmt", "yuv420p", str(tmp_path / "black.mp4")], check=True, timeout=30)
    out = tmp_path / "out.mp4"
    layers = compose_text_layers(plan, pngs, tmp_path)
    command = build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True, text_layers=layers)
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return _frames(out)


def _plan(subtitles, text_overlays=()):
    return build_render_plan(
        sequence_id="s", revision=1, width=W, height=H, fps=FPS,
        clips=[{"id": "base", "asset_id": "k", "timeline_start": 0, "src_in": 0, "src_out": 6}],
        assets={"k": {"file_key": "black.mp4"}},
        subtitle_clips=[{"id": f"s{i}", "asset_id": None, "timeline_start": start, "src_in": 0, "src_out": length,
                         "text_override": text} for i, (text, start, length) in enumerate(subtitles)],
        text_overlays=list(text_overlays),
    )


def test_字幕不管多少条_都只占一路输入一个叠加(tmp_path: Path) -> None:
    plan = _plan([(f"第{i}句", i * 0.1, 0.1) for i in range(50)])
    pngs = {"subtitles": [_png(tmp_path / f"{i}.png", (40 + i, 10), (255, 255, 255, 255)) for i in range(50)]}
    command = build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4",
                                   text_layers=compose_text_layers(plan, pngs, tmp_path))
    graph = command[command.index("-filter_complex") + 1]
    assert command.count("-i") == 2 and graph.count("overlay=") == 1, "50 条字幕该是一路输入、一个叠加"


def test_字幕一路输入_出现消失的帧和逐条叠时一样(tmp_path: Path) -> None:
    """三条字幕:红、绿(紧挨着红)、隔一段空白再一条红(和第一条同一句,共用一张图)。
    边界在帧格上(0.1 秒一帧):第 k 帧在 [start, end) 里才出现。"""
    plan = _plan([("红", 0.5, 1.0), ("绿", 1.5, 1.0), ("红", 3.5, 0.5)])
    red = _png(tmp_path / "red.png", (60, 20), (255, 0, 0, 255))
    green = _png(tmp_path / "green.png", (40, 10), (0, 255, 0, 255))
    pngs = {"subtitles": [red, green, red]}
    command = build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4",
                                   text_layers=compose_text_layers(plan, pngs, tmp_path))
    assert command.count("-i") == 2, "字幕该只占一路输入(底轨一路 + 字幕轨一路)"
    assert str(red[0]) not in command and str(green[0]) not in command

    frames = _render(tmp_path, plan, pngs)
    rx, ry = _subtitle_overlay_pos(plan.subtitle_style, 60, 20, W, H)
    gx, gy = _subtitle_overlay_pos(plan.subtitle_style, 40, 10, W, H)
    red_only = (ry + 2, rx + 2)  # 红块的左上角:绿块盖不到
    green_px = (gy + 5, gx + 20)
    expect = {4: "none", 5: "red", 14: "red", 15: "green", 24: "green", 25: "none", 34: "none", 35: "red",
              39: "red", 40: "none", 59: "none"}
    for k, what in expect.items():
        frame = frames[k]
        if what == "red":
            assert _is(frame[red_only], (255, 0, 0)), f"第 {k} 帧该有红字幕"
        elif what == "green":
            assert _is(frame[green_px], (0, 255, 0)) and _is(frame[red_only], (0, 0, 0)), f"第 {k} 帧该只有绿字幕"
        else:
            assert _is(frame[red_only], (0, 0, 0)) and _is(frame[green_px], (0, 0, 0)), f"第 {k} 帧不该有字幕"
    assert len(frames) == 60, "成片时长变了"


def test_带动画的花字压在它前面的静止花字上面_静止花字不并进轨(tmp_path: Path) -> None:
    """叠的次序:字幕 < 花字(按出现的先后)。并进轨的字都在轨里 —— 轨叠在所有单独叠的花字**下面**。
    所以一条静止花字只要和它前面一条带动画的花字时间上重叠,就不能并,否则它被压到那条下面去。"""
    moving = {"id": "m", "asset_id": None, "timeline_start": 0.0, "src_in": 0, "src_out": 4, "text_override": "动",
              "transform": {"keyframes": [{"t": 0, "x": 0.0}, {"t": 1, "x": 0.001}]}}
    still_on_top = {"id": "s", "asset_id": None, "timeline_start": 1.0, "src_in": 0, "src_out": 2,
                    "text_override": "静"}
    still_later = {"id": "l", "asset_id": None, "timeline_start": 4.5, "src_in": 0, "src_out": 1,
                   "text_override": "后"}
    plan = _plan([("字", 0.0, 6.0)], [moving, still_on_top, still_later])
    sub = _png(tmp_path / "sub.png", (100, 20), (255, 255, 255, 255))
    blue = _png(tmp_path / "blue.png", (80, 40), (0, 0, 255, 255))
    red = _png(tmp_path / "red.png", (40, 20), (255, 0, 0, 255))
    green = _png(tmp_path / "green.png", (40, 20), (0, 255, 0, 255))
    pngs = {"subtitles": [sub], "text_overlays": [blue, red, green]}
    layers = compose_text_layers(plan, pngs, tmp_path)
    assert [k for k, *_ in layers.text_overlays] == [0, 1], "和带动画的那条重叠的静止花字不该并进轨"

    frames = _render(tmp_path, plan, pngs)
    centre = (H // 2, W // 2)
    assert _is(frames[5][centre], (0, 0, 255)), "0.5 秒:只有会动的蓝块"
    assert _is(frames[15][centre], (255, 0, 0)), "1.5 秒:后出现的静止红块压在蓝块上面"
    assert _is(frames[47][centre], (0, 255, 0)), "4.7 秒:并进轨的静止绿块在原位"


def test_同一句字幕只渲一次(monkeypatch, tmp_path: Path) -> None:
    """「一框一段」把同一句话切成好几段、或者隔一阵又出现一次,都是同一张图:浏览器只画一次。"""
    drawn: list[str] = []

    class FakeRasterizer:
        def __init__(self, w, h):
            pass

        def available(self):
            return True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def render_subtitle(self, text, style):
            drawn.append(text)
            path = tmp_path / f"draw{len(drawn)}.png"
            Image.new("RGBA", (30, 10), (255, 255, 255, 255)).save(path)
            return path.read_bytes()

    monkeypatch.setattr(settings, "text_rasterize", True)
    monkeypatch.setattr("app.media.text_render.TextRasterizer", FakeRasterizer)
    plan = _plan([("一", 0.0, 1.0), ("二", 1.0, 1.0), ("一", 2.0, 1.0), ("一", 4.0, 1.0)])
    result = render_executor._rasterize_text(plan, tmp_path)
    assert drawn == ["一", "二"]
    assert result is not None and [png for png, *_ in result["subtitles"]][0] == result["subtitles"][2][0]


def test_起止不在帧格上_每一帧都按右开的边界出现消失(tmp_path: Path) -> None:
    """50fps(一帧 20 毫秒)、起止都不在帧格上:轨里的时间要精确到毫秒 —— 不给 ffconcat 定时基的话,
    图片按 25fps 取整,边界会差出 40 毫秒,也就是整整两帧。"""
    fps, w, h = 50, 160, 90
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:r={fps}:d=2",
                    "-pix_fmt", "yuv420p", str(tmp_path / "black.mp4")], check=True, timeout=30)
    windows = [(0.333, 0.377), (0.71, 0.423), (1.371, 0.529)]
    plan = build_render_plan(
        sequence_id="s", revision=1, width=w, height=h, fps=fps,
        clips=[{"id": "base", "asset_id": "k", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"k": {"file_key": "black.mp4"}},
        subtitle_clips=[{"id": f"s{i}", "asset_id": None, "timeline_start": start, "src_in": 0, "src_out": length,
                         "text_override": f"第{i}句"} for i, (start, length) in enumerate(windows)],
    )
    white = _png(tmp_path / "white.png", (40, 10), (255, 255, 255, 255))
    out = tmp_path / "out.mp4"
    layers = compose_text_layers(plan, {"subtitles": [white] * 3}, tmp_path)
    subprocess.run(build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True, text_layers=layers),
                   check=True, capture_output=True, timeout=60)
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w)
    x, y = _subtitle_overlay_pos(plan.subtitle_style, 40, 10, w, h)
    seen = [bool(frame[y + 5, x + 20] > 128) for frame in frames]
    #: _shown_during 的 [start − 半帧, end − 半帧):第 k 帧在 start·fps − ½ ≤ k < end·fps − ½ 时出现。
    expected = [any(start * fps - 0.5 <= k < (start + length) * fps - 0.5 for start, length in windows)
                for k in range(len(frames))]
    assert seen == expected, [k for k, (a, b) in enumerate(zip(seen, expected)) if a != b]
