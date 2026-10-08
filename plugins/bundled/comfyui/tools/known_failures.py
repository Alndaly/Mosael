"""认得出的 ComfyUI 执行错误:原话里带着这一段,就给一句「这是怎么回事、该去哪修」(宿主摆在失败卡上那句话下面)。

只收**确定**的那几种:原话里那一段指着一个已知的原因,修法也是确定的。认不出的不猜 —— 失败卡上照样有那句话和原文。
加一种就在 `KNOWN` 里加一行:`pattern` 匹配 ComfyUI 的原话(`exception_message`,不分大小写),`hint` 是两种语言的那句提示。
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Known(NamedTuple):
    pattern: re.Pattern[str]
    hint: dict[str, str]


KNOWN: tuple[Known, ...] = (
    #: comfy-kitchen 的 hostbuf 读文件那一步,老版本在新的 ComfyUI 上读模型就报这一句(和工作流无关,换哪张图都一样)。
    Known(
        re.compile(r"hostbuf_file_reader_read failed", re.IGNORECASE),
        {
            "zh": "这是那台 ComfyUI 上的问题,不是这张工作流的:它装的 comfy-kitchen 或 comfyui-workflow-templates 太旧。在那台机器上"
                  "把 comfy-kitchen 升到 0.2.37 以上、comfyui-workflow-templates 升到 0.11.77 以上(在 ComfyUI 用的那个 Python 里执行 "
                  "pip install -U comfy-kitchen comfyui-workflow-templates),重启 ComfyUI 再试。",
            "en": "This is a problem with that ComfyUI install, not with this workflow: its comfy-kitchen or "
                  "comfyui-workflow-templates is too old. On that machine, upgrade comfy-kitchen to 0.2.37 or later and "
                  "comfyui-workflow-templates to 0.11.77 or later (pip install -U comfy-kitchen comfyui-workflow-templates in "
                  "the Python ComfyUI runs on), then restart ComfyUI and try again.",
        },
    ),
)


def hint_for(said: str) -> dict[str, str] | None:
    """ComfyUI 的原话 → 认得出就是那句提示,认不出是 None。"""
    for one in KNOWN:
        if one.pattern.search(said or ""):
            return dict(one.hint)
    return None


__all__ = ["KNOWN", "Known", "hint_for"]
