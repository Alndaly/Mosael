"""结构性约束:**「普通 / 高级」这条分界怎么划都行,但有几种划法一定是错的。**

哪个字段算高级,是判断题(判据:留空/默认也能跑 **且** 它不是这个节点在做的事),不该由测试
来替人拍板 —— 所以这里钉的是**不变量**,不是具体名单:名单可以随产品判断改,而下面这几条
一旦破了,面板一定坏。

踩过的坑:纯按「说明里写了留空/默认」机械判,29 个字段命中,里面包括 `delay.seconds`
(那个节点唯一的字段)、`json_extract.path`(节点的全部意义)、`browser_open.url`(主操作)。
把它们收进高级,用户打开面板会看到一片空白,以为节点坏了。所以第二条判断跑不掉。
"""

from __future__ import annotations

RATCHET = True

import pytest

from app.domain.workflows import NODE_TYPES


def _config(name: str) -> dict:
    return NODE_TYPES[name].get("config") or {}


@pytest.mark.parametrize("name", sorted(NODE_TYPES))
def test_必填字段不能被收进高级(name: str) -> None:
    """必填却藏起来 = 用户点运行才被告知少了东西,而那个框他根本没看见。"""
    bad = [key for key, spec in _config(name).items() if (spec or {}).get("advanced") and (spec or {}).get("required")]
    assert not bad, f"{name} 把必填项收进了高级:{bad}"


@pytest.mark.parametrize("name", sorted(NODE_TYPES))
def test_不能整个节点都是高级(name: str) -> None:
    """一个字段都不剩的话,打开面板是一片空白 —— 看起来像节点坏了。"""
    config = _config(name)
    if not config:
        return
    basic = [key for key, spec in config.items() if not (spec or {}).get("advanced")]
    assert basic, f"{name} 的字段全被收进了高级,面板会是空的"


@pytest.mark.parametrize("name", sorted(NODE_TYPES))
def test_字段少于三个的节点不该分档(name: str) -> None:
    """两个字段藏一个,省下的那点空间不值得多一次点击 —— 分档本身也是一种成本。"""
    config = _config(name)
    if len(config) >= 3:
        return
    bad = [key for key, spec in config.items() if (spec or {}).get("advanced")]
    assert not bad, f"{name} 只有 {len(config)} 个字段,不值得分档:{bad}"


def test_分档没有退化成摆设() -> None:
    """一个都不标(或几乎不标),这套分档就只是多了一个永远空着的档。

    不写死具体数字 —— 那会变成每加一个字段就要改测试。只钉住"确实用起来了"。
    """
    total = sum(len(spec.get("config") or {}) for spec in NODE_TYPES.values())
    advanced = sum(
        1 for spec in NODE_TYPES.values() for meta in (spec.get("config") or {}).values() if (meta or {}).get("advanced")
    )
    assert advanced * 10 >= total, f"只有 {advanced}/{total} 个字段标了高级,分档基本没起作用"
    assert advanced * 2 <= total, f"{advanced}/{total} 个字段进了高级,那第一屏就没剩下什么了"
