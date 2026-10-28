"""按路径取值时 `*` 表示「这一串里的每一个」:从循环交出的一串结果里取出每一项的某一格。

模特上身图要把每一组的视频也列进输出:循环交出的是每一组的全部产物,「每一组的视频」就是
`*.on_model_clip.asset_id`。哪一组没有这一格(视频没出来)就不在结果里,不拿空值占位。
"""

from __future__ import annotations

from app.domain.workflows.executors.registry import get_executor

RESULTS = [
    {"on_model": {"asset_id": "img-1"}, "on_model_clip": {"asset_id": "clip-1"}},
    {"on_model": {"asset_id": "img-2"}},
    {"on_model": {"asset_id": "img-3"}, "on_model_clip": {"asset_id": "clip-3"}},
]


def _extract(source, path: str) -> dict:
    return get_executor("json_extract")(None, None, {"source": source, "path": path})


def test_星号取出每一项的那一格_没有那一格的不占位() -> None:
    assert _extract(RESULTS, "*.on_model_clip.asset_id")["value"] == ["clip-1", "clip-3"]
    assert _extract(RESULTS, "*.on_model.asset_id")["value"] == ["img-1", "img-2", "img-3"]


def test_星号可以在路径中间_也收_JSON_文本() -> None:
    import json

    wrapped = {"results": RESULTS}
    assert _extract(wrapped, "results.*.on_model.asset_id")["value"] == ["img-1", "img-2", "img-3"]
    assert _extract(json.dumps(wrapped), "results.*.on_model_clip.asset_id")["text"] == '["clip-1", "clip-3"]'


def test_没有星号照旧取一格() -> None:
    assert _extract(RESULTS, "0.on_model.asset_id")["value"] == "img-1"
    assert _extract(RESULTS, "[2].on_model_clip.asset_id")["value"] == "clip-3"


def test_没有星号时取不到就报错_星号下没有的只是不占位() -> None:
    import pytest

    from app.domain.workflows.errors import WorkflowDomainError

    with pytest.raises(WorkflowDomainError) as missing:
        _extract(RESULTS, "1.on_model_clip.asset_id")
    assert missing.value.params["at"] == "1.on_model_clip"
    assert _extract(RESULTS, "*.nothing")["value"] == []


def test_来源是空的而路径要往里走_直说来源空() -> None:
    """维护者踩过:来源(上游 JSON 输出)是空的,旧报错却丢一句「走到「0」那一段时没有它 · 那一层是:""」,
    把「上游没东西」藏成了「路径不对」,人照着路径改死也修不好。现在来源空且要往里走时直说来源空。"""
    import pytest

    from app.domain.workflows.errors import WorkflowDomainError

    with pytest.raises(WorkflowDomainError) as empty:
        _extract("", "0.name")
    assert empty.value.key == "wfErr_jsonSourceEmpty"
    assert empty.value.params["path"] == "0.name"
    assert "来源是空的" in str(empty.value)
    # None 来源同样
    with pytest.raises(WorkflowDomainError):
        _extract(None, "a.b")
    # wildcard 开头对**空来源**是故意宽容的:「每一个」就是零个,返回 [](真实模板 *.on_model.asset_id 靠这个)。
    assert _extract("", "*.name")["value"] == []
    assert _extract(None, "*")["value"] == []


def test_长度保留段_列表字典字符串都给_len() -> None:
    """`$length` 取这一层的长度:列表给元素个数、字典给键数、字符串给字符数 —— 列表长度这种小操作
    不用为此开一个 code 节点(Docker 沙箱)。真实 JSON 键几乎不会叫 `$length`,保留段不撞。
    """
    chars = [{"name": "林晚"}, {"name": "沈昼"}, {"name": "程雪"}]
    assert _extract(chars, "$length")["value"] == 3
    assert _extract({"characters": chars}, "characters.$length")["value"] == 3
    assert _extract("你好世界", "$length")["value"] == 4
    assert _extract({"a": 1, "b": 2}, "$length")["value"] == 2
    assert _extract([], "$length")["value"] == 0
    # 和星号配合:每一项的 name 是几个字(*.$length 落在每个字典上是键数,要名字长度得 *.name.$length)
    assert _extract([{"name": "ab"}, {"name": "cde"}], "*.$length")["value"] == [1, 1]
    assert _extract([{"name": "ab"}, {"name": "cde"}], "*.name.$length")["value"] == [2, 3]
    # JSONPath 根写法 `$` / `$.` 照常,不会被 `$length` 的根符号干扰
    assert _extract({"items": chars}, "$.items.$length")["value"] == 3
    # 取不到长度的(数字/None)走 missing 报错,不瞎猜
    import pytest

    from app.domain.workflows.errors import WorkflowDomainError

    with pytest.raises(WorkflowDomainError):
        _extract(42, "$length")
    # 路径留空 = 取整个值:来源空也照实交出空串,不报错
    assert _extract("", "")["value"] == ""


def test_顶层列表的裸下标和星号照旧取得到() -> None:
    # 维护者误以为开头裸 0 不认 —— 它对列表就是 int(下标),等价 [0];提示里"也可以写 data.items.0.title"就是它。
    assert _extract('[{"name": "林澜"}, {"name": "陈默"}]', "0.name")["value"] == "林澜"
    assert _extract('[{"name": "林澜"}, {"name": "陈默"}]', "*.name")["value"] == ["林澜", "陈默"]
