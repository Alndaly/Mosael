"""条件节点里照旧写法手写的 `True` / `False`,迁移后跟得上 JSON 写法的布尔。

值当文字用改成 JSON 之后(workflows.as_text),上游的布尔在条件里读作 `true`。库里照 `str()`
时代写好的 `True` 由 `_migrate_condition_literals_are_json` 一次改好 —— 条件节点不为旧写法留分支。
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import interpolate
from app.domain.workflows.executors import get_executor


def _condition(node_id: str, left: str, right: str) -> dict:
    return {"id": node_id, "type": "condition", "config": {"left": left, "op": "equals", "right": right}}


def _graph() -> dict:
    loop = {"id": "loop", "type": "loop_foreach", "config": {
        "items": "[]", "body": {"nodes": [_condition("inner", "{{loop.item.ok}}", "False")], "edges": []},
    }}
    return {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        _condition("check", "{{llm.json.ok}}", "True"),
        _condition("keep", "{{llm.json.ok}}", "True or not"),
        loop,
    ], "edges": []}


def test_迁移后照旧写法写的条件又对得上上游的布尔() -> None:
    from app.db.migrations import _migrate_condition_literals_are_json
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟改成 JSON 写法之前落库的图。
        workflow = Workflow(workspace_id=ws, name="旧图", graph=_graph())
        db.add(workflow)
        db.commit()
        workflow_id = workflow.id

    _migrate_condition_literals_are_json()
    _migrate_condition_literals_are_json()

    with SessionLocal() as db:
        graph = db.get(Workflow, workflow_id).graph
        graph = json.loads(graph) if isinstance(graph, str) else graph
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["check"]["config"]["right"] == "true"
    assert nodes["keep"]["config"]["right"] == "True or not"  # 不是整格字面量的不动
    assert nodes["loop"]["config"]["body"]["nodes"][0]["config"]["right"] == "false"

    config = interpolate(nodes["check"]["config"], {"llm": {"json": {"ok": True}}})
    assert get_executor("condition")(None, None, config)["result"] is True
