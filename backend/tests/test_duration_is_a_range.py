"""视频时长有两种形状:**枚举**和**区间**。

Seedance 2 此前写的是 `[5, 10]`,于是界面只给这两个选项。而真机实测(2026-08-27,
doubao-seedance-2-0-260128):

    3s  → 400 the specified duration is not supported
    4s  → 200
    7s  → 200
    12s → 200
    15s → 200
    16s → 400

**它是 4–15 的任意整数**,不是两个档位。写成枚举等于把十二个可选值砍成两个,而用户看不出
少了什么 —— 下拉里只有 5 和 10,看着就像这个模型只支持这两种。

校验也要认区间。只校验枚举的话,区间型的模型全放行,越界的值要等供应商拒了才知道 ——
而那时任务已经建好、扣了一次配额,报的还是一句英文的 InvalidParameter。
"""

from __future__ import annotations

import pytest

from app.domain.generation.catalog import SEEDANCE_2_VIDEO_CAPABILITIES as SEEDANCE_2
from app.domain.generation.operations import GenerationDomainError, validate_against_capabilities


class Test描述符:
    def test_seedance2_是区间不是枚举(self) -> None:
        assert SEEDANCE_2["duration_seconds"] == [], "还写着枚举 —— 界面会退回下拉,只给那几个档"
        assert SEEDANCE_2["min_duration_seconds"] == 4
        assert SEEDANCE_2["max_duration_seconds"] == 15

    def test_默认值落在区间内(self) -> None:
        """默认值越界的话,什么都不改直接点生成就会被拒。"""
        assert SEEDANCE_2["min_duration_seconds"] <= SEEDANCE_2["default_duration_seconds"] <= SEEDANCE_2["max_duration_seconds"]


def _check(duration: int) -> None:
    validate_against_capabilities(
        "bytedance", "doubao-seedance-2-0-260128", "video", {"duration_seconds": duration}, []
    )


class Test区间校验:
    @pytest.mark.parametrize("seconds", [4, 5, 7, 12, 15])
    def test_区间内放行(self, seconds: int) -> None:
        _check(seconds)

    @pytest.mark.parametrize("seconds", [3, 16, 30])
    def test_区间外拦下(self, seconds: int) -> None:
        """这几个真机上确实被拒。在这里拦住,用户看到的是中文的「要在 4–15 秒之间」,
        而不是任务失败之后一句英文的 InvalidParameter。"""
        with pytest.raises(GenerationDomainError, match="4"):
            _check(seconds)


class Test枚举型不受影响:
    def test_只收枚举里那几个(self) -> None:
        """万相只支持 5 秒(枚举)。加了区间那条路之后,枚举这条不该跟着松掉。"""
        from app.domain.generation.catalog import WAN_VIDEO_CAPABILITIES as WAN

        assert WAN["duration_seconds"] == [5], "万相是枚举型 —— 这条用例的前提"
        with pytest.raises(GenerationDomainError):
            validate_against_capabilities("alibaba", "wan2.2-t2v-plus", "video", {"duration_seconds": 7}, [])
