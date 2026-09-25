"""槽位里顺着连线挂上的素材记下出处:`_migrate_board_sources_record_their_upstream`。

「哪一份是从上游来的」此前只活在前端的一份底账里,服务端不知道 —— 智能体删掉上游那一格,
下游表单里那份引用原样留着。现在出处(`from`)记在那一份自己身上,服务端一处判定。
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.db.models import Board


def _canvas(board_id: str) -> dict:
    with SessionLocal() as db:
        canvas = db.get(Board, board_id).canvas
    return json.loads(canvas) if isinstance(canvas, str) else canvas


def test_顺着线挂上的那几份迁移后记着从哪一格来() -> None:
    from app.db.migrations import _migrate_board_sources_record_their_upstream
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟改之前落库的画布(槽位里没有 from)。
        board = Board(workspace_id=ws, name="旧板", canvas={
            "items": [
                {"id": "A", "kind": "image", "x": 0, "y": 0, "asset_id": "a1"},
                {"id": "S", "kind": "scene", "x": 0, "y": 300, "scene_id": "sc", "asset_id": "frame"},
                {"id": "N", "kind": "note", "x": 0, "y": 600, "text": "一只猫"},
                {"id": "V", "kind": "video", "x": 400, "y": 0, "form": {"prompt": "动起来", "source_assets": [
                    {"asset_id": "a1", "role": "first_frame"},
                    {"asset_id": "frame", "role": "reference_image"},
                    {"asset_id": "m1", "role": "last_frame"},
                ]}},
                #: 同一份素材,可这一格和 A 之间没有线 —— 是手动挂的。
                {"id": "W", "kind": "video", "x": 400, "y": 300, "form": {"source_assets": [
                    {"asset_id": "a1", "role": "first_frame"},
                ]}},
            ],
            "edges": [
                {"id": "e1", "source": "A", "target": "V"},
                {"id": "e2", "source": "S", "target": "V"},
                {"id": "e3", "source": "N", "target": "V"},
            ],
        })
        db.add(board)
        db.commit()
        board_id = board.id

    _migrate_board_sources_record_their_upstream()
    once = _canvas(board_id)
    _migrate_board_sources_record_their_upstream()
    assert _canvas(board_id) == once, "再跑一次不该再动"

    items = {item["id"]: item for item in once["items"]}
    assert items["V"]["form"]["source_assets"] == [
        {"asset_id": "a1", "role": "first_frame", "from": "A"},
        {"asset_id": "frame", "role": "reference_image", "from": "S"},
        {"asset_id": "m1", "role": "last_frame"},
    ]
    assert items["W"]["form"]["source_assets"] == [{"asset_id": "a1", "role": "first_frame"}]
