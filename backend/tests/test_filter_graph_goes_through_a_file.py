"""滤镜图走文件,命令行不随时间线变长。

滤镜图每段、每层、每条字幕都是几百个字符,而 Windows 上一条命令行最长 32767 个字符
(CreateProcess 的上限)。审查实测一两百段的时间线就过线了 —— 那里 ffmpeg 根本起不来,
报的还是看不出原因的「文件名或扩展名太长」。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.media import render_executor
from app.media.render_executor import _filter_script_flag, build_ffmpeg_command, execute_render
from app.media.render_plan import build_render_plan

HAS_FFMPEG = shutil.which("ffmpeg") is not None
WINDOWS_COMMAND_LINE_LIMIT = 32767


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_这台机器的_ffmpeg_认我们选的那种写法(tmp_path: Path) -> None:
    """`-/filter_complex`(7.0 起)和 `-filter_complex_script`(8.0 删了)各认一半版本,
    选错了就是整条导出起不来。拿真 ffmpeg 跑一次选出来的写法。"""
    script = tmp_path / "graph.txt"
    script.write_text("anullsrc,atrim=0:0.1[a]", encoding="utf-8")
    flag = _filter_script_flag(settings.ffmpeg)
    ran = subprocess.run([settings.ffmpeg, "-v", "error", flag, str(script), "-map", "[a]", "-f", "null", "-"],
                         capture_output=True, text=True)
    assert ran.returncode == 0, f"{flag} 这台 ffmpeg 不认:{ran.stderr}"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_一百多段的时间线_命令行不过_Windows_的上限_照样渲得出(tmp_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=64x36:r=10:d=1",
         "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(tmp_path / "a.mp4")],
        check=True,
    )
    #: 片段之间隔着空白:片段和空白各是一段,滤镜图过 3 万字。
    clips = [{"id": f"c{i}", "asset_id": "a", "timeline_start": i * 0.2, "src_in": 0, "src_out": 0.1}
             for i in range(120)]
    plan = build_render_plan(sequence_id="s", revision=1, width=64, height=36, fps=10, clips=clips,
                             assets={"a": {"file_key": "a.mp4"}}, encode_preset="ultrafast")
    resolve = lambda key: tmp_path / key  # noqa: E731
    inline = build_ffmpeg_command(plan, resolve, tmp_path / "o.mp4")
    graph = inline[inline.index("-filter_complex") + 1]
    assert len(graph) > WINDOWS_COMMAND_LINE_LIMIT, "时间线不够长,测不到要测的东西"

    out = tmp_path / "o.mp4"
    with patch.object(render_executor, "popen_text", wraps=render_executor.popen_text) as spawned:
        execute_render(plan, resolve, out)
    argv = spawned.call_args.args[0]
    assert sum(len(part) + 1 for part in argv) < WINDOWS_COMMAND_LINE_LIMIT, "滤镜图还在命令行上"
    assert graph not in argv
    script = Path(argv[argv.index(_filter_script_flag(settings.ffmpeg)) + 1])
    assert not script.exists(), "跑完了滤镜图文件还留着"

    probed = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout)
    assert abs(float(probed["format"]["duration"]) - plan.timeline_duration) < 0.15
