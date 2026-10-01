"""循环 / 子图的 `output`、条件循环的 `condition` 属于**体内**作用域,规范化不许把它们接成外层数据边。

## 现场

规范化把精确引用 `{{节点.输出}}` 升级成数据边,只跳过 object / graph 类型的字段,没排除内嵌子图
节点的 output / condition。节点 id 只在当前层唯一,外层和体内都有一个 `llm-1` 是常态 —— 于是
`output: "{{llm-1.text}}"`(体里那个)保存后被清空,多出一条**来自外层 llm-1** 的数据边:循环每一项
交出的都是外层那一个值;loop_while 的条件绑到了外层的布尔值上。

迁移 migrate-loop-scopes-are-not-outer-data-edges 把已经被改写的图改回来。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_loop_scopes_are_not_outer_data_edges
from app.db.models import Workflow, WorkflowRevision
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.revisions import current_workflow_revision
from tests.util import fresh_client


def _body(template: str = "体内 {{loop.index}}") -> dict:
    return {"nodes": [{"id": "llm-1", "type": "template", "config": {"template": template}}], "edges": []}


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "llm-1", "type": "template", "config": {"template": "外层"}},
            {"id": "each", "type": "loop_foreach", "config": {"items": "a\nb", "body": _body(), "output": "{{llm-1.text}}"}},
            {"id": "again", "type": "loop_while",
             "config": {"body": _body(), "condition": "{{llm-1.text}}", "output": "{{llm-1.text}}", "max_iterations": 2}},
            {"id": "sub", "type": "subgraph", "config": {"inputs": {}, "body": _body("体内"), "output": "{{llm-1.text}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm-1"},
            {"id": "e2", "source": "llm-1", "target": "each"},
            {"id": "e3", "source": "llm-1", "target": "again"},
            {"id": "e4", "source": "start", "target": "sub"},
        ],
    }


def test_规范化不碰体内作用域的字段() -> None:
    graph = _graph()
    normalized = normalize_graph(graph, node_types=NODE_TYPES)
    nodes = {node["id"]: node for node in normalized["nodes"]}
    assert nodes["each"]["config"]["output"] == "{{llm-1.text}}"
    assert nodes["again"]["config"]["condition"] == "{{llm-1.text}}"
    assert nodes["again"]["config"]["output"] == "{{llm-1.text}}"
    assert nodes["sub"]["config"]["output"] == "{{llm-1.text}}"
    assert not [edge for edge in normalized["edges"] if edge.get("kind") == "data"], "体内引用被接成了外层数据边"
    #: 控制边一条不少(没有数据边,也就没有可折的)。
    assert {edge["id"] for edge in normalized["edges"]} == {"e1", "e2", "e3", "e4"}


def test_保存之后体内引用原样留着_循环交出的是体内那个值() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post("/api/workflows", json={"workspace_id": ws, "name": "同名"}).json()
    saved = client.patch(
        f"/api/workflows/{created['id']}", json={"graph": _graph(), "base_graph_hash": created["graph_hash"]}
    )
    assert saved.status_code == 200, saved.text
    nodes = {node["id"]: node for node in saved.json()["graph"]["nodes"]}
    assert nodes["each"]["config"]["output"] == "{{llm-1.text}}"

    run = client.post(f"/api/workflows/{created['id']}/run", json={"params": {}})
    assert run.status_code == 200, run.text
    from tests.util import wait_status

    assert wait_status(client, run.json()["id"]) == "succeeded"
    result = client.get(f"/api/jobs/{run.json()['id']}").json()["result"]["context"]
    assert result["each"]["results"] == ["体内 0", "体内 1"]
    assert result["again"]["results"] == ["体内 0", "体内 1"]
    assert result["sub"]["output"] == "体内"


def _corrupted() -> dict:
    """被旧规范化改写过的样子:output / condition 清空,多了来自外层 llm-1 的数据边,控制边被折掉。"""
    graph = _graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    nodes["each"]["config"]["output"] = ""
    nodes["each"]["inputs"] = ["output"]
    nodes["again"]["config"]["condition"] = ""
    nodes["again"]["config"]["output"] = "已经重填过"
    nodes["again"]["inputs"] = ["condition", "output"]
    graph["edges"] = [
        {"id": "e1", "source": "start", "target": "llm-1"},
        {"id": "e4", "source": "start", "target": "sub"},
        {"id": "d-llm-1-text-each-output", "source": "llm-1", "target": "each", "kind": "data",
         "source_output": "text", "target_input": "output"},
        {"id": "d-llm-1-text-again-condition", "source": "llm-1", "target": "again", "kind": "data",
         "source_output": "text", "target_input": "condition"},
        {"id": "d-llm-1-text-again-output", "source": "llm-1", "target": "again", "kind": "data",
         "source_output": "text", "target_input": "output"},
    ]
    # 体内一层嵌套的循环也被改写过。
    inner_loop = {"id": "inner", "type": "loop_foreach", "config": {"items": "x", "body": _body(), "output": ""}}
    nodes["sub"]["config"]["body"] = {
        "nodes": [*_body("体内")["nodes"], inner_loop],
        "edges": [{"id": "d-llm-1-text-inner-output", "source": "llm-1", "target": "inner", "kind": "data",
                   "source_output": "text", "target_input": "output"}],
    }
    return graph


def _as_saved_by_1_8_0(workflow_id: str, graph: dict) -> None:
    """1.8.0 存下的样子:当前图和最新那一版修订都是被改写过的那份(那时的保存就是这么落的)。"""
    from app.domain.workflows.revisions import graph_digest

    stored, digest = json.dumps(graph, ensure_ascii=False), graph_digest(graph)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE workflows SET graph = :graph, graph_hash = :hash WHERE id = :id"),
            {"graph": stored, "hash": digest, "id": workflow_id},
        )
        connection.execute(
            text("UPDATE workflow_revisions SET graph = :graph, graph_hash = :hash WHERE workflow_id = :id"),
            {"graph": stored, "hash": digest, "id": workflow_id},
        )


def _stored(workflow_id: str) -> dict:
    with engine.begin() as connection:
        return json.loads(
            connection.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}).scalar_one()
        )


def test_迁移把错接的数据边改回体内引用_补回被折掉的控制边_修订对上_重跑不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow_id = client.post("/api/workflows", json={"workspace_id": ws, "name": "被改写过"}).json()["id"]
    untouched_id = client.post("/api/workflows", json={"workspace_id": ws, "name": "没事的"}).json()["id"]
    _as_saved_by_1_8_0(workflow_id, _corrupted())
    untouched = _stored(untouched_id)

    _migrate_loop_scopes_are_not_outer_data_edges()

    graph = _stored(workflow_id)
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["each"]["config"]["output"] == "{{llm-1.text}}"
    assert nodes["again"]["config"]["condition"] == "{{llm-1.text}}"
    assert nodes["again"]["config"]["output"] == "已经重填过", "重填过的不该被覆盖"
    assert nodes["each"]["inputs"] == [] and nodes["again"]["inputs"] == []
    assert not [edge for edge in graph["edges"] if edge.get("kind") == "data"]
    pairs = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("llm-1", "each") in pairs and ("llm-1", "again") in pairs, "被折掉的控制边没补回来"
    assert len([edge for edge in graph["edges"] if (edge["source"], edge["target"]) == ("llm-1", "again")]) == 1
    inner = next(node for node in nodes["sub"]["config"]["body"]["nodes"] if node["id"] == "inner")
    assert inner["config"]["output"] == "{{llm-1.text}}"
    assert nodes["sub"]["config"]["body"]["edges"] == [{"id": "c-llm-1-inner", "source": "llm-1", "target": "inner"}]
    assert _stored(untouched_id) == untouched

    with SessionLocal() as db:
        workflow = db.get(Workflow, workflow_id)
        assert current_workflow_revision(db, workflow).graph == graph
        revisions = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count()

    _migrate_loop_scopes_are_not_outer_data_edges()
    assert _stored(workflow_id) == graph
    with SessionLocal() as db:
        assert db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count() == revisions
