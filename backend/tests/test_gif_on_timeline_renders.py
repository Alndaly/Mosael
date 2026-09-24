"""时间线上有 GIF 时,取当前帧和导出都要跑得通。

踩出来的形状:用户时间线上一段 AI 生图(缩放 + 旋转)接一段「录屏转 GIF」,点「存下这一帧」
弹「存不下这一帧 / 取当前帧失败」。根因不在变换框,也不在播放头那一刻画的是谁 ——
**图片一律 `-loop 1`,而 `-loop` 是 image2 解复用器私有的选项**。GIF 走 gif 解复用器,
ffmpeg 连输入都打不开(「Option loop not found」),于是只要时间线上**任何位置**有一段 GIF,
整条滤镜图就起不来:取哪一帧都失败,导出也失败。

界面上那句话也没说原因 —— ffmpeg 的原话只进了后端日志。所以这里也钉住:失败时带上原因。
"""

from __future__ import annotations

RATCHET = True

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.media import render_executor
from app.media.render_executor import RenderExecutionError, _image_loop_args, render_still
from app.media.render_plan import build_render_plan

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_静态图用_loop_GIF_用通用的_stream_loop() -> None:
    """`-loop` 只有 image2 认;GIF/AVIF 走别的解复用器,必须换成任何解复用器都认的那个。"""
    assert _image_loop_args(Path("a.png"), 4)[:2] == ["-loop", "1"]
    assert _image_loop_args(Path("a.JPG"), 4)[:2] == ["-loop", "1"]
    for name in ("a.gif", "a.avif"):
        args = _image_loop_args(Path(name), 4)
        assert "-loop" not in args, f"{name} 走的不是 image2 解复用器,-loop 会让 ffmpeg 打不开它"
        assert args[:2] == ["-stream_loop", "-1"]
        assert "-t" in args, "无限循环必须限时长,否则 concat 永远卡在这一段"
    assert _image_loop_args(Path("a.mp4"), 4) == []


def _plan(gif_key: str, png_key: str):
    #: 用户那条时间线的形状:底轨先一张缩放 + 旋转过的图,再一段 GIF。
    return build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[
            {"id": "c1", "asset_id": "png", "timeline_start": 0, "src_in": 0, "src_out": 2,
             "transform": {"scale": 0.5, "x": -0.06, "y": -0.08, "rotation": -54.0, "opacity": 1.0}},
            {"id": "c2", "asset_id": "gif", "timeline_start": 2, "src_in": 0, "src_out": 3,
             "transform": {"scale": 0.1, "x": 0.0, "y": 0.0, "rotation": 0.0, "opacity": 1.0}},
        ],
        assets={"png": {"file_key": png_key}, "gif": {"file_key": gif_key}},
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_时间线上有_GIF_时能取帧_取在图片那段也一样(tmp_path: Path) -> None:
    gif = tmp_path / "clip.gif"
    png = tmp_path / "still.png"
    #: GIF 故意比片段短(1 秒 vs 3 秒):循环才能撑满,播一遍就断流的话后半段没画面。
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=64x36:d=1:r=10",
                    "-loop", "0", str(gif)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=64x64",
                    "-frames:v", "1", str(png)], check=True)
    plan = _plan(gif.name, png.name)
    resolve = lambda key: tmp_path / key  # noqa: E731

    #: 取在图片那段(1s)—— GIF 在别处也会拖垮整条命令;取在 GIF 循环到第三遍的地方(4.5s)。
    for at in (1.0, 4.5):
        out = tmp_path / f"frame-{at}.jpg"
        render_still(plan, resolve, out, at)
        assert out.is_file() and out.stat().st_size > 0, f"{at}s 没取出帧"


def test_ffmpeg_失败时_错误里带上它说的原因(tmp_path: Path) -> None:
    """只说「取当前帧失败」的话,界面上看不出任何线索,原因只在后端日志里。"""
    plan = _plan("clip.gif", "still.png")
    failed = subprocess.CompletedProcess(
        args=["ffmpeg"], returncode=8, stdout="",
        stderr="Error opening input file /x/clip.gif.\nError opening input files: Option not found\n",
    )
    with (
        patch.object(render_executor, "_rasterize_text", return_value=None),
        patch.object(render_executor, "run_logged", return_value=failed),
        pytest.raises(RenderExecutionError) as caught,
    ):
        render_still(plan, lambda key: tmp_path / key, tmp_path / "frame.jpg", 1.0)

    assert caught.value.key == "renderErr_frameFailed"
    assert "Option not found" in str(caught.value), f"原因没带出来:{caught.value}"
    assert "Option not found" in caught.value.stderr_tail
