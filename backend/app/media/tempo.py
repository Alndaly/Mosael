"""音频变速的 atempo 滤镜。成片渲染(render_executor)和对口型配音(dub_lipsync)共用这一份。"""

from __future__ import annotations


def atempo_filters(speed: float) -> str:
    """把 `speed` 倍速拆成几级 atempo —— ffmpeg 的一级 atempo 只收 0.5–2 倍,更快或更慢要串起来。

    返回的是**可以直接接在滤镜链中间的一段**,自带尾随逗号(`atempo=2.0,atempo=1.5,`);原速返回空串,
    调用处不必为「要不要变速」另写分支。
    """
    if speed == 1.0:
        return ""
    parts: list[str] = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining}")
    return ",".join(parts) + ","
