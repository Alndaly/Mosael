"""文字层契约的后端一侧:跑 contracts/text-layer-cases.json。

前端 `textLayers.parity.test.ts` 跑**同一份文件**。哪些字幕、哪些花字会被画出来,预览在 Monitor 里
算、导出在 render.py 里算;两侧各写一份的时候,「视频轨静音」在两边都把花字藏掉了 —— 而轨道头
是喇叭。改语义时先改语料,看着两侧一起红,再改两侧实现。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.media.scene import text_layers

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "text-layer-cases.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    return _load()["cases"]


def test_contract_file_is_present_and_versioned() -> None:
    """语料找不到就静默跳过是最坏的结果——那样两侧都「通过」,而契约根本没跑。"""
    data = _load()
    assert data["contract"] == "text-layers"
    assert isinstance(data["version"], int)
    assert data["cases"]


@pytest.mark.parametrize("case", _cases(), ids=[case["name"] for case in _cases()])
def test_text_layers_match_contract(case: dict) -> None:
    layers = text_layers(case["tracks"])
    actual = {
        "subtitles": sorted(clip["id"] for clip in layers.subtitles),
        "titles": sorted(clip["id"] for clip in layers.titles),
        "subtitle_lanes": layers.subtitle_lanes,
    }
    expected = {
        "subtitles": sorted(case["expected"]["subtitles"]),
        "titles": sorted(case["expected"]["titles"]),
        "subtitle_lanes": case["expected"]["subtitle_lanes"],
    }
    assert actual == expected, case["why"]
