"""one_of 认「引用在前、兜底在后」;「只填一样」那次迁移删掉的兜底从修订历史里找回来。

## 现场

「点击」的选择器写 `{{上游.选择器}}`、文字填一个兜底 —— 上游给空时执行器按顺序落到文字那格(点击先认选择器、
等待按「元素 → 网址 → 文字」)。one_of 却把它判成「只能填一个」,1.8.1 的迁移照这条规矩把兜底删了。

规矩(和前端 analyze / fieldActivation 同一条):同组按声明顺序,最后一个填了的之前,填了的每一格都是整格一条
引用(`^\\s*\\{\\{\\s*[\\w.-]+\\s*\\}\\}\\s*$`)或接了数据边,就放行。两样都给就报错的组(浏览器上传,
`one_of_strict`)照旧恰好一个。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.migrations import _BROWSER_ONE_TARGET_NOTE, _migrate_browser_fallback_targets_come_back
from app.db.models import Workflow, WorkflowRevision
from app.domain.workflows import validate_graph
from tests.util import fresh_client


def _graph(*nodes: dict, edges: list | None = None) -> dict:
    return {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {"sel": "#x", "url": "/done"}}},
                  {"id": "t", "type": "template", "config": {"template": "#a"}}, *nodes],
        "edges": edges or [],
    }


def _errors(node: dict, edges: list | None = None) -> list[str]:
    return [one for one in validate_graph(_graph(node, edges=edges)) if node["id"] in one]


@pytest.mark.parametrize(("config", "ok"), [
    ({"selector": "{{t.text}}", "text": "去"}, True),
    ({"selector": " {{ t.text }} ", "text": "去"}, True),
    ({"selector": "#go", "text": "去"}, False),
    ({"selector": "#go", "text": "{{t.text}}"}, False),
    ({"selector": "{{t.text}} 后面还有字", "text": "去"}, False),
])
def test_点击_引用在前兜底在后放行_字面量在前不行(config: dict, ok: bool) -> None:
    errors = _errors({"id": "c", "type": "browser_click", "config": {"session": "s", **config}})
    assert (not errors) is ok, errors


def test_等待_前两格都是引用或接了数据边_最后一格兜底() -> None:
    edges = [{"id": "d", "source": "t", "target": "w", "kind": "data", "source_output": "text", "target_input": "url_contains"}]
    assert not _errors({"id": "w", "type": "browser_wait",
                        "config": {"session": "s", "selector": "{{start.sel}}", "url_contains": "", "text": "完成"}},
                       edges)
    assert _errors({"id": "w", "type": "browser_wait",
                    "config": {"session": "s", "selector": "{{start.sel}}", "url_contains": "/done", "text": "完成"}})


def test_浏览器上传两样都给就报错_不认兜底() -> None:
    errors = _errors({"id": "u", "type": "browser_upload",
                      "config": {"session": "s", "asset_id": "{{t.text}}", "file_path": "/tmp/a.png"}})
    assert errors == ["节点 u 的 asset_id / file_path 只能填一个"]


def _config(graph: dict, node_id: str) -> dict:
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node["config"]
        for value in node["config"].values():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                try:
                    return _config(value, node_id)
                except KeyError:
                    pass
    raise KeyError(node_id)


def _strip_like_1_8_1(workflow_id: str) -> None:
    """1.8.1 的 migrate-browser-nodes-fill-one-target 落的那一版(那条已被取代,这里照它的做法和说明落一版)。"""
    from app.domain.workflows.revisions import commit_graph_revision

    order = {"browser_click": ("selector", "text"), "browser_wait": ("selector", "url_contains", "text")}

    def strip(graph: dict) -> dict:
        for node in graph["nodes"]:
            keys = order.get(node["type"])
            if keys:
                filled = [key for key in keys if node["config"].get(key) not in (None, "")]
                node["config"] = {key: value for key, value in node["config"].items() if key not in filled[1:]}
            body = node["config"].get("body")
            if isinstance(body, dict):
                strip(body)
        return graph

    with SessionLocal() as db:
        workflow = db.get(Workflow, workflow_id)
        commit_graph_revision(db, workflow, strip, source="migration", created_by=None, note=_BROWSER_ONE_TARGET_NOTE)
        db.commit()


def test_只填一样那次迁移删掉的兜底找回来_两格字面量的不补_重跑不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    body = {"nodes": [{"id": "inner", "type": "browser_click",
                       "config": {"session": "s", "selector": "{{loop.item}}", "text": "兜底"}}], "edges": []}
    graph = _graph(
        {"id": "ref", "type": "browser_click", "config": {"session": "s", "selector": "{{start.sel}}", "text": "去"}},
        {"id": "lit", "type": "browser_click", "config": {"session": "s", "selector": "#go", "text": "去"}},
        {"id": "w", "type": "browser_wait",
         "config": {"session": "s", "selector": "{{start.sel}}", "url_contains": "{{start.url}}", "text": "完成"}},
        {"id": "loop", "type": "loop_foreach", "config": {"items": "a", "body": body}},
    )
    workflow_id = client.post("/api/workflows", json={"workspace_id": ws, "name": "流程", "graph": graph}).json()["id"]

    _strip_like_1_8_1(workflow_id)  # 1.8.1 那次:多填的一律删掉,只留执行器先认的那一格
    with SessionLocal() as db:
        stripped = db.get(Workflow, workflow_id).graph
    assert "text" not in _config(stripped, "ref") and "text" not in _config(stripped, "inner")
    assert "text" not in _config(stripped, "w")

    _migrate_browser_fallback_targets_come_back()
    _migrate_browser_fallback_targets_come_back()

    with SessionLocal() as db:
        after = db.get(Workflow, workflow_id).graph
        revisions = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count()
    assert _config(after, "ref") == {"session": "s", "selector": "{{start.sel}}", "text": "去"}
    assert _config(after, "inner") == {"session": "s", "selector": "{{loop.item}}", "text": "兜底"}
    assert _config(after, "w") == {"session": "s", "selector": "{{start.sel}}", "url_contains": "{{start.url}}", "text": "完成"}
    assert _config(after, "lit") == {"session": "s", "selector": "#go"}, "两格都是字面量:执行器本来只认第一格,不补"
    assert revisions == 3
    assert not [one for one in validate_graph(after) if "只能填一个" in one]
