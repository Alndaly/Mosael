"""三个浏览器节点的是非选项从「否 / 是」迁成「false / true」的那一次迁移。

选项**值**会原样存进图里,也会原样显示在下拉框上 —— 那是值不是文案,没有任何出口能翻掉它。
目录里其余选项一律是中性标识符,所以改的是值本身;库里已有的图在迁移里跟上,而不是让读取端
认两套写法。

这类迁移只在"老库第一次跑新版本"时发生一次,肉眼几乎不可能复验:漏掉的图会一直带着「是」,
而下拉框里已经没有这个选项了 —— 界面显示成空,用户一存就把它改成了别的意思。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_browser_boolean_options
from tests.util import fresh_client

GRAPH = {
    "nodes": [
        {"id": "n1", "type": "browser_click", "config": {"selector": "#ok", "exact": "是"}},
        {"id": "n2", "type": "browser_extract", "config": {"selector": "li", "all": "否"}},
        {"id": "n3", "type": "browser_wait", "config": {"gone": "是"}},
        # 自由文本里的「是」是内容,不是选项 —— 一个字都不该动。
        {"id": "n4", "type": "llm", "config": {"prompt": "是", "exact": "是"}},
        # 子图里的节点同样要迁到。
        {"id": "n5", "type": "loop", "config": {"body": {"nodes": [
            {"id": "n5a", "type": "browser_click", "config": {"exact": "否"}},
        ]}}},
    ],
    "edges": [],
}


def _stored() -> dict:
    with engine.begin() as conn:
        return json.loads(conn.execute(text("SELECT graph FROM workflows WHERE id = 'wf-1'")).scalar_one())


def _seed(graph: dict) -> None:
    """直接写库,不走接口 —— 接口会拒绝这些旧值,而库里正是这样存着的。"""
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflows (id, workspace_id, name, description, graph, created_at, updated_at) "
                "VALUES ('wf-1',:ws,'旧图','', :g, :now, :now)"
            ),
            {"ws": workspace_id, "g": json.dumps(graph, ensure_ascii=False), "now": "2026-01-01 00:00:00"},
        )


def test_三个浏览器节点的是非值迁成_true_false() -> None:
    _seed(GRAPH)

    _migrate_browser_boolean_options()

    nodes = {node["id"]: node for node in _stored()["nodes"]}
    assert nodes["n1"]["config"]["exact"] == "true"
    assert nodes["n2"]["config"]["all"] == "false"
    assert nodes["n3"]["config"]["gone"] == "true"
    body = nodes["n5"]["config"]["body"]["nodes"][0]
    assert body["config"]["exact"] == "false", "子图里的节点漏掉了"


def test_别的字段一个字都不动() -> None:
    """「是」在提示词里是内容。按(节点类型, 字段名)对里迁,不是见到「是」就改。"""
    _seed(GRAPH)

    _migrate_browser_boolean_options()

    nodes = {node["id"]: node for node in _stored()["nodes"]}
    assert nodes["n4"]["config"]["prompt"] == "是"
    assert nodes["n4"]["config"]["exact"] == "是", "llm 节点上碰巧同名的字段不该被改"
    assert nodes["n1"]["config"]["selector"] == "#ok"


def test_跑第二次什么都不改() -> None:
    _seed(GRAPH)

    _migrate_browser_boolean_options()
    once = _stored()
    _migrate_browser_boolean_options()

    assert _stored() == once


def test_目录里已经没有中文选项值() -> None:
    """迁移只管存量。**目录本身**再写回中文的话,新图立刻又长出旧值。"""
    from app.domain.workflows import NODE_TYPES

    for key, meta in NODE_TYPES.items():
        for field, spec in (meta.get("config") or {}).items():
            for option in spec.get("options") or []:
                assert option.isascii(), f"{key}.{field} 的选项值 {option!r} 不是中性标识符"
