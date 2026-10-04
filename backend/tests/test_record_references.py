"""引用表(record_references):JSON 里点名的别的记录,派生成一张有索引的表(见 db/references)。

- 抽取规则各来源一条,纯函数;
- flush 时跟着写(新建、改 JSON、删除),绕过 flush 的比较并交换写就地 resync —— 棘轮在最后;
- 启动时按抽取规则的版本号整张重建(迁移计划里的对账步骤 reindex-record-references),老库里读坏的 JSON 不拦启动。
"""

from __future__ import annotations

# 这条测试里有一道**棘轮**(最后一条):它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import pathlib

from sqlalchemy import delete, select, text

from app.core.db import SessionLocal, engine
from app.db import references
from app.db.models import Board, RecordReference, RecordReferenceIndex
from tests.util import fresh_client

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _refs(source_kind: str, source_id: str) -> set[tuple[str, str, str]]:
    with SessionLocal() as db:
        rows = db.execute(
            select(RecordReference.target_kind, RecordReference.target_id, RecordReference.how).where(
                RecordReference.source_kind == source_kind, RecordReference.source_id == source_id
            )
        )
        return {tuple(row) for row in rows}


def _recomputed() -> set[tuple[str, ...]]:
    """按当前 JSON 从头算一遍。和表里的对不上,就是哪条写路径没维护它。"""
    out: set[tuple[str, ...]] = set()
    with SessionLocal() as db:
        for source in references.SOURCES:
            for row in db.scalars(select(source.model())):
                out |= {(source.kind, row.id, *ref) for ref in references.refs_of(source, row)}
    return out


def _stored() -> set[tuple[str, ...]]:
    with SessionLocal() as db:
        rows = db.execute(select(RecordReference.source_kind, RecordReference.source_id, RecordReference.target_kind,
                                 RecordReference.target_id, RecordReference.how))
        return {tuple(row) for row in rows}


# ---------------- 抽取规则 ----------------


def test_画布_格子是_cell_提示词里_at_的是_mention() -> None:
    canvas = {"items": [
        {"id": "a", "kind": "image", "asset_id": "asset1"},
        {"id": "b", "kind": "entity", "entity_id": "ent1"},
        {"id": "c", "kind": "text", "form": {"mentioned_entity_ids": ["ent2", "ent2"]}},
        {"id": "d", "kind": "scene", "scene_id": "scene1"},
        {"id": "e", "kind": "sequence", "sequence_id": "{{上游}}"},
        {"id": "f", "kind": "note", "source_note": {"note_id": "note1", "revision": 2, "title": "周报"}},
    ]}
    assert set(references.board_refs(canvas)) == {
        ("asset", "asset1", "cell"), ("entity", "ent1", "cell"), ("entity", "ent2", "mention"), ("scene", "scene1", "cell"),
        ("note", "note1", "source"),
    }
    assert set(references.board_refs(None)) == set()
    assert set(references.board_refs({"items": "坏的"})) == set()


def test_工作流节点_多值字段按同一条规矩拆_模板插值不算引用() -> None:
    graph = {"nodes": [
        {"id": "n1", "config": {"entity_ids": "e1, e2\ne3", "asset_id": "a1"}},
        {"id": "n2", "config": {"workflow_id": "w1", "asset_ids": ["a2", "{{input.asset}}"]}},
        {"id": "n3"},
    ]}
    assert set(references.workflow_refs(graph)) == {
        ("entity", "e1", "node"), ("entity", "e2", "node"), ("entity", "e3", "node"),
        ("asset", "a1", "node"), ("asset", "a2", "node"), ("workflow", "w1", "node"),
    }


def test_生成请求_场景_定时任务() -> None:
    assert set(references.generation_refs({"entities": [{"id": "e1"}, {"name": "没有 id"}]})) == {("entity", "e1", "")}
    assert set(references.scene_refs({"objects": [{"model_id": "m1"}, {"kind": "camera"}]})) == {("scene_model", "m1", "")}
    assert set(references.scheduled_task_refs("workflow", {"workflow_id": "w1"})) == {("workflow", "w1", "")}
    assert set(references.scheduled_task_refs("publish", {"workflow_id": "w1"})) == set()


# ---------------- 维护 ----------------


def _board_with_scene(client, ws: str) -> tuple[str, str]:
    scene = client.post("/api/scenes", json={"workspace_id": ws, "name": "主场景"}).json()
    board = client.post("/api/boards", json={"workspace_id": ws, "name": "分镜板"}).json()
    saved = client.patch(f"/api/boards/{board['id']}", json={
        "workspace_id": ws, "base_revision": board.get("revision", 0),
        "canvas": {"items": [{"id": "i1", "kind": "scene", "scene_id": scene["id"], "x": 0, "y": 0, "width": 320, "height": 180}]},
    })
    assert saved.status_code == 200, saved.text
    return scene["id"], board["id"]


def test_存画板时跟着写_改了跟着改_删了跟着删() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    scene_id, board_id = _board_with_scene(client, ws)
    assert _refs("board", board_id) == {("scene", scene_id, "cell")}

    board = client.get(f"/api/boards/{board_id}?workspace_id={ws}").json()
    cleared = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": board["revision"], "canvas": {"items": []},
    })
    assert cleared.status_code == 200, cleared.text
    assert _refs("board", board_id) == set()

    _board_with_scene(client, ws)
    assert _stored() == _recomputed()
    with SessionLocal() as db:
        for board in db.scalars(select(Board).where(Board.workspace_id == ws)):
            db.delete(board)
        db.commit()
    assert not {row for row in _stored() if row[0] == "board"}


def test_定时任务点名的工作流进表() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    flow = client.post("/api/workflows", json={"workspace_id": ws, "name": "流"}).json()
    task = client.post("/api/scheduled-tasks", json={
        "workspace_id": ws, "name": "每天", "kind": "workflow", "trigger_type": "manual",
        "payload": {"workflow_id": flow["id"]},
    })
    assert task.status_code == 200, task.text
    assert _refs("scheduled_task", task.json()["id"]) == {("workflow", flow["id"], "")}
    assert _stored() == _recomputed()


# ---------------- 重建 ----------------


def test_版本号对得上什么都不做_对不上整张重建_读坏的_JSON_不拦启动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    scene_id, board_id = _board_with_scene(client, ws)
    with engine.begin() as conn:
        assert references.reindex(conn) is False
        # 迁移的原生 SQL 不经过 flush:表里没了,版本号也作废 —— 下一次启动整张补回来。
        conn.execute(delete(RecordReference))
        conn.execute(delete(RecordReferenceIndex))
        conn.execute(text("UPDATE workflows SET graph = '' WHERE workspace_id = :ws"), {"ws": ws})
    client.post("/api/workflows", json={"workspace_id": ws, "name": "另一个"})
    with engine.begin() as conn:
        conn.execute(text("UPDATE workflows SET graph = '半截{' WHERE workspace_id = :ws"), {"ws": ws})
        assert references.reindex(conn) is True
        assert references.reindex(conn) is False
    assert _refs("board", board_id) == {("scene", scene_id, "cell")}


def test_启动时的对账步骤就是它() -> None:
    from app.db.migrations import migration_plan

    step = next(step for step in migration_plan().steps if step.name == "reindex-record-references")
    assert step.once is False


# ---------------- 棘轮 ----------------


def _watched() -> dict[str, set[str]]:
    return {source.model().__name__: set(source.columns) for source in references.SOURCES}


def test_绕过_flush_改来源_JSON_的写必须就地_resync() -> None:
    """`update(Board).values(canvas=…)` 这类比较并交换的写不经过 ORM 的脏检查,after_flush 看不见它。
    漏一处,那条路径存下的引用就一直是旧的 ——「谁还在用它」答错,而且不报任何错。"""
    watched = _watched()
    missing: list[str] = []
    for path in sorted((BACKEND / "app/domain").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            writes = False
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "update"):
                    continue
                model = node.args[0].id if node.args and isinstance(node.args[0], ast.Name) else None
                if model not in watched:
                    continue
                for outer in ast.walk(fn):
                    if (isinstance(outer, ast.Call) and isinstance(outer.func, ast.Attribute) and outer.func.attr == "values"
                            and {k.arg for k in outer.keywords} & watched[model]):
                        writes = True
            resyncs = any(
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "resync"
                for node in ast.walk(fn)
            )
            if writes and not resyncs:
                missing.append(f"{path.relative_to(BACKEND)}:{fn.name}")
    assert not missing, "这些写绕过 flush 改了来源的 JSON,却没有 references.resync:\n  " + "\n  ".join(missing)


def test_这道棘轮扫得到东西() -> None:
    """扫描写错了会让上面那条永远绿:至少画板、场景、工作流那三处比较并交换的写要被它看见。"""
    seen = 0
    watched = _watched()
    for path in sorted((BACKEND / "app/domain").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "update"
                    and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in watched):
                seen += 1
    assert seen >= 3
