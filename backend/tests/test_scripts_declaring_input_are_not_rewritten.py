"""自己声明了 `input` 的「执行脚本」,代码字段的改写不碰它;1.8.1 已经改了的改回原文,修订说明里点名。

## 现场

「执行脚本」包在 `with ({input: …}) { 脚本 }` 里跑。脚本自己写了 `const input = …`(或叫 input 的参数)时,
它盖住交进来的那个 —— 改写成 `input.k` 读到的是脚本自己的变量,静默取空,而且看不出来。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import (
    _CODE_FIELDS_NOTE,
    _migrate_code_fields_read_references_from_input,
    _migrate_scripts_declaring_input_go_back,
)
from app.db.models import User, Workflow, WorkflowRevision
from app.domain.workflows.graph_upgrade import upgrade_graph
from app.domain.workflows.revisions import commit_graph_revision, current_workflow_revision
from tests.util import fresh_client

OWN_INPUT = "const input = document.querySelector('#q'); input.value + '{{t.text}}'"


def _graph(expression: str, extra: dict | None = None) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "t", "type": "template", "config": {"template": "后缀"}},
            {"id": "js", "type": "browser_evaluate", "config": {"session": "s", "expression": expression, **(extra or {})}},
            {"id": "plain", "type": "browser_evaluate", "config": {"session": "s", "expression": "'{{t.text}}'"}},
        ],
        "edges": [],
    }


def _js(graph: dict, node_id: str = "js") -> dict:
    return next(node for node in graph["nodes"] if node["id"] == node_id)["config"]


def test_图升级不改自己声明了input的脚本_别的照改() -> None:
    upgraded = upgrade_graph(_graph(OWN_INPUT))
    assert _js(upgraded) == {"session": "s", "expression": OWN_INPUT}
    assert _js(upgraded, "plain")["input"] == {"t_text": "{{t.text}}"}


def test_代码字段迁移跳过这种脚本_修订说明里点名() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow_id = client.post("/api/workflows", json={"workspace_id": ws, "name": "脚本", "graph": _graph(OWN_INPUT)}).json()["id"]

    _migrate_code_fields_read_references_from_input()

    with SessionLocal() as db:
        revision = current_workflow_revision(db, db.get(Workflow, workflow_id))
    assert _js(revision.graph)["expression"] == OWN_INPUT
    assert revision.note.startswith(_CODE_FIELDS_NOTE) and revision.note.endswith("js")


def test_1_8_1已经改了的改回原文_点名_人后来改过的不动_重跑不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    ids = [client.post("/api/workflows", json={"workspace_id": ws, "name": name, "graph": _graph(OWN_INPUT)}).json()["id"]
           for name in ("没动过", "后来改过")]
    #: 1.8.1 那次改写的产出:脚本读 input.t_text —— 读到的是脚本自己的 input。
    migrated = _graph("const input = document.querySelector('#q'); input.value + '' + String(input.t_text) + ''",
                      {"input": {"t_text": "{{t.text}}"}})
    with SessionLocal() as db:
        author = db.query(User).filter(User.username == "tester").one().id
        for workflow_id in ids:
            commit_graph_revision(db, db.get(Workflow, workflow_id), lambda _graph: migrated,
                                  source="migration", created_by=author, note=_CODE_FIELDS_NOTE)
        edited = _graph("input.value", {"input": {"t_text": "{{t.text}}"}})
        commit_graph_revision(db, db.get(Workflow, ids[1]), lambda _graph: edited, source="edit", created_by=author)
        db.commit()

    _migrate_scripts_declaring_input_go_back()
    _migrate_scripts_declaring_input_go_back()

    with SessionLocal() as db:
        back = current_workflow_revision(db, db.get(Workflow, ids[0]))
        assert _js(back.graph) == {"session": "s", "expression": OWN_INPUT}
        assert back.revision == 3 and back.created_by == author and back.note.endswith("js")
        assert db.query(WorkflowRevision).filter_by(workflow_id=ids[0]).count() == 3
        assert _js(db.get(Workflow, ids[1]).graph)["expression"] == "input.value"
