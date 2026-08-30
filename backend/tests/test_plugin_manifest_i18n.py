"""插件清单里给人看的文字必须能跟着界面语言走。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

这个仓库里数据目录的多语言一律是「领域里存 key,出口才翻」—— 文案进 `core/i18n.MESSAGES`,
清单里只留 key。**插件清单不能这么办**:插件是第三方写的,它没法往我们的表里加词条。

所以换一条路:**翻译贴着它翻译的那个东西写**,一段给人看的文字既可以是普通字符串,
也可以是 `{"zh": …, "en": …}`。不写成清单顶上的一张 `{"config.X.label": …}` 侧表,是因为
那种表的键要和别处对得上,而对不上时不会报错,只会让那一条永远显示原文 —— 这个项目在
「手抄一张表」上栽过好几次。

下面第二条钉的是**我们自己发的那几个插件**:它们是别人写插件时照抄的样板,样板上只有中文,
抄出来的插件在英文界面上就还是中文。
"""

from __future__ import annotations

RATCHET = True

import json
import re
from pathlib import Path
from typing import Any

from app.core.i18n import set_current_locale
from app.domain.plugins.manifest import parse, text_of

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "plugins" / "examples"
MANIFEST_NAME = "open-studio.plugin.json"
CJK = re.compile(r"[一-鿿]")


def _manifests() -> list[tuple[str, dict[str, Any]]]:
    return [(p.parent.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(EXAMPLES.glob(f"*/{MANIFEST_NAME}"))]


def _human_texts(raw: dict[str, Any]) -> list[tuple[str, Any]]:
    """清单里所有**给人看的**字段。位置写死 —— 不扫全树,免得把 id、路径也当成文案。"""
    out: list[tuple[str, Any]] = [("name", raw.get("name"))]
    for i, skill in enumerate(raw.get("skills") or []):
        out.append((f"skills[{i}].description", skill.get("description")))
    instance = raw.get("instance") or {}
    if instance.get("name_template"):
        out.append(("instance.name_template", instance["name_template"]))
    for group in ("config", "credentials"):
        for spec in instance.get(group) or []:
            where = f"instance.{group}.{spec.get('key')}"
            for key in ("label", "help"):
                if spec.get(key):
                    out.append((f"{where}.{key}", spec[key]))
            for option in spec.get("options") or []:
                out.append((f"{where}.options.{option.get('value')}.label", option.get("label")))
    tools = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
    for tool in tools.get("declare") or []:
        out.append((f"tools.{tool.get('name')}.description", tool.get("description")))
        node = tool.get("node") or {}
        if node.get("label"):
            out.append((f"tools.{tool.get('name')}.node.label", node["label"]))
        for key, spec in ((tool.get("input_schema") or {}).get("properties") or {}).items():
            if spec.get("description"):
                out.append((f"tools.{tool.get('name')}.args.{key}.description", spec["description"]))
    return out


def test_一段文案可以是字符串也可以是按语言分的对象() -> None:
    set_current_locale("en")
    assert text_of("Start directory") == "Start directory"
    assert text_of({"zh": "起始目录", "en": "Start directory"}) == "Start directory"
    set_current_locale("zh")
    assert text_of({"zh": "起始目录", "en": "Start directory"}) == "起始目录"


def test_只写了一种语言时给原文而不是空白() -> None:
    """插件作者只写中文,英文界面上看到中文 —— 总好过看到一片空白。"""
    set_current_locale("en")
    assert text_of({"zh": "起始目录"}) == "起始目录"
    assert text_of({"ja": "開始ディレクトリ"}) == "開始ディレクトリ"
    assert text_of(None) == ""


def test_我们自己发的插件每一句中文都配了英文() -> None:
    """样板上只有中文的话,照着它写的插件在英文界面上也只有中文。"""
    missing: list[str] = []
    for name, raw in _manifests():
        for where, value in _human_texts(raw):
            if isinstance(value, str) and CJK.search(value):
                missing.append(f"{name}: {where}")
            elif isinstance(value, dict) and not str(value.get("en") or "").strip():
                missing.append(f"{name}: {where}(缺 en)")
    assert not missing, "这些文案在英文界面上还是中文:\n" + "\n".join(missing)


def test_示例插件都能解析成能跑的东西() -> None:
    """曾经有两个示例停在旧清单形状上,解析出来是 `entry=''`、零个工具 —— 而且一声不吭。"""
    for name, raw in _manifests():
        manifest = parse(raw, name)
        if manifest.is_mcp:
            assert manifest.runtime.command or manifest.runtime.url, f"{name} 是 MCP 插件却没说怎么连"
        else:
            assert manifest.runtime.entry, f"{name} 是脚本插件却没有入口"


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天目录改了名,上面几条会一起真空通过。"""
    assert len(_manifests()) >= 3
    assert sum(len(_human_texts(raw)) for _, raw in _manifests()) >= 20


def test_文档链接只认_http() -> None:
    """那个链接是直接交给用户浏览器打开的 —— `javascript:` 是一条从第三方清单直通浏览器的路。

    这里不是在防御格式,是在防御来源:清单是别人写的。
    """
    from app.domain.plugins.manifest import parse

    base = {"id": "x", "name": "X", "version": "1"}
    for good in ("https://docs.example.com/", "http://example.com/a"):
        assert parse({**base, "homepage": good}, "").homepage == good

    for bad in ("javascript:alert(1)", "file:///etc/passwd", "ftp://x/y", "docs.example.com", ""):
        assert parse({**base, "homepage": bad}, "").homepage == "", bad
