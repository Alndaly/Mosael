"""迁移修好的旧形状,不会借着导入旧文件、恢复旧修订、插件清单晚到这三条路回来。

## 现场

1.8.1 改了三处图的形状(代码字段的 `{{…}}` 改读入参、循环 output 错接的外层数据边改回体内引用、插件数组入参
从映射改成列表),都由迁移改库里的图。可是:

- 导入一份老版本导出的文件,图原样落库 —— 循环 output 又是一条外层数据边,代码里的 `{{…}}` 成了不起作用的字面量;
- 恢复到升级之前的某一版(迁移改不到历史修订),同上;
- 插件数组迁移只改得了它跑的那一刻认得出的,工具清单晚到的节点留着映射,跑的时候交给插件的还是一个对象。

修法:「旧 → 新」的改写下沉到领域层的图升级(graph_upgrade),迁移、导入、恢复修订共用;插件数组的那一步在
规范化里(保存、导入、模板都走),另有一条每次启动的对账按当时的声明补改。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import User, Workflow
from app.domain.workflows.code_references import JS_AS_TEXT
from app.domain.workflows.revisions import commit_graph_revision, graph_digest
from tests.util import fresh_client, wait_status


def _old_graph() -> dict:
    """1.8.0 存下 / 导出的样子:循环的 output 被接成了外层数据边(体内也有一个 t),执行脚本里直接写 {{…}}。"""
    body = {"nodes": [{"id": "t", "type": "template", "config": {"template": "体内 {{loop.item}}"}}], "edges": []}
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "t", "type": "template", "config": {"template": "外层"}},
            {"id": "each", "type": "loop_foreach", "inputs": ["output"],
             "config": {"items": "a\nb", "body": body, "output": ""}},
            {"id": "js", "type": "browser_evaluate",
             "config": {"session": "s", "expression": "document.title + '{{t.text}}'"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "t"},
            {"id": "d1", "source": "t", "target": "each", "kind": "data", "source_output": "text", "target_input": "output"},
        ],
    }


def _assert_upgraded(graph: dict) -> None:
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["each"]["config"]["output"] == "{{t.text}}"
    assert not [edge for edge in graph["edges"] if edge.get("kind") == "data" and edge.get("target") == "each"]
    assert nodes["js"]["config"]["expression"] == f"document.title + '' + {JS_AS_TEXT}(input.t_text) + ''"
    assert nodes["js"]["config"]["input"] == {"t_text": "{{t.text}}"}


def _run(client, workflow_id: str) -> dict:
    started = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}})
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"]) == "succeeded"
    return client.get(f"/api/jobs/{started.json()['id']}").json()["result"]["context"]


def _without_js(graph: dict) -> dict:
    """跑一遍循环看交出的是哪个值(执行脚本要真浏览器,跑的时候拿掉它)。"""
    return {**graph, "nodes": [node for node in graph["nodes"] if node["id"] != "js"]}


def test_导入老版本导出的文件_图升级成现在的形状_循环交出体内的值() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    envelope = {"format": "mosael-workflow", "version": 1, "name": "老文件", "graph": _old_graph()}
    imported = client.post("/api/workflows/import", json={"workspace_id": ws, "data": envelope})
    assert imported.status_code == 200, imported.text
    _assert_upgraded(imported.json()["graph"])

    runnable = client.post("/api/workflows/import", json={
        "workspace_id": ws, "data": {**envelope, "name": "能跑的", "graph": _without_js(_old_graph())},
    }).json()
    assert _run(client, runnable["id"])["each"]["results"] == ["体内 a", "体内 b"]


def test_恢复到升级之前的那一版_恢复的那份先升级() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post("/api/workflows", json={"workspace_id": ws, "name": "流程"}).json()
    # v1 是 1.8.0 存下的老形状(那时的保存就是这么落的);迁移改了库里的当前图,改不到这一版。
    old = _old_graph()
    with engine.begin() as connection:
        connection.execute(text("UPDATE workflow_revisions SET graph = :g, graph_hash = :h WHERE workflow_id = :id"),
                           {"g": json.dumps(old, ensure_ascii=False), "h": graph_digest(old), "id": created["id"]})
        connection.execute(text("UPDATE workflows SET graph = :g, graph_hash = :h WHERE id = :id"),
                           {"g": json.dumps(old, ensure_ascii=False), "h": graph_digest(old), "id": created["id"]})
    with SessionLocal() as db:
        author = db.query(User).filter(User.username == "tester").one().id
        commit_graph_revision(db, db.get(Workflow, created["id"]), lambda _graph: {"nodes": [], "edges": []},
                              source="edit", created_by=author)
        db.commit()

    restored = client.post(f"/api/workflows/{created['id']}/revisions/1/restore")
    assert restored.status_code == 200, restored.text
    _assert_upgraded(restored.json()["graph"])
    assert restored.json()["revision"] == 3


def test_插件数组入参_保存时按声明改成列表_清单晚到的由对账补改_跑起来交给插件的是数组(tmp_path) -> None:
    from app.db.migrations import _plugin_array_inputs_follow_their_declarations
    from tests.test_plugin_nodes_hold_what_they_declare import PACKAGE, _graph, _install

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    node = {"id": "j", "type": f"plugin.{PACKAGE}.join", "config": {"items": {"a": "第一段", "b": "第二段"}}}

    _install(tmp_path, _uid())
    saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "现在存的", "graph": _graph(node)}).json()
    assert saved["graph"]["nodes"][1]["config"]["items"] == ["第一段", "第二段"]

    # 一次性迁移跑的那一刻工具清单还没报上来:库里那条原样留着映射(当前图和修订都是)。
    kept = client.post("/api/workflows", json={"workspace_id": ws, "name": "老的", "graph": _graph(
        {**node, "config": {"items": []}})}).json()
    stale = _graph(node)
    with engine.begin() as connection:
        for table, column in (("workflows", "id"), ("workflow_revisions", "workflow_id")):
            connection.execute(text(f"UPDATE {table} SET graph = :g, graph_hash = :h WHERE {column} = :id"),
                               {"g": json.dumps(stale, ensure_ascii=False), "h": graph_digest(stale), "id": kept["id"]})

    # 由对账按此刻的声明补改(落一版修订),重跑不动。
    _plugin_array_inputs_follow_their_declarations()
    _plugin_array_inputs_follow_their_declarations()
    with SessionLocal() as db:
        workflow = db.get(Workflow, kept["id"])
        assert workflow.revision == 2
        assert workflow.graph["nodes"][1]["config"]["items"] == ["第一段", "第二段"]
    assert _run(client, kept["id"])["j"]["joined"] == "第一段|第二段"


def _uid() -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == "tester").one().id
