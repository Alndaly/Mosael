from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.child_process import run_logged

"""
从一段视频里取某一时刻的**一帧**,存成一个图片文件。

**精确 seek,不用关键帧对齐的那种。** `-ss` 放在 `-i` 之后是逐帧解到那个时间点(慢一点,但取到
的就是你指定的那一帧);放在 `-i` 之前会跳到最近的关键帧 —— 用户在帧条上停在 3.2 秒,拿回来的
却是 2.8 秒那一帧,而画面看着差不多,他不会发现自己取错了。
"""


class StillError(RuntimeError):
    pass


def grab_frame(source: Path, at_seconds: float, target: Path) -> Path:
    """把 `source` 在 `at_seconds` 处的那一帧写到 `target`。"""
    if at_seconds < 0:
        raise StillError("时间不能是负数")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_logged(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(source),
                #: -ss 在 -i **之后** —— 见文件顶部那段。
                "-ss", f"{at_seconds:.3f}",
                "-frames:v", "1",
                "-q:v", "2",
                str(target),
            ],
            check=True, capture_output=True, timeout=120, what="取帧",
        )
    except subprocess.SubprocessError as exc:
        raise StillError("取帧失败") from exc
    if not target.is_file() or target.stat().st_size == 0:
        #: 时间点落在片尾之后时 ffmpeg 会成功退出但什么都不写 —— 空文件比报错更难查。
        raise StillError("这个时间点上没有画面 —— 是不是超过片长了?")
    return target
