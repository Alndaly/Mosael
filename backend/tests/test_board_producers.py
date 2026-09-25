"""画板上的产出者注册表(ADR 0021)。

画板上能产出东西的动作只有一个入口 —— `boards.producers.run`,路由只有一条 `POST /api/boards/{id}/run`。
这里钉住注册表本身:有哪几个、各自挂在哪、未知的怎么拒、表单上写明的产出者从哪来(新跑的一格、
智能体放下的一格、升级前的老画板)。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.util import board_revision, fresh_client, run_on_board


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _board(client, ws: str, items: list[dict]) -> str:
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": items, "edges": []}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_注册表里是四个内置产出者_各自挂在该挂的格子上() -> None:
    from app.domain.boards import producers
    from app.domain.boards.producer_ids import BUILTIN_PRODUCER_IDS
    from app.domain.generation.resolution import KINDS

    by_id = {one.id: one for one in producers.list_producers()}
    assert set(by_id) == {"generate", "speak", "trim", "write"}
    #: canvas 校验表单时认的那张名字表,和注册表是同一份。
    assert set(BUILTIN_PRODUCER_IDS) == set(by_id)

    #: 生成挂在哪由生成目录说了算,不在画板这边另写一份。
    assert by_id["generate"].hosts == tuple(KINDS)
    assert by_id["write"].hosts == ("note",)
    assert by_id["speak"].hosts == ("audio",)
    assert set(by_id["trim"].hosts) == {"video", "audio"}

    assert {one: by_id[one].permission for one in by_id} == {
        "generate": "edit", "speak": "edit", "trim": "edit", "write": "ai",
    }
    #: 智能体替人跑时要不要确认卡看这个:只有本机截取既不花钱也不出门。
    assert {one for one in by_id if by_id[one].effects == "none"} == {"trim"}
    assert all(one.effects in ("none", "paid", "external") for one in by_id.values())


def test_每个产出者的表单都不收非有限的数() -> None:
    """表单在领域里校验,不经过接口层的 ApiModel —— 同一条规矩要在这里再钉一次。"""
    from app.domain.boards import producers

    leaky = [one.id for one in producers.list_producers() if one.form.model_config.get("allow_inf_nan") is not False]
    assert not leaky, f"这些产出者的表单放进了 NaN / Infinity:{leaky}"


def test_新放下的一格挂哪个产出者() -> None:
    from app.domain.boards.producers import producer_for_new_slot

    assert [producer_for_new_slot(kind) for kind in ("note", "image", "video", "audio")] == [
        "write", "generate", "generate", "speak",
    ]
    assert [producer_for_new_slot(kind) for kind in ("frame", "scene", "document")] == [None, None, None]


def test_未知的产出者和挂错地方的产出者都拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, [{"id": "n1", "kind": "note", "x": 0, "y": 0}])

    unknown = run_on_board(client, board_id, ws, producer="paint", item_id="n1", kind="note", form={})
    assert unknown.status_code == 400, unknown.text
    assert "paint" in unknown.json()["detail"]

    misplaced = run_on_board(client, board_id, ws, producer="speak", item_id="n1", kind="note", form={"text": "你好"})
    assert misplaced.status_code == 400, misplaced.text
    assert "speak" in misplaced.json()["detail"]

    #: 表单缺字段是请求体的错 —— 和别的请求体一样回 422,点名是哪一格。
    incomplete = run_on_board(client, board_id, ws, producer="write", item_id="n1", kind="note", form={})
    assert incomplete.status_code == 422, incomplete.text
    assert ["body", "form", "prompt"] in [one["loc"] for one in incomplete.json()["detail"]]


def test_运行要带版本号_旧版本起不了任务() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, [{"id": "n1", "kind": "note", "x": 0, "y": 0}])

    missing = client.post(f"/api/boards/{board_id}/run", json={
        "workspace_id": ws, "item_id": "n1", "kind": "note", "producer": "write", "form": {"prompt": "x"},
    })
    assert missing.status_code == 422, "不带版本号的运行被放过去了"

    stale = run_on_board(client, board_id, ws, producer="write", item_id="n1", kind="note",
                         form={"prompt": "x"}, base_revision=board_revision(client, board_id, ws) + 5)
    assert stale.status_code == 409, stale.text


def test_画布上的表单只认产出者的名字() -> None:
    from app.domain.boards import BoardDomainError, normalize_canvas

    ok = normalize_canvas({"items": [{"id": "a", "kind": "audio", "x": 0, "y": 0, "form": {"producer": "speak"}}]})
    assert ok["items"][0]["form"] == {"producer": "speak"}
    for bad in ("paint", 3, ""):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "a", "kind": "audio", "x": 0, "y": 0, "form": {"producer": bad}}]})


def test_跑过的那一格表单上写着是谁做的(monkeypatch) -> None:
    """占位摆下时,表单末尾写上这一轮的产出者 —— 跑挂了回来,面板照它挂。调用方带来的那个不算数。"""
    import app.domain.voices.engine_catalog as engine_catalog
    import app.domain.voices.voices as voices

    monkeypatch.setattr(engine_catalog, "synthesis_params", lambda db, **kwargs: {})
    monkeypatch.setattr(voices, "start_synthesis", lambda db, **kwargs: SimpleNamespace(id="job-tts"))

    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, [{"id": "a1", "kind": "audio", "x": 0, "y": 0, "form": {"producer": "generate"}}])

    spoken = run_on_board(client, board_id, ws, producer="speak", item_id="a1", kind="audio",
                          form={"text": "你好", "engine": "edge", "engine_voice": "zh-CN-XiaoxiaoNeural"})
    assert spoken.status_code == 200, spoken.text
    form = spoken.json()["canvas"]["items"][0]["form"]
    assert form["producer"] == "speak"
    assert list(form)[-1] == "producer", "产出者要排在表单最后,前端按 JSON 比对表单"


def test_智能体放下的空格子也写明产出者() -> None:
    from app.domain.boards.ops import apply_board_ops

    canvas = apply_board_ops({"items": [], "edges": []}, [
        {"kind": "add_item", "type": "note", "item_id": "n", "text": "开场"},
        {"kind": "add_item", "type": "image", "item_id": "i"},
        {"kind": "add_item", "type": "video", "item_id": "v", "asset_id": "clip-1"},
        {"kind": "add_item", "type": "frame", "item_id": "f"},
    ])
    forms = {one["id"]: one.get("form") for one in canvas["items"]}
    assert forms == {"n": {"producer": "write"}, "i": {"producer": "generate"}, "v": None, "f": None}


def _canvas(board_id: str) -> tuple[dict, int]:
    from app.core.db import SessionLocal
    from app.db.models import Board

    with SessionLocal() as db:
        board = db.get(Board, board_id)
        canvas = json.loads(board.canvas) if isinstance(board.canvas, str) else board.canvas
        return canvas, board.revision


def test_老画板上的每一格写明产出者_照此前前端的推断() -> None:
    """`migrate-board-forms-name-their-producer`:挂哪块面板此前由前端按种类猜,现在写在表单上。"""
    from app.core.db import SessionLocal
    from app.db.migrations import _migrate_board_forms_name_their_producer, migration_plan
    from app.db.models import Board
    from app.domain.boards import normalize_canvas

    assert "migrate-board-forms-name-their-producer" in {step.name for step in migration_plan().steps}

    client = fresh_client()
    ws = _workspace(client)
    trim = {"asset_id": "src", "start": 1.0, "end": 2.0, "mute": False}
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟升级前落库的画布(表单上没有 producer)。
        board = Board(workspace_id=ws, name="旧板", revision=3, canvas={"items": [
            {"id": "note-bare", "kind": "note", "x": 0, "y": 0, "text": "没表单的便签"},
            {"id": "note-form", "kind": "note", "x": 0, "y": 0, "form": {"prompt": "改短", "model": "m"}},
            {"id": "img-empty", "kind": "image", "x": 0, "y": 0},
            {"id": "img-made", "kind": "image", "x": 0, "y": 0, "asset_id": "a1"},
            {"id": "img-form", "kind": "image", "x": 0, "y": 0, "asset_id": "a2", "form": {"prompt": ""}},
            {"id": "vid-cut", "kind": "video", "x": 0, "y": 0, "form": {"trim": trim}, "run": {"status": "failed"}},
            {"id": "vid-gen", "kind": "video", "x": 0, "y": 0, "form": {"prompt": "动起来"}},
            {"id": "aud-cut", "kind": "audio", "x": 0, "y": 0, "form": {"trim": trim}},
            {"id": "aud-empty", "kind": "audio", "x": 0, "y": 0},
            {"id": "aud-made", "kind": "audio", "x": 0, "y": 0, "asset_id": "s1"},
            {"id": "named", "kind": "image", "x": 0, "y": 0, "form": {"producer": "trim", "trim": trim}},
            {"id": "frame", "kind": "frame", "x": 0, "y": 0},
            {"id": "doc", "kind": "document", "x": 0, "y": 0},
        ], "edges": []})
        untouched = Board(workspace_id=ws, name="新板", revision=2, canvas={"items": [
            {"id": "pic", "kind": "image", "x": 0, "y": 0, "asset_id": "a1"},
        ], "edges": []})
        db.add_all([board, untouched])
        db.commit()
        board_id, untouched_id = board.id, untouched.id

    _migrate_board_forms_name_their_producer()
    once, revision = _canvas(board_id)
    _migrate_board_forms_name_their_producer()
    assert _canvas(board_id) == (once, revision), "再跑一次不该再动(版本号也不该再涨)"

    forms = {item["id"]: item.get("form") for item in once["items"]}
    assert forms == {
        "note-bare": {"producer": "write"},
        "note-form": {"prompt": "改短", "model": "m", "producer": "write"},
        "img-empty": {"producer": "generate"},
        "img-made": None,
        "img-form": {"prompt": "", "producer": "generate"},
        "vid-cut": {"trim": trim, "producer": "trim"},
        "vid-gen": {"prompt": "动起来", "producer": "generate"},
        "aud-cut": {"trim": trim, "producer": "trim"},
        "aud-empty": {"producer": "speak"},
        "aud-made": None,
        "named": {"producer": "trim", "trim": trim},
        "frame": None,
        "doc": None,
    }
    #: 升级那一刻还开着这张板的客户端,手里的旧快照要撞 409,不能把产出者盖掉。
    assert revision == 4
    assert _canvas(untouched_id)[1] == 2, "没改到的板版本号不动"
    #: 迁完的画布照现在的规则存得下。
    normalize_canvas(once)
