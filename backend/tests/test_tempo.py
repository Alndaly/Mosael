"""atempo 链只有一份(media/tempo):成片渲染和对口型配音此前各写了一遍同一个拆分算法。"""

from __future__ import annotations

import math

from app.media.tempo import atempo_filters


def _product(chain: str) -> float:
    return math.prod(float(part.removeprefix("atempo=")) for part in chain.rstrip(",").split(","))


def test_原速不加滤镜() -> None:
    assert atempo_filters(1.0) == ""


def test_超出一级的范围就串起来_每一级都在_0_5_到_2_之间() -> None:
    assert atempo_filters(3.0) == "atempo=2.0,atempo=1.5,"
    for speed in (0.2, 0.25, 0.7, 1.3, 2.0, 5.0, 9.0):
        chain = atempo_filters(speed)
        assert chain.endswith(",")
        assert all(0.5 <= float(part.removeprefix("atempo=")) <= 2.0 for part in chain.rstrip(",").split(","))
        assert math.isclose(_product(chain), speed)
