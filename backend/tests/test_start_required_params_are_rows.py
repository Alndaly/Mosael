"""开始节点的「必填」跟着那一行参数走:`required_params` 是 params 里参数名的**列表**,不是一串逗号分隔的字。

## 现场

开始节点的面板上半是「启动参数」一行一对,下半是一个独立的「必填参数」文本框,里面手打 `account_link`。同一个名字
写两遍,打错了没有提示;参数改了名、删了行,必填那串字不跟着变 —— 改名之后那一格永远是空的,运行前一直被拦;
删掉的参数还在必填里,也一直被拦。

## 现在

- 形状:`required_params` 是名字的列表,每个名字都是 params 里的一个参数,按参数的顺序排。面板上每一行一个「必填」
  开关,改名、删行时跟着那一行走。
- 旧形状(逗号分隔的一串)由迁移改库里的图;导入旧文件、恢复旧修订走同一份图升级(graph_upgrade)。点名了却没有
  那一行的参数补成一行(默认空着)—— 它照旧是必填,运行前照旧拦,面板上看得见。
- 保存:名字去空白、去重,没有那一行的补一行,按参数顺序排。还写成一串字的(智能体照旧习惯写的)保存就拒,说清形状。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_start_required_params_are_a_list
from app.db.models import Workflow, WorkflowRevision
from app.domain.workflows import validate_graph
from app.domain.workflows.revisions import current_workflow_revision, graph_digest
from tests.util import fresh_client


def _graph(start_config: dict) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": start_config},
            {"id": "t", "type": "template", "config": {"template": "{{start.topic}}"}},
        ],
        "edges": [{"id": "e", "source": "start", "target": "t"}],
    }


def _client_and_workspace():
    client = fresh_client()
    return client, client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _start_config(graph: dict) -> dict:
    return next(node for node in graph["nodes"] if node["type"] == "start")["config"]


def _as_saved_by_an_older_version(workflow_id: str, graph: dict) -> None:
    """老版本存下的样子:当前图和最新那一版修订都是逗号分隔的那一串(那时的保存就是这么落的)。"""
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


def test_迁移把逗号分隔的一串改成参数名的列表_点名了却没有那一行的补一行_修订对上_重跑不动() -> None:
    client, workspace = _client_and_workspace()
    old_id = client.post("/api/workflows", json={"workspace_id": workspace, "name": "老的", "graph": _graph({})}).json()["id"]
    blank_id = client.post("/api/workflows", json={"workspace_id": workspace, "name": "空串", "graph": _graph({})}).json()["id"]
    new_id = client.post("/api/workflows", json={
        "workspace_id": workspace, "name": "新的",
        "graph": _graph({"params": {"topic": ""}, "required_params": ["topic"]}),
    }).json()["id"]
    #: 全角逗号、多余的空格、重复、params 里没有的名字 —— 手打的那一格里什么都有。
    _as_saved_by_an_older_version(old_id, _graph({
        "params": {"topic": "", "tone": "轻松"}, "required_params": " extra，topic, topic ,",
    }))
    _as_saved_by_an_older_version(blank_id, _graph({"params": {"topic": "猫"}, "required_params": ""}))
    untouched = _stored(new_id)

    _migrate_start_required_params_are_a_list()

    migrated = _start_config(_stored(old_id))
    assert migrated["params"] == {"topic": "", "tone": "轻松", "extra": ""}, "点名了却没有那一行的,补一行(默认空着)"
    assert migrated["required_params"] == ["topic", "extra"], "按参数的顺序"
    assert _start_config(_stored(blank_id))["required_params"] == []
    assert _stored(new_id) == untouched, "已经是列表的不动"

    with SessionLocal() as db:
        workflow = db.get(Workflow, old_id)
        assert current_workflow_revision(db, workflow).graph == _stored(old_id)
        assert current_workflow_revision(db, workflow).source == "migration"
        revisions = db.query(WorkflowRevision).filter_by(workflow_id=old_id).count()

    _migrate_start_required_params_are_a_list()
    with SessionLocal() as db:
        assert db.query(WorkflowRevision).filter_by(workflow_id=old_id).count() == revisions, "重跑不再落新的一版"
    #: 补出来的那一行照旧是必填:运行前照旧拦,说清是哪一个。
    refused = client.post(f"/api/workflows/{old_id}/run", json={"params": {"topic": "猫"}})
    assert refused.status_code == 422 and refused.json()["detail"] == "「开始」缺少必填:extra", refused.text


def test_导入老版本导出的文件_必填改成列表() -> None:
    client, workspace = _client_and_workspace()
    envelope = {"format": "mosael-workflow", "version": 1, "name": "老文件",
                "graph": _graph({"params": {"topic": ""}, "required_params": "topic, tag"})}
    imported = client.post("/api/workflows/import", json={"workspace_id": workspace, "data": envelope})
    assert imported.status_code == 200, imported.text
    config = _start_config(imported.json()["graph"])
    assert config["required_params"] == ["topic", "tag"] and config["params"] == {"topic": "", "tag": ""}


def test_恢复到升级之前的那一版_必填照样是列表() -> None:
    client, workspace = _client_and_workspace()
    workflow = client.post("/api/workflows", json={"workspace_id": workspace, "name": "W", "graph": _graph({})}).json()
    _as_saved_by_an_older_version(workflow["id"], _graph({"params": {"topic": ""}, "required_params": "topic"}))
    _migrate_start_required_params_are_a_list()
    #: 历史修订里第一版还是一串字(迁移改不到历史修订)。
    restored = client.post(f"/api/workflows/{workflow['id']}/revisions/1/restore")
    assert restored.status_code == 200, restored.text
    assert _start_config(restored.json()["graph"])["required_params"] == ["topic"]


def test_保存时只留存在的参数名_没有那一行的补一行_去重_按参数顺序() -> None:
    client, workspace = _client_and_workspace()
    saved = client.post("/api/workflows", json={
        "workspace_id": workspace, "name": "W",
        "graph": _graph({"params": {"topic": "", "tone": ""}, "required_params": ["tone", " topic ", "tone", "", "extra"]}),
    })
    assert saved.status_code == 200, saved.text
    config = _start_config(saved.json()["graph"])
    assert config["required_params"] == ["topic", "tone", "extra"]
    assert config["params"] == {"topic": "", "tone": "", "extra": ""}


def test_还写成一串字的_保存就拒_说清形状() -> None:
    """不认旧写法(那是迁移和图升级的事):智能体照旧习惯写一串字时,当场说清要的是列表。"""
    client, workspace = _client_and_workspace()
    refused = client.post("/api/workflows", json={
        "workspace_id": workspace, "name": "W", "graph": _graph({"params": {"topic": ""}, "required_params": "topic"}),
    })
    assert refused.status_code == 422, refused.text
    assert "required_params" in refused.text and "列表" in refused.text
    english = client.post("/api/workflows", headers={"Accept-Language": "en"}, json={
        "workspace_id": workspace, "name": "W", "graph": _graph({"params": {"topic": ""}, "required_params": "topic"}),
    })
    assert english.status_code == 422 and "list" in english.text, english.text


def test_运行前按列表查_空着拦_这一次带了值就过() -> None:
    graph = _graph({"params": {"topic": "", "count": 0}, "required_params": ["topic", "count"]})
    assert validate_graph(graph) == ["「开始」缺少必填:topic"], "0 是值,不是空"
    client, workspace = _client_and_workspace()
    workflow = client.post("/api/workflows", json={"workspace_id": workspace, "name": "W", "graph": graph}).json()
    blank = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}})
    assert blank.status_code == 422 and blank.json()["detail"] == "「开始」缺少必填:topic", blank.text
    given = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {"topic": "猫"}})
    assert given.status_code == 200, given.text


def test_节点声明_每一行自带必填_必填清单由参数那一格的控件编辑() -> None:
    """面板上没有单独的「必填参数」文本框:参数那一格用开始节点专用的控件(名字 / 默认值 / 必填),它同时写
    `required_params`。这两格的关系写在声明里 —— 表单不认识开始节点。"""
    client = fresh_client()
    start = {one["type"]: one for one in client.get("/api/workflows/node-types").json()}["start"]["config"]
    assert start["params"]["editor"] == "start_params"
    assert start["params"]["required_list"] == "required_params"
    assert start["required_params"]["type"] == "list"
    assert start["required_params"]["edited_by"] == "params"
