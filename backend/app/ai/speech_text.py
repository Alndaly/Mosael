"""引擎侧的标点处理:只有**会念出符号名**的引擎才需要。"""

from __future__ import annotations

import re
from typing import Literal

#: 引擎怎么处理省略号:
#:
#: - ``pause``:引擎自己把 ``……`` 当停顿(Edge 实测约 0.79 秒)。原文原样送进去。
#: - ``literal``:引擎会把省略号逐字念成「省略号」。送进去之前换成它认识的停顿标点。
#:
#: 这是**引擎的能力**,不是文案的清洗规则:同一个 ``……`` 在 Edge 里是语气,在另一些模型里是三个字。
#: 所以它和 ``speed_control`` 一样挂在引擎目录上,由适配器 / 本地引擎各自声明。
EllipsisHandling = Literal["pause", "literal"]

#: 中文省略号、三个以上的英文句点、数学省略号。
_ELLIPSIS = re.compile(r"…+|\.{3,}|⋯+")


def _pause(match: re.Match[str]) -> str:
    """省略号在句尾收成句号,句中收成逗号,紧挨着别的停顿时不重复。"""
    rest = match.string[match.end() :]
    next_char = next((char for char in rest if not char.isspace()), "")
    if not next_char:
        return "。"
    if next_char in "。！？!?，,；;：:":
        return ""
    if "\n" in rest[: len(rest) - len(rest.lstrip())]:
        return "。"
    return "，"


def pause_ellipsis(text: str) -> str:
    """把会被念成「省略号」的符号换成停顿。只给 ``literal`` 引擎用;``pause`` 引擎直接收原文。"""
    return _ELLIPSIS.sub(_pause, text) if text else text


def text_for_engine(text: str, ellipsis: EllipsisHandling) -> str:
    """按引擎声明的策略决定送进去的那一份文本。"""
    return pause_ellipsis(text) if ellipsis == "literal" else text


__all__ = ["EllipsisHandling", "pause_ellipsis", "text_for_engine"]
