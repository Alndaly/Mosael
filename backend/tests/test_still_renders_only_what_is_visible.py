"""取当前帧只渲**这一刻看得见的东西**,而画出来的和成片同一时刻那一帧是同一帧。

审查实测:300 秒的时间线,取第 5 秒和第 290 秒都要 3 秒;再加 200 条字幕要 63 秒。原因是取一帧
走的是整条成片的滤镜图 —— 基底轨每一段都从头解一遍、整条声音解出来丢进 null、每条字幕都先
起浏览器画成 PNG 再挂进滤镜图,而这一刻只用得上其中一段画面和一条字幕。

只渲局部最怕的是**画面悄悄不一样**(关键帧、淡入淡出、变速都按段内时间算,段从中间开始解,
时间就可能整体错开)。所以这里拿真 ffmpeg 渲一条无损成片,逐个时刻和取出来的帧比。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.media.render_executor import build_ffmpeg_command, execute_render, render_still, still_plan
from app.media.render_plan import build_render_plan

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _timeline(**extra):
    #: 每一类按段内时间算的东西都放一份:淡入 + 位置关键帧、变速 + 投影、上层的透明度关键帧、
    #: 段之间的空白。
    return build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30, crf=0, encode_preset="ultrafast",
        clips=[
            {"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0.5, "src_out": 2.5},
            {"id": "c2", "asset_id": "a", "timeline_start": 2, "src_in": 1.0, "src_out": 4.0,
             "effects": {"video_fade_in": 1.0},
             "transform": {"keyframes": [{"t": 0, "x": -0.5, "scale": 0.6}, {"t": 1, "x": 0.5, "scale": 0.9}]}},
            {"id": "c3", "asset_id": "a", "timeline_start": 5.5, "src_in": 1.0, "src_out": 5.0, "speed": 2.0,
             "transform": {"scale": 0.7},
             "effects": {"appearance": {"shadow": {"enabled": True, "opacity": 0.8, "blur": 6,
                                                   "offset_x": 8, "offset_y": 6}}}},
        ],
        overlay_clips=[
            {"id": "o1", "asset_id": "a", "timeline_start": 3.0, "src_in": 2.0, "src_out": 5.0,
             "transform": {"scale": 0.3, "x": 0.6, "y": -0.5,
                           "keyframes": [{"t": 0, "opacity": 0.2}, {"t": 1, "opacity": 1.0}]}},
        ],
        assets={"a": {"file_key": "a.mp4"}},
        **extra,
    )


def _psnr(a: Path, b: Path) -> float:
    err = subprocess.run(
        ["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    value = re.findall(r"average:(\S+)", err)[-1]
    return float("inf") if value == "inf" else float(value)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
@pytest.mark.parametrize("fill_mode", ["cover", "blur"])
def test_取出来的帧和成片同一时刻那一帧是同一帧(tmp_path: Path, fill_mode: str) -> None:
    #: 每一帧的亮度都不一样(帧号 × 12),错开一帧 PSNR 掉到 20 上下;同一帧只差 JPEG 的损失(淡入到一半、
    #: 底下垫着模糊背景的那一帧最差,三十出头 —— 走整条成片滤镜图取出来的也是这个数)。
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=320x180:r=30:d=6",
         "-vf", "geq=lum='mod(N*12+X/4,200)+20':cb=128:cr=128",
         "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p", str(tmp_path / "a.mp4")],
        check=True,
    )
    plan = _timeline(fill_mode=fill_mode)
    resolve = lambda key: tmp_path / key  # noqa: E731
    movie = tmp_path / "movie.mp4"
    execute_render(plan, resolve, movie)

    #: 4.9 和 7.2 落在段内一秒之后:那一段从中间开始解(段内时间要补回去)。
    for at in (1.0, 2.5, 3.7, 4.9, 5.2, 6.4, 7.2):
        still = render_still(plan, resolve, tmp_path / f"still-{at}.jpg", at)
        same, neighbour = tmp_path / f"movie-{at}.png", tmp_path / f"movie-{at}-next.png"
        for when, target in ((at, same), (at + 1 / 30, neighbour)):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(movie), "-ss", f"{when:.3f}",
                            "-frames:v", "1", str(target)], check=True)
        assert _psnr(still, same) > 30, f"{at}s 取出来的帧和成片同一时刻那一帧不一样"
        if at != 5.2:  # 5.2 落在空白里:前后两帧都是黑的,比不出差别
            assert _psnr(still, neighbour) < _psnr(still, same) - 5, f"{at}s 这个比法分不出相邻两帧"


def test_只留这一刻看得见的东西() -> None:
    subtitles = [{"id": f"s{i}", "asset_id": None, "timeline_start": i * 1.0, "src_in": 0, "src_out": 0.9,
                  "text_override": f"第{i}句"} for i in range(7)]
    plan = _timeline(subtitle_clips=subtitles, audio_clips=[
        {"id": "m", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 6, "gain": 1.0},
    ])
    visible = still_plan(plan, 4.2)

    #: 4.2 落在第二段(2~5)里:前面并成一段空白保住位置,后面的不要。
    assert [(s.kind, s.duration) for s in visible.video_segments] == [("gap", 2.0), ("clip", 3.0)]
    assert len(visible.overlays) == 1
    assert [s.text for s in visible.subtitles] == ["第4句"], "只该光栅化这一刻的那条字幕"
    assert visible.audio_overlays == ()

    #: 2.5 时上层还没出现,第 2 句字幕在 2.0~2.9。
    early = still_plan(plan, 2.5)
    assert early.overlays == () and [s.text for s in early.subtitles] == ["第2句"]


def test_取一帧只开这一刻用得上的输入_也不建声音() -> None:
    plan = _timeline(audio_clips=[
        {"id": "m", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 6, "gain": 1.0},
    ])
    command = build_ffmpeg_command(still_plan(plan, 6.4), lambda key: Path("/x") / key, Path("/x/f.jpg"),
                                   still_at=6.4)
    assert command.count("-i") == 1, f"6.4s 只有第三段在画面上:{command}"
    graph = command[command.index("-filter_complex") + 1]
    assert ":a]" not in graph and "anullsrc" not in graph and "amix" not in graph, "一张图不该建声音那一路"
    assert command.count("-map") == 1
