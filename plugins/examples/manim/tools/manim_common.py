"""几个工具都要用的小东西:说人话、报进度、看取消、从一堆输出里挑出原因。只用标准库。"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

#: 往宿主报一行(NDJSON):进度 `{"event": "progress", …}`,或者最后的结果 `{"ok": …}`。
Emit = Callable[[dict[str, Any]], None]


class PluginError(RuntimeError):
    """说得出口的失败,原样进工具结果。"""


class Cancelled(PluginError):
    """宿主建了取消文件:用户停了这次调用,或者预算用完了。"""


def is_zh(locale: str) -> bool:
    return str(locale or "").replace("_", "-").split("-")[0].lower() == "zh"


def line(locale: str, zh: str, en: str) -> str:
    return zh if is_zh(locale) else en


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


_last_progress: list = [None]


def progress(send: Emit, fraction: float, message: str) -> None:
    """报一次进度。和上一次一模一样的不再报 —— 进度条一秒重画十几次,宿主要的是「变了」。"""
    event = {"event": "progress", "progress": round(max(0.0, min(1.0, fraction)), 4), "message": message[:200]}
    if event == _last_progress[0]:
        return
    _last_progress[0] = event
    send(event)


def cancel_requested() -> bool:
    """宿主建了取消文件没有(`MOSAEL_PLUGIN_CANCEL_FILE`)。不在任务里跑时没有这个变量,永远是 False。"""
    path = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "").strip()
    return bool(path) and Path(path).exists()


def data_dir(locale: str) -> Path:
    raw = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "").strip()
    if not raw:
        raise PluginError(line(
            locale,
            "宿主没有给插件持久目录(MOSAEL_PLUGIN_DATA_DIR)—— 请把 Mosael 升级到最新版。",
            "The host gave no persistent plugin directory (MOSAEL_PLUGIN_DATA_DIR). Please update Mosael.",
        ))
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(locale: str) -> Path:
    raw = os.environ.get("MOSAEL_PLUGIN_OUTPUT_DIR", "").strip()
    if not raw:
        raise PluginError(line(locale, "宿主没有给产出目录(MOSAEL_PLUGIN_OUTPUT_DIR)。",
                               "The host gave no output directory (MOSAEL_PLUGIN_OUTPUT_DIR)."))
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_stem(value: Any, fallback: str) -> str:
    """产出文件名:只留字母数字、中文、点、横线;扩展名由调用方加。"""
    stem = re.sub(r"[^\w一-鿿.-]+", "_", str(value or "")).strip("._")[:80]
    stem = re.sub(r"\.(mp4|mov|webm|gif|png|srt)$", "", stem, flags=re.I)
    return stem or fallback


# ---------------------------------------------------------------- 从输出里挑原因

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_EXCEPTION_LINE = re.compile(r"\b\w*(Error|Exception)\b\s*:")
_PROGRESS_LINE = re.compile(r"\d+%\s*\||\|\s*\d+/\d+\s*\[|\d+(\.\d+)?\s*(it|file|[kMG]?i?[Bb])/s")
_NOISE_LINE = re.compile(
    r"^(?:[\^~]+|[-=_]{3,}|note:.*|hint:.*|File \".*\", line \d+.*|Traceback \(most recent call last\):"
    r"|During handling of the above exception.*|The above exception was the direct cause.*"
    r"|[│╭╰─╮╯┃━\s]+.*|Manim Community v[\d.]+)$",
    re.I,
)


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


def blame_line(output: str, fallback: str = "") -> str:
    """从子进程的输出里挑**说明失败原因**的那一行 —— 不是最后一行。

    和宿主的 core/text.blame_line 同一个判据(插件拿不到宿主的代码,所以抄一份):先从后往前找长得像
    异常的一行;找不到再找第一行不是噪声、不是进度条、也不是 rich 画的边框的。最后一行常常是一根
    进度条或一条分隔线,拿它当原因只会让人对着一句无关的话发愣。
    """
    lines = [one.strip() for one in strip_ansi(output).splitlines() if one.strip()]
    exception = next((one for one in reversed(lines) if _EXCEPTION_LINE.search(one)), None)
    if exception:
        return exception.strip("│ ")
    meaningful = next((one for one in reversed(lines) if not _NOISE_LINE.match(one) and not _PROGRESS_LINE.search(one)), None)
    return meaningful or fallback
