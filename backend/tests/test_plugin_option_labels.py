"""插件字段下拉里每一项叫什么,只由插件自己说(`x-enum-labels`),不借宿主内置节点按字段名登记的那张表。

维护者截图:Manim 的「画质」(`quality`)和导出时间线节点的画质同名,`high` 被顺手翻成「高画质」,其余几项对不上露出原值,
一个下拉里 low / medium / 高画质 / production / 4k 中英混着。
"""

from __future__ import annotations

import json
import pathlib

from app.core.i18n import speaking
from app.domain.plugins.nodes import node_meta
from app.domain.workflows.node_catalog import translated_spec

QUALITY = {
    "type": "string",
    "enum": ["low", "high", "4k"],
    "x-enum-labels": {"low": {"zh": "低 · 480p", "en": "Low · 480p"}, "high": {"zh": "高 · 1080p", "en": "High · 1080p"},
                      "nope": "不在 enum 里的不收"},
}


def _field(schema: dict, key: str, locale: str) -> dict:
    with speaking(locale):
        meta = node_meta({"name": "t", "input_schema": {"type": "object", "properties": schema}})
        return translated_spec(key, meta["config"][key], locale)


def test_插件写了名字就照它的_按语言取_没写的照原值() -> None:
    zh = _field({"quality": QUALITY}, "quality", "zh-CN")
    assert zh["option_labels"] == {"low": "低 · 480p", "high": "高 · 1080p"}
    en = _field({"quality": QUALITY}, "quality", "en")
    assert en["option_labels"] == {"low": "Low · 480p", "high": "High · 1080p"}


def test_没写名字的插件字段不借宿主的选项名_哪怕字段同名() -> None:
    #: 宿主的导出节点有 `wfOpt_quality_high`(「高画质」)、画幅有 `wfOpt_aspect_*`:插件字段一项都不借。
    got = _field({"quality": {"type": "string", "enum": ["low", "high"]},
                  "aspect": {"type": "string", "enum": ["16:9", "9:16"]}}, "quality", "zh-CN")
    assert got["option_labels"] == {}
    assert _field({"aspect": {"type": "string", "enum": ["16:9", "9:16"]}}, "aspect", "zh-CN")["option_labels"] == {}


def test_开关的是否照旧由宿主给() -> None:
    got = _field({"loop": {"type": "boolean"}}, "loop", "zh-CN")
    assert set(got["option_labels"]) == {"true", "false"}
    assert all(label not in ("true", "false") for label in got["option_labels"].values())


def test_随应用发的示例插件里每个可选值都有名字或本身就读得懂() -> None:
    """Manim / Remotion 的画幅、画质、主题都写了名字;帧率、格式这类本身就是给人看的值,不写。"""
    root = pathlib.Path(__file__).resolve().parents[2] / "plugins" / "examples"
    for name in ("manim", "remotion"):
        manifest = json.loads((root / name / "mosael.plugin.json").read_text(encoding="utf-8"))
        for tool in manifest["tools"]["declare"]:
            for key, spec in ((tool.get("input_schema") or {}).get("properties") or {}).items():
                if key in ("aspect", "quality", "theme") and spec.get("enum"):
                    labels = spec.get("x-enum-labels") or {}
                    assert set(map(str, spec["enum"])) <= set(labels), f"{name}.{tool['name']}.{key}"
