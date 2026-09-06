"""片段的时间必须是**有限的数**。

`_validate_clip_range` 判的是 `timeline_start < 0`、`src_in < 0`、`src_out <= src_in`。
**任何和 NaN 的比较都是 False**,所以这三条对 NaN 全部放行;Infinity 同理(inf < 0 是 False,
而 src_out=inf 比任何 src_in 都大)。

后果比画布那个更重:

· NaN 存进去之后,序列序列化出的 `{"timeline_start": NaN}` 不是合法 JSON —— 这条时间线
  在浏览器里再也打不开;
· src_out=inf 是一段**无限长**的片段,而它会进渲染计划。

来源不必是恶意客户端:前端算时间码时一次除以零(时长为 0 的素材、缩放为 0)就是 NaN,
智能体的 edit_timeline 也直接收这几个数。
"""

from __future__ import annotations

import pytest

from app.domain.sequences.operations import SequenceDomainError, _validate_clip_range

BAD = [float("nan"), float("inf"), float("-inf")]


@pytest.mark.parametrize("bad", BAD)
def test_timeline_start_非有限就拒绝(bad: float) -> None:
    with pytest.raises(SequenceDomainError):
        _validate_clip_range(bad, 0.0, 1.0)


@pytest.mark.parametrize("bad", BAD)
def test_src_in_非有限就拒绝(bad: float) -> None:
    with pytest.raises(SequenceDomainError):
        _validate_clip_range(0.0, bad, 1.0)


@pytest.mark.parametrize("bad", BAD)
def test_src_out_非有限就拒绝(bad: float) -> None:
    """src_out=inf 尤其要挡:它比任何 src_in 都大,所以"出点要晚于入点"那条判据是满足的
    —— 而它是一段无限长的片段,会一路进到渲染计划里。"""
    with pytest.raises(SequenceDomainError):
        _validate_clip_range(0.0, 0.0, bad)


def test_正常的值照旧() -> None:
    _validate_clip_range(0.0, 0.0, 1.0)
    _validate_clip_range(12.5, 3.25, 9.75)


def test_报错要说清楚是哪一个() -> None:
    """「参数不合法」帮不上忙 —— 时间线上有三个数,得知道是哪一个。"""
    for index, field in enumerate(("timeline_start", "src_in", "src_out")):
        args = [0.0, 0.0, 1.0]
        args[index] = float("nan")
        with pytest.raises(SequenceDomainError) as error:
            _validate_clip_range(*args)
        assert field in str(error.value), f"{field} 的报错没点名它自己:{error.value}"
