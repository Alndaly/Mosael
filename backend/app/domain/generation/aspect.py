"""画幅:「要几比几」怎么读、怎么翻成一个具体模型认的参数(ADR 0094)。

两件事共用这里:
- **出图、出视频时按要的画幅出**(`parameters_for_aspect`):节点上写的是「要 9:16」,不是某个模型的 `720x1280` ——
  模板建图时写死的尺寸一换模型就清掉了(真跑时 gpt-image-2 换回来变成 1024×1024 方图),而这一格是节点自己的,换模型不丢。
  交给哪个模型,就按它的描述符翻成它认的那一格:画幅选项、尺寸表、任意尺寸,或 ComfyUI 工作流里叫 `aspect_ratio` 的节点输入;
- **首帧、尾帧按视频画幅摆正**(`frame_fit`):读这次参数里说的画幅(`aspect_of_parameters`)。

画幅的写法只认两种:开头的「宽:高」(`9:16`、`9:16 (Portrait Widescreen)`)和「宽x高」(`1280x720`、`832*480`)。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

#: 两个画幅算不算同一个:宽高比的相对差多少以内。万相视频的 832*480 是 1.733,和 16:9 的 1.778 差 2.5%。
SAME_ASPECT = 0.05
#: 视频跟着首帧走,不定画幅。
FOLLOWS_THE_FRAME = "adaptive"

_RATIO = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
_SIZE = re.compile(r"^\s*(\d+)\s*[x×*]\s*(\d+)\s*$")


def ratio_of(text: Any) -> float | None:
    """「宽:高」开头或「宽x高」→ 宽 / 高;都不是返回 None。"""
    value = str(text or "")
    if (match := _RATIO.match(value)) and float(match.group(2)):
        return float(match.group(1)) / float(match.group(2))
    if (match := _SIZE.match(value.lower())) and int(match.group(2)):
        return int(match.group(1)) / int(match.group(2))
    return None


def same_aspect(a: float, b: float, tolerance: float = SAME_ASPECT) -> bool:
    return abs(a - b) / b <= tolerance


def is_aspect_key(key: Any) -> bool:
    """这一格是不是在说画幅:宿主的 `aspect_ratio`,或名字就叫 `aspect_ratio` 的节点输入(`115.aspect_ratio`)。"""
    return isinstance(key, str) and (key == "aspect_ratio" or key.endswith(".aspect_ratio"))


def aspect_of_parameters(parameters: Mapping[str, Any]) -> tuple[float | None, str]:
    """这次参数里说的画幅(宽 / 高)和原样的写法。先说画幅的那几格(宿主的在前),再 `size`;
    `adaptive` 或都没有返回 (None, "")。"""
    named = [parameters.get("aspect_ratio")] + [value for key, value in parameters.items() if key != "aspect_ratio" and is_aspect_key(key)]
    for value in (str(one) for one in named if one not in (None, "")):
        if value.strip().lower() == FOLLOWS_THE_FRAME:
            return None, ""
        if (match := _RATIO.match(value)) and float(match.group(2)):
            return float(match.group(1)) / float(match.group(2)), f"{match.group(1)}:{match.group(2)}"
    size = str(parameters.get("size") or "").strip()
    if (match := _SIZE.match(size.lower())) and int(match.group(2)):
        return int(match.group(1)) / int(match.group(2)), size
    return None, ""


def size_for_aspect(sizes: Any, aspect: str, *, pick: str = "smallest", near_area: int = 0, minimum: int = 0) -> str:
    """尺寸表里和这个画幅同比例的那一档,**原样**交出(`832*480` 就是 `832*480`);没有就空串。

    像素写法(`宽x高` / `宽*高`)优先,在同比例的几档里按 `pick` 挑:smallest / largest 按面积,near 挑面积最接近
    `near_area` 的(视频按默认那一档的清晰度挑,不顺手升到 1080p 多花钱)。`minimum` 是模型要求的最小像素数。
    没有像素写法、但表里列着同一个比例的**画幅比写法**(Evolink 的 `9:16`)时,直接交它。
    """
    target = ratio_of(aspect)
    if target is None:
        return ""
    pixel: list[tuple[int, str]] = []
    for raw in sizes or ():
        text = str(raw).strip().lower().replace("*", "x")
        if not re.fullmatch(r"\d+x\d+", text):
            continue
        width, height = (int(value) for value in text.split("x", 1))
        if height and same_aspect(width / height, target) and width * height >= minimum:
            pixel.append((width * height, str(raw).strip()))
    if pixel:
        if pick == "near":
            return min(pixel, key=lambda one: abs(one[0] - near_area))[1]
        return sorted(pixel, reverse=pick == "largest")[0][1]
    for raw in sizes or ():
        text = str(raw).strip()
        if re.fullmatch(r"\d+:\d+", text) and (ratio := ratio_of(text)) is not None and same_aspect(ratio, target, 0.02):
            return text
    return ""


def _area(size: Any) -> int:
    match = _SIZE.match(str(size or "").lower())
    return int(match.group(1)) * int(match.group(2)) if match else 0


def _custom_size(rule: Mapping[str, Any], aspect: float, area: int) -> str:
    """任意尺寸都收的模型(描述符的 `custom_size`):按默认那一档的面积、这个画幅,取 `multiple_of` 的倍数。"""
    step = max(int(rule.get("multiple_of") or 1), 1)
    minimum = max(int(rule.get("minimum") or 1), 1)
    area = area or 1024 * 1024
    width = max(minimum, round(math.sqrt(area * aspect) / step) * step)
    height = max(minimum, round(math.sqrt(area / aspect) / step) * step)
    return f"{width}x{height}"


def parameters_for_aspect(
    capabilities: Mapping[str, Any] | None, aspect: str, given: Mapping[str, Any],
) -> dict[str, Any]:
    """要 `aspect`(「9:16」)时,这个模型该收哪几格参数。**写明了的优先**:`given` 里已经有说画幅的格子或 `size`,
    什么都不加。按先后:画幅选项(`aspect_ratios`)→ ComfyUI 工作流里叫 `aspect_ratio` 的节点输入(按选项挑)→
    尺寸表(`sizes`,面积挑最接近默认那一档的)→ 任意尺寸(`custom_size`)。都对不上返回空 —— 不硬塞。"""
    target = ratio_of(aspect)
    caps = capabilities or {}
    if target is None or any(is_aspect_key(key) for key in given) or given.get("size"):
        return {}
    keys = set(caps.get("parameter_keys") or ())
    takes = (lambda key: not keys or key in keys)
    for option in caps.get("aspect_ratios") or ():
        if takes("aspect_ratio") and (ratio := ratio_of(option)) is not None and same_aspect(ratio, target, 0.01):
            return {"aspect_ratio": str(option)}
    schema = caps.get("parameter_schema") or {}
    for key, spec in schema.items():
        if is_aspect_key(key) and isinstance(spec, Mapping):
            for option in spec.get("enum") or ():
                if (ratio := ratio_of(option)) is not None and same_aspect(ratio, target, 0.01):
                    return {key: str(option)}
    if takes("size"):
        found = size_for_aspect(caps.get("sizes"), aspect, pick="near", near_area=_area(caps.get("default_size")))
        if found:
            return {"size": found}
        if isinstance(caps.get("custom_size"), Mapping):
            return {"size": _custom_size(caps["custom_size"], target, _area(caps.get("default_size")))}
    return {}


__all__ = [
    "FOLLOWS_THE_FRAME", "SAME_ASPECT", "aspect_of_parameters", "is_aspect_key", "parameters_for_aspect",
    "ratio_of", "same_aspect", "size_for_aspect",
]
