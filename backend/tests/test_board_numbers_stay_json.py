"""画板上的坐标和尺寸必须是**能序列化回 JSON 的数**。

`NaN` / `Infinity` 是 Python float 的合法取值,`json.dumps` 也照写不误 —— 写出来的
`{"x": NaN}` 却**不是合法 JSON**,浏览器的 `JSON.parse` 直接抛。于是一张画板只要混进一个
NaN,它就再也打不开了:用户看到的是"我的画板坏了",而库里那份数据其实完好。

不是只有恶意客户端才能造出它:前端在拖拽/缩放时算坐标,一次除以零(缩放为 0、宽度为 0)
就是 NaN,而那个值会一路存进去,不报错。这类 bug 的代价不成比例 —— 一个瞬时的计算失误
换来一张永久打不开的画板。
"""

from __future__ import annotations

import json

import pytest

from app.domain.boards import BoardDomainError, normalize_canvas


def _canvas(x: object) -> dict:
    return {"items": [{"id": "a", "kind": "note", "x": x, "y": 0}], "edges": []}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_非有限数一律拒绝(bad: float) -> None:
    with pytest.raises(BoardDomainError) as error:
        normalize_canvas(_canvas(bad))
    # 报错要点名是哪一项的哪个字段 —— "画布不合法"帮不上任何忙。
    assert "x" in str(error.value)


def test_正常的数照旧() -> None:
    out = normalize_canvas(_canvas(12.5))
    assert out["items"][0]["x"] == 12.5
    # 负坐标是合法的:画布可以往左上方向延伸。
    assert normalize_canvas(_canvas(-40))["items"][0]["x"] == -40


def test_算子那一侧同样挡() -> None:
    """智能体走的是 apply_board_ops,它有自己的 _number —— 两处都要挡,否则挡住的那条路
    只是把入口挪了一下。"""
    from app.domain.board_ops import apply_board_ops
    from app.domain.boards import BoardDomainError as Err

    with pytest.raises(Err):
        apply_board_ops({"items": [], "edges": []}, [{"kind": "add_item", "type": "note", "x": float("nan"), "y": 0}])
    with pytest.raises(Err):
        apply_board_ops(
            {"items": [{"id": "a", "kind": "note", "x": 0, "y": 0}], "edges": []},
            [{"kind": "move_item", "item_id": "a", "x": float("inf"), "y": 0}],
        )


def test_归一后的画布一定是合法_JSON() -> None:
    """最终判据:不管前面怎么校验,吐出去的东西得能被浏览器读。"""
    out = normalize_canvas(_canvas(3))
    # parse_constant 只在遇到 NaN/Infinity/-Infinity 时被调用 —— 拿它当探针。
    json.loads(json.dumps(out), parse_constant=lambda name: pytest.fail(f"序列化出了 {name}"))
