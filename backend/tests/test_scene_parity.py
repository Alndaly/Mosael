"""场景契约的后端一侧:跑 contracts/scene-cases.json。

前端 `sceneModel.parity.test.ts` 跑**同一份文件**。语料是语言中立的,所以任何一侧改了场景语义
而另一侧没跟上,两边 CI 都会红——这正是预览与导出漂移的唯一防线。

为什么不共用一份实现:预览要本地同步跑到 60fps、还要处理未提交的拖拽草稿,导出要无头、在后端、
可外派给 worker(ADR-0002)。两个约束决定了模型必然存在于两种语言里,所以一致性靠契约而非共用代码。

**改语义时**:先改 contracts/scene-cases.json,看着两侧一起红,再改两侧实现。反过来做——先改实现
再补语料——就等于把语料降级成实现的复读机,防不住任何东西。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.media.scene import scene_layers_at

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "scene-cases.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    return _load()["cases"]


def _ids() -> list[str]:
    return [case["name"] for case in _cases()]


def test_contract_file_is_present_and_versioned() -> None:
    """语料找不到就静默跳过是最坏的结果——那样两侧都「通过」,而契约根本没跑。"""
    assert _CONTRACT.is_file(), f"场景契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "scene"
    assert isinstance(data["version"], int)
    assert data["cases"], "语料为空 = 没有任何一致性保护"


@pytest.mark.parametrize("case", _cases(), ids=_ids())
def test_scene_layers_match_contract(case: dict) -> None:
    tracks, assets = case["tracks"], case["assets"]
    for sample in case["samples"]:
        actual = [
            {"clip": layer.clip["id"], "track": layer.track_id, "isBase": layer.is_base}
            for layer in scene_layers_at(tracks, assets, float(sample["t"]))
        ]
        assert actual == sample["layers"], (
            f"{case['name']} @ t={sample['t']}\n"
            f"  契约: {sample['layers']}\n"
            f"  实际: {actual}\n"
            f"  用例理由: {case.get('why', '')}"
        )

