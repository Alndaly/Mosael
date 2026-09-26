"""Text Toolkit — Mosael 插件 entry 脚本示例。

协议:stdin 读一个 JSON 请求 {"tool": name, "input": {...}, "locale": "zh"},stdout 写一个
JSON 响应 {"ok": true, "output": {...}} 或 {"ok": false, "error": "..."}。
纯标准库、纯函数:不碰网络、文件系统或数据库。

**跑出来的字由插件自己定语言**:清单里的文案由 Mosael 按界面语言挑,而这里产出的摘要、
失败原因只有插件写得出 —— 所以每次调用都告诉它读的人在用哪种语言(请求体里的 `locale`,
或环境变量 `MOSAEL_LOCALE`)。
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

#: 朗读速度:中文每秒约 4.5 字,英文每分钟约 150 词(每秒 2.5 词)。**两种语言各按各的单位算** ——
#: 按字符算的话,英文的一个词有五六个字符,念完的时间被估长两三倍。
CJK_PER_SECOND = 4.5
WORDS_PER_SECOND = 2.5

#: 一个「词」:字母数字连成的一段,中间可以有撇号、连字符、小数点(`It's`、`well-known`、`3.14`)。
_WORD = re.compile(r"[^\W_]+(?:['’.\-][^\W_]+)*")


class ToolError(ValueError):
    """说得出口的失败,原样交回。"""


def _line(locale: str, zh: str, en: str) -> str:
    """一句给人看的话。按主语言挑 —— `zh-CN` 和 `zh` 是同一件事。"""
    return zh if locale.replace("_", "-").split("-")[0].lower() == "zh" else en


def _is_cjk(ch: str) -> bool:
    """中日韩的「字」:全角宽度的文字(标点不算,它们不是字也不念)。"""
    return unicodedata.east_asian_width(ch) in ("W", "F") and ch.isalnum()


def word_count(payload: dict, locale: str) -> dict:
    """字数、词数、念完要多久。

    词数:中日韩文**一个字算一个词**(没有空格可切,Word、WPS 也是这么数的),其余按词。此前 `[\\w一-鿿]+`
    会把一整串汉字连成一个词 —— `\\w` 本来就包含汉字 —— 于是「你好世界」是 1 个词。
    """
    text = str(payload.get("text", ""))
    chars = sum(1 for ch in text if not ch.isspace())
    cjk = sum(1 for ch in text if _is_cjk(ch))
    words = len(_WORD.findall("".join(" " if _is_cjk(ch) else ch for ch in text)))
    seconds = round(cjk / CJK_PER_SECOND + words / WORDS_PER_SECOND, 1)
    return {
        "chars": chars,
        "words": cjk + words,
        "estimated_seconds": seconds,
        "summary": _line(locale, f"{chars} 字,念完约 {seconds} 秒", f"{chars} characters, about {seconds}s to read"),
    }


#: 成对的话题:微博 / 抖音的 `#话题#`。中间不能有空白 —— 否则 `#AI and #ML` 会被当成一个叫「AI and 」的话题。
_PAIRED = re.compile(r"(?<![A-Za-z0-9_&/])#([^#\s]{1,30})#")
#: 单个井号的标签:`#sunset`、`#旅行`。到第一个非字母数字处为止(`#sunset!` 是 sunset)。
#: 前面紧挨着英文字母数字、`&`、`/` 的不算:`C#`、`&#123;`、`https://x.com/a#frag`。
_SINGLE = re.compile(r"(?<![A-Za-z0-9_&/#])#(\w{1,50})")


def _is_tag(tag: str) -> bool:
    """全是数字的不算(`#1`、`#2024` 是编号,不是话题)。"""
    return bool(re.search(r"[^\W\d_]", tag))


def extract_hashtags(payload: dict, locale: str) -> dict:
    """提取 `#话题#` 与 `#hashtag`,按出现的先后;大小写不同的算同一个(留第一次的写法)。"""
    text = str(payload.get("text", ""))
    found: list[tuple[int, str]] = [(m.start(), m.group(1)) for m in _PAIRED.finditer(text)]
    # 成对的那一段挖掉再找单个的:`#好物#` 不该再被认成一个 `#好物`。换成空格,不让前后两段粘在一起。
    rest = _PAIRED.sub(lambda m: " " * len(m.group(0)), text)
    found += [(m.start(), m.group(1)) for m in _SINGLE.finditer(rest)]
    tags: dict[str, str] = {}
    for _, tag in sorted(found):
        if _is_tag(tag):
            tags.setdefault(tag.casefold(), tag)
    listed = list(tags.values())
    return {
        "hashtags": listed,
        "count": len(listed),
        "summary": _line(locale, f"找到 {len(listed)} 个话题标签", f"Found {len(listed)} hashtags"),
    }


TOOLS = {"word_count": word_count, "extract_hashtags": extract_hashtags}


def main() -> None:
    locale = "zh"
    try:
        request = json.loads(sys.stdin.read())
        locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
        name = str(request.get("tool"))
        tool = TOOLS.get(name)
        if tool is None:
            raise ToolError(_line(locale, f"不认识的工具:{name}", f"Unknown tool: {name}"))
        payload = request.get("input") or {}
        if not isinstance(payload, dict):
            raise ToolError(_line(locale, "input 要是一个 JSON 对象。", "input must be a JSON object."))
        json.dump({"ok": True, "output": tool(payload, locale)}, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — report, don't crash silently
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
