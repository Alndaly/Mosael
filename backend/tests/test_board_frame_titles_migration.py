"""分组框的名字从 `text` 搬到 `title`:`migrate-board-frame-names-become-titles`。

此前只有分组框能起名,名字借住在 `text` 里;现在每一格都能起名,统一放在 `title`。
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.db.models import Board


def _canvas(board_id: str) -> dict:
    with SessionLocal() as db:
        canvas = db.get(Board, board_id).canvas
    return json.loads(canvas) if isinstance(canvas, str) else canvas


def test_分组框的名字搬进_title_别的格子的正文不动() -> None:
    from app.db.migrations import _migrate_board_frame_names_become_titles, migration_plan
    from app.domain.boards import normalize_canvas
    from tests.util import fresh_client

    assert "migrate-board-frame-names-become-titles" in {step.name for step in migration_plan().steps}

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟改之前落库的画布(分组框的名字在 text 里)。
        board = Board(workspace_id=ws, name="旧板", canvas={
            "items": [
                {"id": "F1", "kind": "frame", "x": 0, "y": 0, "text": "  第一幕\n开场  "},
                {"id": "F2", "kind": "frame", "x": 500, "y": 0, "text": "   "},
                {"id": "F3", "kind": "frame", "x": 900, "y": 0, "text": "长" * 300},
                {"id": "F4", "kind": "frame", "x": 1300, "y": 0},
                {"id": "N", "kind": "note", "x": 0, "y": 400, "text": "便签正文留在 text"},
            ],
            "edges": [],
        })
        db.add(board)
        db.commit()
        board_id = board.id

    _migrate_board_frame_names_become_titles()
    once = _canvas(board_id)
    _migrate_board_frame_names_become_titles()
    assert _canvas(board_id) == once, "再跑一次不该再动"

    items = {item["id"]: item for item in once["items"]}
    assert items["F1"]["title"] == "第一幕 开场"
    assert "title" not in items["F2"], "只有空白的名字就是没起名"
    assert items["F3"]["title"] == "长" * 120, "超长的截到上限,否则这张板下一次保存会被整个拒掉"
    assert "title" not in items["F4"]
    assert all("text" not in items[one] for one in ("F1", "F2", "F3", "F4")), "分组框身上不再留 text"
    assert items["N"] == {"id": "N", "kind": "note", "x": 0, "y": 400, "text": "便签正文留在 text"}
    #: 搬完的画布照现在的规则存得下。
    normalize_canvas(once)
