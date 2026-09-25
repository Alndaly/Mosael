"""截出来的那一格记下「截的是哪一份、哪一段」:`_migrate_board_trim_slots_record_their_source`。

此前截取只记了 `form.parameters = {start, end, mute}`。截挂了的那一格和一格生成挂了的视频长得
一样 —— 选中它挂的是生成面板,重截也不知道截的是哪一份。迁移按截取任务的 payload 认来历。
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.db.models import Board, Job


def _canvas(board_id: str) -> dict:
    with SessionLocal() as db:
        canvas = db.get(Board, board_id).canvas
    return json.loads(canvas) if isinstance(canvas, str) else canvas


def test_截挂了的那一格迁移后记着截的是哪一份() -> None:
    from app.db.migrations import _migrate_board_trim_slots_record_their_source
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    old_trim = {"parameters": {"start": 1.5, "end": 4, "mute": True}}
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟改之前落库的画布。
        board = Board(workspace_id=ws, name="旧板", canvas={
            "items": [
                {"id": "cut", "kind": "video", "x": 0, "y": 0, "form": old_trim,
                 "run": {"status": "failed", "error": "截取失败"}},
                {"id": "done", "kind": "audio", "x": 0, "y": 300, "asset_id": "made",
                 "form": {"parameters": {"start": 0, "end": 2, "mute": False}, "prompt": ""},
                 "run": {"status": "succeeded"}},
                #: 生成出来的那一格,参数长得再像也不是截取 —— 没有截取任务指着它。
                {"id": "gen", "kind": "video", "x": 400, "y": 0,
                 "form": {"prompt": "海边", "parameters": {"start": 0, "end": 5, "fps": 24}}},
            ],
            "edges": [],
        })
        db.add(board)
        db.flush()
        for item_id, source in (("cut", "src-video"), ("done", "src-audio")):
            db.add(Job(workspace_id=ws, kind="trim", created_by=None, status="failed", payload={
                "asset_id": source, "subject": "片子",
                "receipt": {"kind": "board_item", "board_id": board.id, "item_id": item_id},
            }))
        db.commit()
        board_id = board.id

    _migrate_board_trim_slots_record_their_source()
    once = _canvas(board_id)
    _migrate_board_trim_slots_record_their_source()
    assert _canvas(board_id) == once, "再跑一次不该再动"

    items = {item["id"]: item for item in once["items"]}
    assert items["cut"]["form"] == {"trim": {"asset_id": "src-video", "start": 1.5, "end": 4.0, "mute": True}}
    assert items["done"]["form"] == {"prompt": "", "trim": {"asset_id": "src-audio", "start": 0.0, "end": 2.0, "mute": False}}
    assert items["gen"]["form"] == {"prompt": "海边", "parameters": {"start": 0, "end": 5, "fps": 24}}

    #: 迁完的画布过得了当前的校验(存得下、读得回)。
    revision = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["revision"]
    saved = client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "base_revision": revision, "canvas": once})
    assert saved.status_code == 200, saved.text
