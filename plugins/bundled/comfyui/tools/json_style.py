"""照一份 JSON 原来的排版写回(`annotate` 改那台机器上的工作流文件用)。

ComfyUI 的前端存工作流用的是 `JSON.stringify`:紧凑、没有空格,数字按 JavaScript 的写法(`0.00001`、`1e-7`);导进来的、
别的工具写的可能缩进了几格。`annotate` 只改 `mosael` 那几处标记,别的字节应当一个不变 —— 此前一律按两格缩进写回,整份
文件重排,那台机器上的版本记录、同步盘、git 里每次都是「整个文件都改了」。

照原来的:紧凑的写成紧凑的(和 `JSON.stringify` 一样的分隔符、数字写法、不转义中文),缩进的照它的缩进(空格或制表符、
几格),键和值之间有没有空格、末尾有没有换行照旧。没改的那部分于是逐字节相同。
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

#: 浮点数先换成占位的字符串,写完再换回 JavaScript 的写法(json 模块的浮点写法是 Python 的 repr:`1e-05` 而不是 `0.00001`)
_MARK = "\x00n{}\x00"
#: 写出来的占位(控制字符被转义成 \u0000)
_MARKED = re.compile(r'"\\u0000n(\d+)\\u0000"')
#: 有的编辑器把空的 `{}` / `[]` 也拆成三行(中间一行只有缩进):照它的,先占位,写完按那一行的缩进换回去
_EMPTY = "\x00e{}\x00"
_EMPTIED = re.compile(r'(?m)^([ \t]*)(.*)"\\u0000e([{\[])\\u0000"')


def dumps_like(value: Any, original: str) -> str:
    """把 `value` 写成和 `original` 同一种排版的 JSON。"""
    indent = _indent_of(original)
    spread = indent is not None and re.search(r"[\[{]\r?\n[ \t]*\r?\n[ \t]*[\]}]", original) is not None
    numbers: list[str] = []
    marked = _mark(value, numbers, spread)
    text = json.dumps(marked, ensure_ascii=False, indent=indent, separators=_separators_of(original, indent))
    text = _MARKED.sub(lambda found: numbers[int(found.group(1))], text)
    if spread:
        closing = {"{": "}", "[": "]"}
        text = _EMPTIED.sub(lambda found: f"{found[1]}{found[2]}{found[3]}\n{found[1]}{indent}\n{found[1]}{closing[found[3]]}",
                            text)
    if "\r\n" in original:
        text = text.replace("\n", "\r\n")
    trailing = original[len(original.rstrip("\r\n")):]
    return text + trailing


def _indent_of(original: str) -> str | None:
    """缩进的单位(第一行之后那一行开头的空白);紧凑的(第一个括号后面没换行)是 None。"""
    found = re.match(r"\s*[\[{]\r?\n([ \t]+)\S", original)
    return found.group(1) if found else None


def _separators_of(original: str, indent: str | None) -> tuple[str, str]:
    """键和值之间(`"a":1`、`"a": 1`)、两项之间(紧凑的 `,`、Python 缺省的 `, `)各是什么,照原来的第一处。缩进的两项之间
    就是逗号加换行。"""
    key = re.search(r'"(\s*):(\s?)', original)
    colon = f"{key.group(1)}:{key.group(2)}" if key else ":"
    if indent is not None:
        return ",", colon
    item = re.search(r'[\]}"\d],( ?)[\[{"\d-]', original)
    return "," + (item.group(1) if item else ""), colon


def _mark(value: Any, numbers: list[str], spread: bool) -> Any:
    """浮点数换成占位(见 _MARK);`spread` 时空的对象、数组也换成占位(见 _EMPTY)。"""
    if isinstance(value, float):
        numbers.append(js_number(value))
        return _MARK.format(len(numbers) - 1)
    if spread and isinstance(value, (dict, list)) and not value:
        return _EMPTY.format("{" if isinstance(value, dict) else "[")
    if isinstance(value, dict):
        return {key: _mark(one, numbers, spread) for key, one in value.items()}
    if isinstance(value, list):
        return [_mark(one, numbers, spread) for one in value]
    return value


def js_number(value: float) -> str:
    """一个浮点数按 JavaScript `Number.prototype.toString` 的写法:最短的、能读回同一个数的那几位(Python 的 repr 也是),
    指数小于 -6 或不小于 21 才写成科学计数法,整数不带小数点。不是有限数的写成 null(和 `JSON.stringify` 一样)。"""
    if value != value or value in (float("inf"), float("-inf")):
        return "null"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    _, digits, exponent = Decimal(repr(abs(value))).normalize().as_tuple()
    text = "".join(str(one) for one in digits)
    count, point = len(text), len(text) + int(exponent)
    if count <= point <= 21:
        return sign + text + "0" * (point - count)
    if 0 < point <= 21:
        return sign + text[:point] + "." + text[point:]
    if -6 < point <= 0:
        return sign + "0." + "0" * -point + text
    power = point - 1
    tail = ("+" if power >= 0 else "-") + str(abs(power))
    return sign + (text if count == 1 else text[0] + "." + text[1:]) + "e" + tail
