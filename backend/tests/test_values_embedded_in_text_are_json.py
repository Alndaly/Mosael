"""一个值被**嵌进一段文字**时,写成 JSON,而不是 Python 的 repr。

`{{节点.输出}}` 独占整个字段时保留原类型(列表还是列表);嵌在文字里时要变成字符串 —— 此前用的
是 `str()`,于是对象嵌进 HTTP 请求体是 `{'ok': True, 'n': None}`:单引号、`True`、`None`,
没有一个 JSON 解析器认它。同一个值独占 `body` 字段时也一样(执行器最后还是 `str()` 了它)。
布尔值则写成 `True` / `False`,和条件节点右边照 JSON 习惯写的 `true` 永远对不上。

"值变成文字"只有一种写法(`as_text`),插值和各个把值当文字用的节点都走它。
"""

from __future__ import annotations

import json

import pytest

from app.domain.workflows import as_text, interpolate
from app.domain.workflows.executors.basic import condition, http_request, template


def test_嵌进文字的对象和布尔是_JSON() -> None:
    context = {"je": {"value": {"ok": True, "n": None, "名": "猫"}}, "check": {"result": False}}
    embedded = interpolate("body={{je.value}}", context)
    assert json.loads(embedded.removeprefix("body=")) == {"ok": True, "n": None, "名": "猫"}
    assert interpolate("是否:{{check.result}}", context) == "是否:false"
    # 独占整个字段时仍然保留原类型。
    assert interpolate("{{je.value}}", context) == {"ok": True, "n": None, "名": "猫"}


def test_as_text_的几种形状() -> None:
    assert as_text("原样") == "原样"
    assert as_text(None) == ""
    assert as_text(3) == "3"
    assert as_text(True) == "true"
    assert as_text(["a", 1]) == '["a", 1]'


def test_HTTP_请求体收到对象时发出去的是_JSON(monkeypatch) -> None:
    sent: dict = {}

    class _Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    def fake_request(method, url, *, headers, content, timeout):
        sent["content"] = content
        return _Response()

    monkeypatch.setattr("app.domain.workflows.executors.basic.httpx.request", fake_request)
    # 数据边 / 整串引用把一个对象原样交给 body。
    http_request(None, None, {"method": "POST", "url": "http://example.invalid", "body": {"ok": True, "n": None}})
    assert json.loads(sent["content"]) == {"ok": True, "n": None}


def test_模板独占一个对象引用时产出_JSON_文本() -> None:
    assert json.loads(template(None, None, {"template": {"a": [1, 2]}})["text"]) == {"a": [1, 2]}


@pytest.mark.parametrize(("left", "right", "expected"), [(True, "true", True), (False, "true", False), (None, "", True)])
def test_条件拿布尔和照_JSON_写的字面量比(left, right, expected) -> None:
    assert condition(None, None, {"left": left, "op": "equals", "right": right}) == {"result": expected}
