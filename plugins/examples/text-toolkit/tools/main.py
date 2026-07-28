"""Text Toolkit — Open Studio 插件 entry 脚本示例。

协议:stdin 读一个 JSON 请求 {"tool": name, "input": {...}},stdout 写一个
JSON 响应 {"ok": true, "output": {...}} 或 {"ok": false, "error": "..."}。
纯标准库、纯函数:不碰网络、文件系统或数据库。
"""
from __future__ import annotations

import json
import re
import sys


def word_count(payload: dict) -> dict:
    text = str(payload.get("text", ""))
    chars = len([ch for ch in text if not ch.isspace()])
    words = len(re.findall(r"[\w一-鿿]+", text))
    return {
        "chars": chars,
        "words": words,
        "estimated_seconds": round(chars / 4.5, 1),
    }


def extract_hashtags(payload: dict) -> dict:
    text = str(payload.get("text", ""))
    zh = re.findall(r"#([^#\s]{1,30})#", text)
    en = re.findall(r"#([A-Za-z0-9_]{1,30})(?![^#\s])", text)
    tags = list(dict.fromkeys(zh + [tag for tag in en if tag not in zh]))
    return {"hashtags": tags, "count": len(tags)}


TOOLS = {"word_count": word_count, "extract_hashtags": extract_hashtags}


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        tool = TOOLS.get(str(request.get("tool")))
        if tool is None:
            raise ValueError(f"unknown tool: {request.get('tool')}")
        output = tool(request.get("input") or {})
        json.dump({"ok": True, "output": output}, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — report, don't crash silently
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
