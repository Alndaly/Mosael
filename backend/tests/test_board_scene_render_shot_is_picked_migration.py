"""「渲染白模参考」的镜头和项目改成挑,存着的便签绑定摘掉:`migrate-board-scene-render-shot-is-picked`。

这两格此前能接便签 / 文档(必填的镜头还会默认接第一张便签);现在是从清单里挑的,不再接写字的格子。
摘掉绑定;镜头绑的是便签、又没手填过的,把便签上的字填进表单 —— 上次运行取到的就是它。
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.db.models import Board


def _canvas(board_id: str) -> tuple[dict, int]:
    with SessionLocal() as db:
        board = db.get(Board, board_id)
        canvas = board.canvas
        return (json.loads(canvas) if isinstance(canvas, str) else canvas), board.revision


def _render(item_id: str, config: dict, bindings: dict) -> dict:
    return {"id": item_id, "kind": "action", "x": 400, "y": 0,
            "form": {"config": config, "bindings": bindings, "producer": "node:scene_render"}}


def test_镜头和项目的写字绑定摘掉_便签上的镜头搬进表单() -> None:
    from app.db.migrations import _migrate_board_scene_render_shot_is_picked, migration_plan
    from app.domain.boards import normalize_canvas
    from tests.util import fresh_client

    assert "migrate-board-scene-render-shot-is-picked" in {step.name for step in migration_plan().steps}

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟升级前落库的画布。
        board = Board(workspace_id=ws, name="旧板", revision=3, canvas={
            "items": [
                {"id": "scene", "kind": "scene", "x": 0, "y": 0, "scene_id": "s1"},
                {"id": "n1", "kind": "note", "x": 0, "y": 200, "text": "  shot-2 \n", "form": {"producer": "write"}},
                {"id": "doc", "kind": "document", "x": 0, "y": 400, "note_id": "note-1", "note_revision": 1},
                #: 默认绑定把镜头接到了便签上:摘掉,便签上的字搬进表单。
                _render("r1", {"render": "both"}, {"scene_id": [{"from": "scene"}], "shot_id": [{"from": "n1"}]}),
                #: 手填过镜头的不覆盖;项目接的文档一并摘掉。
                _render("r2", {"shot_id": "shot-1"}, {"shot_id": [{"from": "n1"}], "project_id": [{"from": "doc"}]}),
                #: 接的是文档:正文当不了镜头 id,只摘不搬。
                _render("r3", {}, {"shot_id": [{"from": "doc"}]}),
                #: 没有这两格绑定的、别的工具格:一个字不动。
                _render("r4", {"shot_id": "shot-3"}, {"scene_id": [{"from": "scene"}]}),
                {"id": "t1", "kind": "action", "x": 400, "y": 800,
                 "form": {"config": {}, "bindings": {"text": [{"from": "n1"}]}, "producer": "node:translate"}},
            ],
            "edges": [
                {"id": f"e-{source}-{target}", "source": source, "target": target}
                for target in ("r1", "r2", "r3", "r4") for source in ("scene", "n1", "doc")
            ] + [{"id": "e-n1-t1", "source": "n1", "target": "t1"}],
        })
        untouched = Board(workspace_id=ws, name="新板", revision=2, canvas={"items": [
            _render("r1", {}, {"scene_id": [{"from": "scene"}]}),
            {"id": "scene", "kind": "scene", "x": 0, "y": 0, "scene_id": "s1"},
        ], "edges": [{"id": "e", "source": "scene", "target": "r1"}]})
        db.add_all([board, untouched])
        db.commit()
        board_id, untouched_id = board.id, untouched.id
        before = board.canvas

    _migrate_board_scene_render_shot_is_picked()
    once, revision = _canvas(board_id)
    _migrate_board_scene_render_shot_is_picked()
    assert _canvas(board_id) == (once, revision), "再跑一次不该再动(版本号也不该再涨)"

    forms = {item["id"]: item.get("form") for item in once["items"]}
    assert forms["r1"] == {"config": {"render": "both", "shot_id": "shot-2"},
                           "bindings": {"scene_id": [{"from": "scene"}]}, "producer": "node:scene_render"}
    assert forms["r2"]["config"] == {"shot_id": "shot-1"} and forms["r2"]["bindings"] == {}
    assert forms["r3"]["config"] == {} and forms["r3"]["bindings"] == {}
    for kept in ("r4", "t1", "n1", "doc", "scene"):
        assert next(one for one in once["items"] if one["id"] == kept) == next(
            one for one in before["items"] if one["id"] == kept), kept
    assert once["edges"] == before["edges"], "线一根不动"
    #: 升级那一刻还开着这张板的客户端要撞 409。
    assert revision == 4
    assert _canvas(untouched_id)[1] == 2, "没改到的板版本号不动"
    #: 迁完的画布照现在的规则存得下。
    normalize_canvas(once)
