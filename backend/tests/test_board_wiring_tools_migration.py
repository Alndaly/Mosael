"""画板上跑流程 / 数据节点的工具格改成便签:`migrate-board-wiring-tools-become-notes`(ADR 0021 修订)。

画板上只放内容变换,调用工作流、HTTP 请求、文本模板、JSON 提取、文本处理、检索笔记不再是画板上的工具。
已经摆着的那几格改成一张便签:同一个 id(线都还连得上)、名字和位置照留、原来的设置附在正文后面;
它跑出来的产出一格不动。
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


def test_流程和数据工具格改成便签_线和产出都留着() -> None:
    from app.db.migrations import _migrate_board_wiring_tools_become_notes, migration_plan
    from app.domain.boards import normalize_canvas
    from tests.util import fresh_client

    assert "migrate-board-wiring-tools-become-notes" in {step.name for step in migration_plan().steps}

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟升级前落库的画布。
        board = Board(workspace_id=ws, name="旧板", revision=5, canvas={
            "items": [
                {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hello", "form": {"producer": "write"}},
                {"id": "t1", "kind": "action", "x": 300, "y": 0, "width": 280, "height": 150, "title": "大写一下",
                 "form": {"config": {"op": "upper"}, "bindings": {"text": [{"from": "n1"}]},
                          "producer": "node:text_transform"},
                 "run": {"status": "succeeded"}},
                {"id": "out", "kind": "note", "x": 700, "y": 0, "text": "HELLO", "form": {"producer": "write"}},
                {"id": "c1", "kind": "action", "x": 300, "y": 300,
                 "form": {"config": {}, "bindings": {}, "producer": "node:call_workflow"}},
                {"id": "h1", "kind": "action", "x": 300, "y": 600,
                 "form": {"config": {"url": "https://example.com/a", "method": "GET"}, "bindings": {},
                          "producer": "node:http_request"},
                 "run": {"status": "running", "job_id": "gone"}},
                #: 还合格的内容变换、插件工具:不动(插件工具合不合格随清单变,运行时说清楚)。
                {"id": "g1", "kind": "action", "x": 300, "y": 900,
                 "form": {"config": {"target_lang": "en"}, "bindings": {}, "producer": "node:translate"}},
                {"id": "p1", "kind": "action", "x": 300, "y": 1200,
                 "form": {"config": {}, "bindings": {}, "producer": "node:plugin.dev.mosael.baidu-pan.pan_list"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "t1"},
                {"id": "e2", "source": "t1", "target": "out"},
            ],
        })
        untouched = Board(workspace_id=ws, name="新板", revision=2, canvas={"items": [
            {"id": "g1", "kind": "action", "x": 0, "y": 0,
             "form": {"config": {}, "bindings": {}, "producer": "node:video_to_gif"}},
        ], "edges": []})
        db.add_all([board, untouched])
        db.commit()
        board_id, untouched_id = board.id, untouched.id
        before, _ = board.canvas, board.revision

    _migrate_board_wiring_tools_become_notes()
    once, revision = _canvas(board_id)
    _migrate_board_wiring_tools_become_notes()
    assert _canvas(board_id) == (once, revision), "再跑一次不该再动(版本号也不该再涨)"

    items = {item["id"]: item for item in once["items"]}
    #: 同一个 id、位置、大小、名字;产出者换成便签的写字;运行态不带过来。
    t1 = items["t1"]
    assert {key: t1[key] for key in ("kind", "x", "y", "width", "height", "title")} == {
        "kind": "note", "x": 300, "y": 0, "width": 280, "height": 150, "title": "大写一下"}
    assert t1["form"] == {"producer": "write"} and "run" not in t1
    assert "「文本处理」" in t1["text"] and "工作流" in t1["text"]
    assert '"op": "upper"' in t1["text"], "原来的设置附在正文后面,不丢"
    assert "原来的设置" not in items["c1"]["text"], "没有设置就不附"
    assert "「调用工作流」" in items["c1"]["text"]
    assert "https://example.com/a" in items["h1"]["text"] and "run" not in items["h1"]
    #: 还合格的、插件工具、别的格子一个字不动。
    for kept in ("n1", "out", "g1", "p1"):
        assert items[kept] == next(one for one in before["items"] if one["id"] == kept), kept
    #: 线都还在,两头都在画布上。
    assert once["edges"] == before["edges"]
    ids = set(items)
    assert all(edge["source"] in ids and edge["target"] in ids for edge in once["edges"])
    #: 升级那一刻还开着这张板的客户端要撞 409。
    assert revision == 6
    assert _canvas(untouched_id)[1] == 2, "没改到的板版本号不动"
    #: 迁完的画布照现在的规则存得下。
    normalize_canvas(once)
