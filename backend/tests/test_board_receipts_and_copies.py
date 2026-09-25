"""画板回执与复制的边界 —— 这几条都是「不报错、只是东西没了」的那种。"""

from __future__ import annotations

from types import SimpleNamespace

from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _board(client, ws: str, canvas: dict) -> str:
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": canvas})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _deliver(board_id: str, item_id: str, job: SimpleNamespace) -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import deliver_generated, receipt_to_item

    with SessionLocal() as db:
        deliver_generated(db, job, receipt_to_item(board_id, item_id))


def _canvas(client, ws: str, board_id: str) -> dict:
    return client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]


def test_产出落回时画板上的标记还在() -> None:
    """标记和 items 平级 —— 回执只动它那一格,不该顺手把整张板的书签清掉。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
        "markers": [{"id": "m1", "name": "开头", "x": 10, "y": 20}],
    })

    _deliver(board_id, "img", SimpleNamespace(id="job-1", status="succeeded", result={"asset_ids": ["a1"]}))

    canvas = _canvas(client, ws, board_id)
    assert canvas["items"][0]["asset_id"] == "a1"
    assert [one["id"] for one in canvas["markers"]] == ["m1"], "产出一落回来,用户放的标记全没了"


def test_失败回执同样不动标记() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
        "markers": [{"id": "m1", "name": "开头", "x": 10, "y": 20}],
    })

    _deliver(board_id, "img", SimpleNamespace(id="job-1", status="failed", result=None, error="炸了"))

    assert [one["id"] for one in _canvas(client, ws, board_id)["markers"]] == ["m1"]


def test_同一格再出一次多张_多出来的那几张不撞上一轮的() -> None:
    """一次出两张:占位那一格拿第一张,第二张另起一格。**再生成一次**同样出两张时,第二张的新格子
    不能和上一轮那一格同名 —— 撞了的话整次回执被 normalize 拒掉,产出一张都没落回来,
    那一格永远停在「生成中」。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "width": 200,
                   "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
    })
    _deliver(board_id, "img", SimpleNamespace(id="job-1", status="succeeded", result={"asset_ids": ["a1", "a2"]}))
    first = _canvas(client, ws, board_id)
    assert [one["asset_id"] for one in first["items"]] == ["a1", "a2"]

    # 第二轮:同一格重新进入生成(place_pending 的效果),再交回两张。
    from app.core.db import SessionLocal
    from app.domain.boards import place_pending

    with SessionLocal() as db:
        place_pending(db, workspace_id=ws, board_id=board_id, item={
            "id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-2"},
        })
    _deliver(board_id, "img", SimpleNamespace(id="job-2", status="succeeded", result={"asset_ids": ["b1", "b2"]}))

    items = {one["id"]: one for one in _canvas(client, ws, board_id)["items"]}
    # 占位那一格就地换成这一轮的第一张;上一轮多出来的那格原样留着;这一轮多出来的另起一格。
    assert {key: one["asset_id"] for key, one in items.items()} == {"img": "b1", "img-2": "a2", "img-3": "b2"}, (
        f"第二轮的产出没落回来:{items}"
    )
    assert all((one.get("run") or {}).get("status") == "succeeded" for one in items.values()), "还有一格停在生成中"
    assert items["img-3"]["x"] != items["img-2"]["x"], "新的一格正好叠在上一轮那一格上,看着像只出了一张"


def test_起任务后才撞上并发保存_占位照样落下_任务照样起(monkeypatch) -> None:
    """版本检查在建任务**之前**做(没花钱时拒);可建任务到摆占位之间还有一段窗口 —— 同一个人的
    自动保存正好在这时落库,占位就撞 409。此前那一刻任务已经建好了(钱在路上),而占位没摆、
    线程没起:任务中心里一条永远排队的任务,画布上什么都没有,用户看到的是一句「有冲突」。

    摆占位是服务端对**一格**的合并,不是客户端快照 —— 它该合到最新的画布上,而不是被这次保存挡回去。"""
    import app.domain.generation as generation
    import app.domain.generation.runner as runner
    from app.core.db import SessionLocal
    from app.domain.boards import update_board
    from app.domain.boards.actions import Slot, generate_on_board

    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {"items": [{"id": "img", "kind": "image", "x": 0, "y": 0}], "edges": []})
    user_id = client.get("/api/auth/me").json()["id"]
    started: list[str] = []

    def create_job_while_user_autosaves(db, **_kwargs):
        with SessionLocal() as other:
            update_board(other, workspace_id=ws, board_id=board_id, canvas={
                "items": [{"id": "img", "kind": "image", "x": 40, "y": 0},
                          {"id": "n1", "kind": "note", "x": 400, "y": 0, "text": "刚加的"}],
                "edges": [],
            })
        return SimpleNamespace(id="gen-1", provider="p", provider_profile_id="pp", model="m"), SimpleNamespace(id="job-1")

    monkeypatch.setattr(generation, "create_generation_job", create_job_while_user_autosaves)
    monkeypatch.setattr(runner, "start_generation_thread", started.append)

    revision = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["revision"]
    with SessionLocal() as db:
        generate_on_board(
            db, workspace_id=ws, slot=Slot(board_id, "img", 0, 0, revision), actor_id=user_id, kind="image",
            prompt="一只猫", provider="p", provider_profile_id="pp", model="m", parameters={}, source_assets=[],
            form={"prompt": "一只猫"},
        )

    assert started == ["gen-1"], "任务建了却没起 —— 任务中心里永远排着一条"
    items = {one["id"]: one for one in _canvas(client, ws, board_id)["items"]}
    assert items["img"]["run"] == {"status": "running", "job_id": "job-1"}
    assert items["img"]["x"] == 40, "占位把并发保存里用户刚拖的位置盖回去了"
    assert "n1" in items, "占位把并发保存里刚加的那一项抹掉了"
