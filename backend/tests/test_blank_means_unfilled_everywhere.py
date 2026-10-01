"""必填、只能填一个(one_of)的「空着」,后端和画布的就绪检查是同一个判据:空白、空列表、空对象都算没填。

## 现场

画布(analyze.ts 的 isEmpty)把空白、`[]`、`{}` 判成没填;后端的必填 / one_of 只认 None 和空串。于是一个
只敲了空格的「网址」画布说没填、后端放行,跑到那一步才失败;点击节点的「选择器」留了个空格、又填了
「文字」,画布说填了一个、后端说「只能填一个」。
"""

from __future__ import annotations

import pytest

from app.domain.workflows import validate_graph
from tests.util import fresh_client


def _graph(node: dict) -> dict:
    return {"nodes": [{"id": "start", "type": "start", "config": {"params": {}}}, node],
            "edges": [{"id": "e1", "source": "start", "target": node["id"]}]}


@pytest.mark.parametrize("value", ["   ", [], {}])
def test_必填字段空白_空列表_空对象都算没填(value) -> None:
    errors = validate_graph(_graph({"id": "loop", "type": "loop_foreach", "config": {
        "items": value, "body": {"nodes": [{"id": "t", "type": "template", "config": {"template": "x"}}], "edges": []},
    }}))
    assert "节点 loop 缺少必填配置 items" in errors


def test_one_of_里留了空格的那一格不算填了() -> None:
    errors = validate_graph(_graph({"id": "click", "type": "browser_click",
                                    "config": {"session": "s", "selector": "  ", "text": "提交"}}))
    assert not [one for one in errors if "click" in one], errors
    errors = validate_graph(_graph({"id": "click", "type": "browser_click",
                                    "config": {"session": "s", "selector": " ", "text": "\n"}}))
    assert "节点 click 的 selector / text 要填一个" in errors


def test_只敲了空格的必填_点运行当场就拒() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "请求", "graph": _graph(
        {"id": "req", "type": "http_request", "config": {"method": "GET", "url": "   "}},
    )}).json()
    refused = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}})
    assert refused.status_code == 422, refused.text
    assert "req" in refused.text and "url" in refused.text
