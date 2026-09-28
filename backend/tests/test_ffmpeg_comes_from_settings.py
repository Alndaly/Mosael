"""起 ffmpeg / ffprobe 一律用 `settings.ffmpeg` / `settings.ffprobe`,不写死程序名。

`core/config` 允许用 MOSAEL_FFMPEG / MOSAEL_FFPROBE 指到完整版(Homebrew 的 core ffmpeg 是精简版,
没有 libass,烧字幕就靠它)。有 11 处命令行直接写 `["ffmpeg", …]`:设了之后,缩略图、帧条、波形、
取帧、转写抽音轨、克隆参考音频、截取、口播拼接照样去跑 PATH 上那一个 —— 同一台机器上两个 ffmpeg,
哪条路用哪个全看写代码的人记没记得。
"""

from __future__ import annotations

import ast
from pathlib import Path

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

APP = Path(__file__).resolve().parent.parent / "app"
PROGRAMS = {"ffmpeg", "ffprobe"}


def test_no_command_line_hardcodes_the_ffmpeg_binary() -> None:
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.List)
                and node.elts
                and isinstance(node.elts[0], ast.Constant)
                and node.elts[0].value in PROGRAMS
            ):
                offenders.append(f"{path.relative_to(APP.parent)}:{node.lineno}")
    assert offenders == [], "命令行第一项写死了程序名,改用 settings.ffmpeg / settings.ffprobe:\n  " + "\n  ".join(offenders)
