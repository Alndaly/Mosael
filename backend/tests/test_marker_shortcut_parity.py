"""画布标记快捷键契约的后端一侧:跑 contracts/marker-shortcut-cases.json。

前端 `frontend/src/lib/markerShortcut.parity.test.ts` 跑**同一份文件**。

为什么需要契约:归一这件事必然有两份实现 —— 前端要在**按下键的那一刻**当场判断(撞了就不给配,
而"先配上再看谁响应"的表现是一个时灵时不灵的键),后端要守"同一份文档里一个键只绑一个标记"
这条数据不变量(总会有第二个客户端写进来)。两份归出不同的串时谁都不报错,只会错开:界面说
「没冲突」而后端拒绝保存,或者两个标记看着绑了不同的键、存进去是同一个。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.markers import MarkerError, normalize_shortcut

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "marker-shortcut-cases.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _ids(section: str) -> list[str]:
    return [case["name"] for case in _load()[section]]


def test_contract_is_present_and_versioned() -> None:
    contract = _load()
    assert contract["contract"] == "marker-shortcut"
    assert contract["version"] == 1


@pytest.mark.parametrize("case", _load()["canonical"], ids=_ids("canonical"))
def test_canonical(case: dict) -> None:
    assert normalize_shortcut(case["raw"]) == case["combo"], case["why"]


@pytest.mark.parametrize("case", _load()["rejected"], ids=_ids("rejected"))
def test_rejected(case: dict) -> None:
    with pytest.raises(MarkerError):
        normalize_shortcut(case["raw"])
