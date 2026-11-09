"""字幕换行:按「栏」量宽度,在画面放得下的地方断行。

**栏**是一个半角字的宽度:全角字(汉字、日文、全角标点)占 2 栏,其余占 1 栏。拉丁字母实测平均比半个
汉字还窄一点(PingFang 下约 0.46 个汉字),按 1 栏算是偏保守的估计 —— 宁可早一点换行,不让字出画。

为什么要自己断:libass 只在空格处换行,一整句中文没有空格,`WrapStyle` 怎么设都会一行冲出画面
(实测「雨夜归灯」成片)。浏览器那条路靠 CSS 的 `max-width` + `pre-wrap` 自己会断;两条路要出同一个样子,
就在交给 libass 之前把 `\\N` 插好。

断在哪(从好到差):
1. 空格处 —— 拉丁文按词断;
2. 句读之后 —— 「，」「。」后面断,读起来最顺;
3. 两个全角字之间 —— 中文本来就可以在任意两字间断;
4. 实在没有(一个超长的英文词)才硬切。

禁则:收尾标点(,。、;:?!)」』"’》…)不放在行首,挂到上一行末尾 —— 挂上去哪怕略超一点。
"""

from __future__ import annotations

import unicodedata

#: 不能出现在行首的标点(全角、半角都算)。
_NO_LINE_START = frozenset("，。、；：？！）」』”’》〉】…—,.;:?!)]}%")
#: 断在它们后面最顺。
_BREAK_AFTER = frozenset("，。、；：？！,.;:?!")
#: 一行至少要填到这么满,才肯为了「断在标点 / 空格处」提前换行;否则就在字间断。
_MIN_FILL = 0.6


def columns(text: str) -> int:
    """这段文字占几栏:全角 2、其余 1。"""
    return sum(_char_columns(char) for char in text)


def _char_columns(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in "WF" else 1


def wrap(text: str, max_columns: int) -> list[str]:
    """把一段文字断成每行不超过 `max_columns` 栏的几行。原有的换行照留;每行去掉首尾空格。"""
    if max_columns <= 0:
        return [text]
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(_wrap_paragraph(paragraph.strip(), max_columns))
    return lines


def _wrap_paragraph(text: str, max_columns: int) -> list[str]:
    lines: list[str] = []
    rest = text
    while columns(rest) > max_columns:
        cut = _cut_at(rest, max_columns)
        line, rest = rest[:cut].rstrip(), rest[cut:].lstrip()
        lines.append(line)
    if rest or not lines:
        lines.append(rest)
    return lines


def _cut_at(text: str, max_columns: int) -> int:
    """`text` 放不进一行:返回这一行在第几个字符处结束(不含)。"""
    fits = _chars_that_fit(text, max_columns)
    cut = _preferred_cut(text, fits, max_columns) or fits
    # 禁则:下一行开头若是收尾标点,把它们挂回这一行。
    while cut < len(text) and text[cut] in _NO_LINE_START:
        cut += 1
    return max(cut, 1)


def _chars_that_fit(text: str, max_columns: int) -> int:
    used = 0
    for index, char in enumerate(text):
        used += _char_columns(char)
        if used > max_columns:
            return index
    return len(text)


def _preferred_cut(text: str, fits: int, max_columns: int) -> int | None:
    """在放得下的那一截里,从后往前找空格 / 句读 / 全角字之间这几种好断点;太靠前的不要。"""
    floor = max_columns * _MIN_FILL
    for cut in range(fits, 0, -1):
        if columns(text[:cut]) < floor:
            break
        before, after = text[cut - 1], text[cut] if cut < len(text) else ""
        if after == " " or before == " " or before in _BREAK_AFTER:
            return cut
    # 没有空格和句读:中文在两个字之间就能断(英文词中间不行)。
    for cut in range(fits, 0, -1):
        before, after = text[cut - 1], text[cut] if cut < len(text) else ""
        if _char_columns(before) == 2 or (after and _char_columns(after) == 2):
            return cut
    return None
