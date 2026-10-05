"""仓库里的每个插件都写一句话简介(清单的 `summary`),中英两份。

市场卡片、插件详情的页头、安装确认先摆的都是它。没写的话,卡片只能摆第一条技能的长介绍 —— 那段是写给
「这东西是干嘛的、怎么用」的,三行放不下,页头上更是一大块(用户截图:「插件详情页面结构彻底重新设计一遍」)。
一句话和长介绍说的不是一回事,所以也不许一字不差地抄过来。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mosael_formats.plugin_manifest import SUMMARY_MAX_CHARS

ROOT = Path(__file__).resolve().parents[2] / "plugins"
MANIFESTS = sorted([*ROOT.glob("examples/*/mosael.plugin.json"), *ROOT.glob("bundled/*/mosael.plugin.json")])


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda path: path.parent.name)
def test_清单写了中英两份一句话简介(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    summary = raw.get("summary")
    assert isinstance(summary, dict) and set(summary) >= {"zh", "en"}, f"{path.parent.name} 的清单没写中英两份 summary"
    description = (raw.get("toolsets") or [{}])[0].get("description") or {}
    for locale in ("zh", "en"):
        text = str(summary[locale]).strip()
        assert 0 < len(text) <= SUMMARY_MAX_CHARS, f"{path.parent.name} 的 summary.{locale} 要是一句话({SUMMARY_MAX_CHARS} 字以内)"
        if isinstance(description, dict):
            assert text != str(description.get(locale) or "").strip(), f"{path.parent.name} 的 summary.{locale} 照抄了长介绍"
