"""TikHub 插件:零代码接 MCP,清单就是全部 —— 所以钉的是清单和说明书对不对得上。

README 同时是官网上插件详情页的正文(网站直接渲染它)。上一版 README 还停在「平台是一项凭据、要两个平台就把
目录复制一份改 id」的年代,而清单早就是「平台是枚举配置、一个包建多个连接」:照着 README 做的人会去凭据页找
一个不存在的格子,或者复制出一个 id 冲突的插件。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "tikhub"
GUIDES = Path(__file__).resolve().parents[2] / "website" / "content" / "docs"


def _manifest() -> dict:
    return json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))


def test_平台是配置_端点和鉴权从配置与凭据展开() -> None:
    manifest = _manifest()
    runtime, instance = manifest["runtime"], manifest["instance"]
    assert runtime["url"] == "https://mcp.tikhub.io/${TIKHUB_PLATFORM}/mcp"
    assert runtime["headers"] == {"Authorization": "Bearer ${TIKHUB_API_KEY}"}
    assert instance["multiple"] is True
    assert [f["key"] for f in instance["config"]] == ["TIKHUB_PLATFORM"]
    assert [c["key"] for c in instance["credentials"]] == ["TIKHUB_API_KEY"]


def test_README里的平台取值和清单一致() -> None:
    options = [o["value"] for o in _manifest()["instance"]["config"][0]["options"]]
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    listed = re.search(r"平台取值:(.+?)。", readme, re.S)
    assert listed, "README 里要列出平台取值"
    assert re.findall(r"`([a-z]+)`", listed.group(1)) == options


def test_README不再教人复制目录或把平台填进凭据() -> None:
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert "复制一份" not in readme and "改掉 manifest 里的 `id`" not in readme
    assert "插件页 → 凭据,填两项" not in readme
    assert "再建一个连接" in readme


def test_官网插件指南说的是MCP_不是本地脚本() -> None:
    for locale in ("zh", "en"):
        guide = (GUIDES / locale / "guides" / "plugins.mdx").read_text(encoding="utf-8")
        line = next(one for one in guide.splitlines() if one.startswith("- `tikhub`"))
        assert "MCP" in line and "本地脚本" not in line and "local script" not in line.lower(), line
