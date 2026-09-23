"""插件清单里的作者与文档。

- `author: {name, url}`:插件是别人的代码,装之前、用的时候都该看得见是谁写的、去哪儿找他。
- `docs`:这个插件**在 Mosael 里怎么用**的文档,可按语言分。应用里「文档」按钮跳到这儿 ——
  此前它一律跳到通用的插件指南,官网上每个插件自己的那一页从应用里到不了。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.i18n import set_current_locale
from app.domain.plugins.manifest import parse

EXAMPLES = Path(__file__).resolve().parents[2] / "plugins" / "examples"
BASE = {"id": "x.y", "manifest_version": 1, "name": "X", "version": "1"}


def test_作者和按语言分的文档都读得出来() -> None:
    raw = {
        **BASE,
        "author": {"name": {"zh": "某人", "en": "Someone"}, "url": "https://example.com"},
        "docs": {"zh": "https://example.com/zh/x", "en": "https://example.com/en/x"},
    }
    set_current_locale("zh")
    manifest = parse(raw, "x")
    assert (manifest.author.name, manifest.author.url, manifest.docs) == ("某人", "https://example.com", "https://example.com/zh/x")
    set_current_locale("en")
    manifest = parse(raw, "x")
    assert (manifest.author.name, manifest.docs) == ("Someone", "https://example.com/en/x")


def test_不是http的链接一律当没写() -> None:
    """界面上这两个链接点下去就是打开它 —— javascript: / file: 是从第三方清单直通浏览器的路。"""
    manifest = parse({**BASE, "author": {"name": "a", "url": "javascript:alert(1)"}, "docs": "file:///etc/passwd"}, "x")
    assert (manifest.author.url, manifest.docs) == ("", "")


def test_没写就是空_不瞎补() -> None:
    manifest = parse(BASE, "x")
    assert (manifest.author.name, manifest.author.url, manifest.docs) == ("", "", "")


def test_官方插件都写了作者_文档指向官网上它自己那一页() -> None:
    """官网的插件页按目录名生成(/zh/plugins/<目录>)。docs 写错一个字母,应用里的「文档」就是 404。"""
    for manifest_path in sorted(EXAMPLES.glob("*/mosael.plugin.json")):
        slug = manifest_path.parent.name
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert raw.get("author", {}).get("name") and raw["author"].get("url", "").startswith("https://"), slug
        assert raw.get("docs") == {
            "zh": f"https://mosael.com/zh/plugins/{slug}",
            "en": f"https://mosael.com/en/plugins/{slug}",
        }, slug


def test_接口把作者和文档交给界面() -> None:
    from tests.test_plugins import install, packages

    manifest = {
        **BASE, "id": "dev.authored", "name": "有作者的",
        "runtime": {"kind": "process", "entry": "main.py"},
        "author": {"name": "某人", "url": "https://example.com"},
        "docs": {"zh": "https://example.com/zh", "en": "https://example.com/en"},
        "tools": {"declare": []},
    }
    client = install(manifest)
    set_current_locale("zh")
    package = packages(client)["dev.authored"]
    assert (package["author_name"], package["author_url"]) == ("某人", "https://example.com")
    assert package["docs"].startswith("https://example.com/")
