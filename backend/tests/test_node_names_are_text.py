"""节点名字落库时是文字:模板里那种 `{zh, en}` 的名字进了库,打开工作流页就崩,整页都进不去。"""

from __future__ import annotations

from tests.util import fresh_client

BILINGUAL = {"zh": "开始", "en": "Start"}


def test_导入带双语名字的文件_落库时定成一种语言_循环体里的也是() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    body = {"nodes": [{"id": "inner", "type": "template", "name": {"zh": "里面", "en": "Inside"}, "config": {}}], "edges": []}
    graph = {"nodes": [
        {"id": "start", "type": "start", "name": BILINGUAL, "config": {}},
        {"id": "L", "type": "loop_foreach", "name": "循环", "config": {"items": "[]", "body": body}},
    ], "edges": []}
    made = client.post("/api/workflows/import", headers={"Accept-Language": "zh-CN"}, json={"workspace_id": ws, "data": {
        "format": "mosael-workflow", "version": 1, "name": "双语", "graph": graph,
    }})
    assert made.status_code == 200, made.text
    nodes = made.json()["graph"]["nodes"]
    assert nodes[0]["name"] == "开始"
    assert nodes[1]["config"]["body"]["nodes"][0]["name"] == "里面"
