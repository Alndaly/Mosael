"""棘轮:我们自己发的插件,清单里的每个工具都写了名字(`label`,中英各一份)。

工具**叫什么**只有一条解析(`manifest.tool_label`):清单里改的名字 → 工具的 `title` / `label` →
`node` 块的 `label` → 按调用名人性化。**从不拿说明顶替名字。** 此前没写名字的工具退到「说明的
第一行」,画板「添加」菜单上于是有一行叫「把桶里的一个对象拉回素材库。**交回的是地…」——
带着 markdown 记号,底下的说明行又把同一句念一遍(对象存储的 `storage_fetch`)。

调用名人性化(`Storage fetch`)只是给第三方插件兜底的;我们自己发的是别人照抄的样板,每个工具
都该有一个给人看的名字 —— 这里钉住。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
from pathlib import Path
from typing import Any

from app.core.i18n import set_current_locale
from app.domain.plugins.manifest import parse, tool_label
from app.domain.plugins.nodes import node_meta

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = sorted([*(ROOT / "plugins" / "examples").glob("*/mosael.plugin.json"),
                    *(ROOT / "plugins" / "bundled").glob("*/mosael.plugin.json")])


def _tools(raw: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """清单里点了名的每个工具:进程插件声明的(`declare`),和 MCP 插件按名字覆盖的(`overrides`)。"""
    tools = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
    declared = [(str(tool.get("name")), tool) for tool in tools.get("declare") or [] if isinstance(tool, dict)]
    overridden = [(str(name), spec) for name, spec in (tools.get("overrides") or {}).items() if isinstance(spec, dict)]
    return declared + overridden


def test_我们自己发的插件每个工具都写了中英两份名字() -> None:
    missing: list[str] = []
    for path in MANIFESTS:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for name, tool in _tools(raw):
            label = tool.get("label")
            if not isinstance(label, dict) or not all(str(label.get(lang) or "").strip() for lang in ("zh", "en")):
                missing.append(f"{path.parent.name}: {name}")
    assert not missing, "这些工具没写名字(`label: {zh, en}`),界面上只能显示调用名:\n" + "\n".join(missing)


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:目录改了名,上面那条会真空通过。"""
    assert len(MANIFESTS) >= 5
    assert sum(len(_tools(json.loads(path.read_text(encoding="utf-8")))) for path in MANIFESTS) >= 20


def test_没写名字的工具用调用名_从不拿说明顶替() -> None:
    described = {"name": "fetch_one_video", "description": "获取视频详情/Get video detail"}
    assert tool_label(described) == "Fetch one video"
    #: 说明里带 markdown、写成好几句的,更不能上菜单当名字。
    assert tool_label({"name": "storage_fetch", "description": "把对象拉回素材库。**交地址**"}) == "Storage fetch"


def test_名字的先后_覆盖_工具自己的_node块的_调用名() -> None:
    tool = {"name": "pan_import", "node": {"label": {"zh": "节点名", "en": "Node name"}}}
    set_current_locale("zh")
    assert tool_label(tool) == "节点名"
    assert tool_label({**tool, "label": {"zh": "工具名", "en": "Tool name"}}) == "工具名"
    assert tool_label({**tool, "title": "MCP 标题"}) == "MCP 标题"
    assert tool_label({**tool, "label": "工具名"}, "改过的名字") == "改过的名字"
    set_current_locale("en")
    assert tool_label(tool) == "Node name"


def test_对象存储的取回工具在节点和画板上叫它声明的名字_出处是插件名() -> None:
    raw = json.loads((ROOT / "plugins" / "bundled" / "object-storage" / "mosael.plugin.json").read_text(encoding="utf-8"))
    for locale, label, plugin in (("zh", "从对象存储取回", "对象存储"), ("en", "Fetch from object storage", "Object Storage")):
        set_current_locale(locale)
        manifest = parse(raw, "object-storage")
        fetch = next(tool for tool in manifest.declared_tools if tool["name"] == "storage_fetch")
        #: 进 node_meta 的形状和 plugins.tools.exposed 给的一样:名字已解析,带上连接名和插件名。
        meta = node_meta({**fetch, "label": tool_label(fetch), "instance_name": "阿里云 OSS · mosael",
                          "package_name": manifest.name})
        assert meta["label"] == label
        assert "**" not in meta["label"] and meta["label"] not in meta["description"]
        #: 出处是插件,不是连接(「阿里云 OSS · 某个桶」是本机事实,节点按包聚合)。
        assert meta["plugin_name"] == plugin
    set_current_locale("zh")
