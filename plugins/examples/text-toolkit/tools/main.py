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


def _line(locale: str, zh: str, en: str) -> str:
    """一句给人看的话。按主语言挑 —— `zh-CN` 和 `zh` 是同一件事。"""
    return zh if locale.replace("_", "-").split("-")[0].lower() == "zh" else en


def word_count(payload: dict, locale: str) -> dict:
    text = str(payload.get("text", ""))
    chars = len([ch for ch in text if not ch.isspace()])
    words = len(re.findall(r"[\w一-鿿]+", text))
    seconds = round(chars / 4.5, 1)
    return {
        "chars": chars,
        "words": words,
        "estimated_seconds": seconds,
        "summary": _line(locale, f"{chars} 字,念完约 {seconds} 秒", f"{chars} characters, about {seconds}s to read"),
    }


def extract_hashtags(payload: dict, locale: str) -> dict:
    text = str(payload.get("text", ""))
    zh = re.findall(r"#([^#\s]{1,30})#", text)
    en = re.findall(r"#([A-Za-z0-9_]{1,30})(?![^#\s])", text)
    tags = list(dict.fromkeys(zh + [tag for tag in en if tag not in zh]))
    return {
        "hashtags": tags,
        "count": len(tags),
        "summary": _line(locale, f"找到 {len(tags)} 个话题标签", f"Found {len(tags)} hashtags"),
    }


TOOLS = {"word_count": word_count, "extract_hashtags": extract_hashtags}


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        tool = TOOLS.get(str(request.get("tool")))
        if tool is None:
            raise ValueError(f"unknown tool: {request.get('tool')}")
        locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
        output = tool(request.get("input") or {}, locale)
        json.dump({"ok": True, "output": output}, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — report, don't crash silently
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
