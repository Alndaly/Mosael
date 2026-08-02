#!/usr/bin/env python3
"""把智能体工具清单同步进 docs/MCP.md。

手写的清单会腐烂:MCP.md 曾经只列了 54 个工具里的 15 个,而缺的那些恰恰是后来加的 ——
读者据此以为智能体不会浏览器、不会记忆、不会发通知。而这类文档漂移**没有任何信号**,
除非有人恰好去数一遍。

所以清单从注册表生成,标记之间的内容整段替换;tests/test_tool_docs_in_sync.py 钉住它
和代码一致——文档过期会让测试红,不再靠人记得更新。

    backend/.venv/bin/python scripts/sync-tool-docs.py [--check]
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "MCP.md"
BEGIN = "<!-- BEGIN generated: tools -->"
END = "<!-- END generated: tools -->"


def _first_sentence(text: str) -> str:
    """取工具说明的第一句。工具的 docstring 写给模型看,前面通常有 `Runs directly:` /
    `Confirmation required:` 这样的前缀,正是读者要的那半句。"""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return re.sub(r"\s+", " ", line).strip()


def render() -> str:
    sys.path.insert(0, str(ROOT / "backend"))
    import mcp_server

    tools = sorted(asyncio.run(mcp_server.mcp.list_tools()), key=lambda t: t.name)
    gated = set(mcp_server.CONFIRMATION_TOOLS)
    rows = [
        f"| `{t.name}` | {'确认卡' if t.name in gated else '直接执行'} | {_first_sentence(t.description)} |"
        for t in tools
    ]
    header = [
        f"共 **{len(tools)}** 个工具,其中 **{len(gated)}** 个走确认卡。",
        "",
        "| 工具 | 门控 | 说明 |",
        "| --- | --- | --- |",
    ]
    return "\n".join([BEGIN, "", *header, *rows, "", END])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只检查是否同步,不写入")
    args = parser.parse_args()

    text = DOC.read_text("utf-8")
    if BEGIN not in text or END not in text:
        print(f"{DOC} 里没有生成标记 {BEGIN} … {END}", file=sys.stderr)
        return 2
    block = render()
    updated = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)

    if args.check:
        if updated != text:
            print("docs/MCP.md 的工具清单已过期,跑 scripts/sync-tool-docs.py 重新生成", file=sys.stderr)
            return 1
        print("工具清单与代码一致")
        return 0

    if updated != text:
        DOC.write_text(updated, "utf-8")
        print(f"已更新 {DOC.relative_to(ROOT)}")
    else:
        print("已是最新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
