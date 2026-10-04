"""画板上的一次生成**一次摆好它会交回的那么多格占位**,落回时不多不少。

用户在图片格的生成面板选「1×」,点生成之后落出两三格:ComfyUI 的一张工作流常常不止一个保存节点(原图 + 放大、
几个预览),一次运行交回的是这几个节点各一份;画板此前只摆一格占位,第二份起在回执到的那一刻才往右冒出来。
现在模型说一次交回几份(`outputs_per_run`,随「结果取自」变的写在那个参数的 `x-outputs-per-run` 上)× 张数
(generation.catalog.outputs_per_run),发起生成时就摆好那么多格;回执按先后填进去,交回的少了多摆的收掉、多了照旧
往右排,失败 / 取消时一起摆的那几格收掉(这一格留着提示词等重试)。
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import ProviderProfile
from tests.fake_comfyui import comfyui_grants, PNG, TWO_SAVES_API, TWO_VIDEOS_API, FakeComfyUI
from tests.util import fresh_client, run_on_board

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"


# --- 一次交回几份 ---------------------------------------------------------------


def test_一次交回几份_模型说的每次几份乘张数() -> None:
    from app.domain.generation.catalog import outputs_per_run

    choice = {"type": "string", "enum": ["all", "9", "12"], "x-outputs-per-run": {"all": 2, "9": 1, "12": 1}}
    caps = {"outputs_per_run": 2, "parameter_schema": {"output_node": choice}}
    assert outputs_per_run(caps, {}) == 2, "没选「结果取自」:两个保存节点各一份"
    assert outputs_per_run(caps, {"num_images": 3}) == 6
    assert outputs_per_run(caps, {"output_node": "12", "num_images": 3}) == 3, "只要一个节点的"
    assert outputs_per_run(caps, {"output_node": "all"}) == 2
    assert outputs_per_run(caps, {"output_node": "gone"}) == 2, "表里没有的取值:照模型说的"
    #: 没说的(内置的图像模型):张数就是份数。
    assert outputs_per_run({"parameter_keys": ["num_images"]}, {"num_images": 4}) == 4
    assert outputs_per_run(None, {}) == 1
    assert outputs_per_run({"outputs_per_run": True}, {"num_images": "2"}) == 1, "形状不对的不认"


# --- 摆占位、落回(纯合并)--------------------------------------------------------


def _board(client, ws: str, items: list[dict[str, Any]]) -> str:
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": items, "edges": []}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _items(client, board_id: str, ws: str) -> list[dict[str, Any]]:
    return client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]


def _place(ws: str, board_id: str, *, outputs: int, job: str = "job-x") -> list[dict[str, Any]]:
    from app.domain.boards import place_pending

    with SessionLocal() as db:
        placed = place_pending(db, workspace_id=ws, board_id=board_id, outputs=outputs, item={
            "id": "img-1", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": job},
            "form": {"prompt": "两只猫", "model": "two.json", "producer": "generate"},
        })
        db.commit()
        return placed.canvas["items"]


def _deliver(board_id: str, *, status: str = "succeeded", asset_ids: list[str] | None = None, error: str = "") -> None:
    from app.domain.boards import deliver_generated, receipt_to_item

    job = SimpleNamespace(id="job-x", status=status, result={"asset_ids": asset_ids or []} if status == "succeeded" else None,
                          error=error, payload={}, created_by=None)
    with SessionLocal() as db:
        deliver_generated(db, job, receipt_to_item(board_id, "img-1"))
        db.commit()


@pytest.fixture
def slot():
    """一张板,图片空格子 `img-1` 在 (100, 50)、宽 200;旁边还有上一轮落下的 `img-1-2`。"""
    from tests.util import seed_assets

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {one: "image" for one in ("a", "b", "c", "d", "old")})
    board_id = _board(client, ws, [
        {"id": "img-1", "kind": "image", "x": 100, "y": 50, "width": 200},
        {"id": "img-1-2", "kind": "image", "x": 324, "y": 50, "asset_id": "old"},
    ])
    return client, ws, board_id


def test_发起生成时一次摆好那么多格占位(slot) -> None:
    client, ws, board_id = slot
    items = {one["id"]: one for one in _place(ws, board_id, outputs=3)}
    assert set(items) == {"img-1", "img-1-2", "img-1-3", "img-1-4"}, "上一轮落下的那格不动,新的往后排"
    for one in ("img-1", "img-1-3", "img-1-4"):
        assert items[one]["run"] == {"status": "running", "job_id": "job-x"}, one
        assert items[one]["form"]["prompt"] == "两只猫"
    #: 和回执往右排的是同一个位置:第 n 格在第 n-1 列,宽按这一格自己的宽。
    assert [items[one]["x"] for one in ("img-1", "img-1-3", "img-1-4")] == [100, 548, 772]
    assert {items[one]["y"] for one in ("img-1-3", "img-1-4")} == {50}
    assert items["img-1-2"].get("asset_id") == "old" and "run" not in items["img-1-2"]


def test_落回时不多不少(slot) -> None:
    client, ws, board_id = slot
    _place(ws, board_id, outputs=3)
    _deliver(board_id, asset_ids=["a", "b", "c"])
    items = {one["id"]: one for one in _items(client, board_id, ws)}
    assert [items[one]["asset_id"] for one in ("img-1", "img-1-3", "img-1-4")] == ["a", "b", "c"]
    assert set(items) == {"img-1", "img-1-2", "img-1-3", "img-1-4"}, "没有事后冒出来的格子"
    assert all(one.get("run", {}).get("status") != "running" for one in items.values())
    assert items["img-1-3"]["run"] == {"status": "succeeded"} and items["img-1-3"]["form"]["prompt"] == "", (
        "和这一格一样:提示词用掉了,模型留着")


def test_交回的少了_多摆的占位收掉(slot) -> None:
    client, ws, board_id = slot
    _place(ws, board_id, outputs=3)
    _deliver(board_id, asset_ids=["a", "b"])
    items = {one["id"]: one for one in _items(client, board_id, ws)}
    assert set(items) == {"img-1", "img-1-2", "img-1-3"}
    assert (items["img-1"]["asset_id"], items["img-1-3"]["asset_id"]) == ("a", "b")


def test_交回的多了_多出来的照旧往右排(slot) -> None:
    client, ws, board_id = slot
    _place(ws, board_id, outputs=2)
    _deliver(board_id, asset_ids=["a", "b", "c", "d"])
    items = {one["id"]: one for one in _items(client, board_id, ws)}
    assert [items[one]["asset_id"] for one in ("img-1", "img-1-3", "img-1-4", "img-1-5")] == ["a", "b", "c", "d"]
    assert [items[one]["x"] for one in ("img-1-4", "img-1-5")] == [772, 996]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_失败或取消_一起摆的占位收掉_这一格留着重试(slot, status: str) -> None:
    client, ws, board_id = slot
    _place(ws, board_id, outputs=3)
    _deliver(board_id, status=status, error="CUDA out of memory")
    items = {one["id"]: one for one in _items(client, board_id, ws)}
    assert set(items) == {"img-1", "img-1-2"}
    assert items["img-1"]["run"]["status"] in ("failed", "cancelled") and items["img-1"]["form"]["prompt"] == "两只猫"


def test_这一格已经不是这一轮了_一起摆的占位照样收下产出(slot) -> None:
    """生成还在跑时这一格被换成了别的(手动换了素材):它不收这一轮的产出,一起摆的那几格按先后收下,不留着转圈。"""
    from app.db.models import Board

    client, ws, board_id = slot
    _place(ws, board_id, outputs=3)
    with SessionLocal() as db:
        board = db.get(Board, board_id)
        items = [({**one, "run": {"status": "idle"}, "asset_id": "old"} if one["id"] == "img-1" else one)
                 for one in board.canvas["items"]]
        board.canvas = {**board.canvas, "items": items}
        db.commit()
    _deliver(board_id, asset_ids=["a", "b", "c"])
    items = {one["id"]: one for one in _items(client, board_id, ws)}
    assert items["img-1"]["asset_id"] == "old"
    assert (items["img-1-3"]["asset_id"], items["img-1-4"]["asset_id"]) == ("a", "b")
    assert all(one.get("run", {}).get("status") != "running" for one in items.values())


# --- 从头到尾:ComfyUI 的两个保存节点 --------------------------------------------


@pytest.fixture
def connected():
    with FakeComfyUI() as comfy:
        comfy.state.workflows["two.json"] = TWO_SAVES_API
        comfy.state.workflows["two_videos.json"] = TWO_VIDEOS_API
        client = fresh_client()
        created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
        assert created.status_code == 200, created.text
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
        enabled = client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
        assert enabled.status_code == 200, enabled.text
        with SessionLocal() as db:
            profile_id = db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))
        ws = client.post("/api/workspaces", json={"name": "ComfyUI"}).json()["id"]
        yield client, comfy, ws, profile_id


def _generate(client, ws: str, profile_id: str, *, kind: str = "image", model: str = "two.json",
              parameters: dict[str, Any] | None = None,
              sources: list[dict[str, str]] | None = None) -> tuple[str, list[dict[str, Any]]]:
    board_id = _board(client, ws, [{"id": "cell", "kind": kind, "x": 0, "y": 0, "width": 240}])
    form = {"prompt": "", "provider": VENDOR, "provider_profile_id": profile_id, "model": model,
            "parameters": parameters or {}, "source_assets": sources or [], "item_form": {"prompt": ""}}
    started = run_on_board(client, board_id, ws, producer="generate", item_id="cell", kind=kind, form=form)
    assert started.status_code == 200, started.text
    return board_id, started.json()["canvas"]["items"]


def _settled(client, board_id: str, ws: str) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        items = _items(client, board_id, ws)
        if not any((one.get("run") or {}).get("status") in ("queued", "running") for one in items):
            return items
        time.sleep(0.1)
    raise AssertionError("一直没落回来")


def test_两个保存节点的工作流_点一次就摆两格_落回两张(connected) -> None:
    client, comfy, ws, profile_id = connected
    comfy.state.outputs = {"9": {"images": [{"filename": "base_00001_.png", "subfolder": "", "type": "output"}]},
                           "12": {"images": [{"filename": "hd_00001_.png", "subfolder": "", "type": "output"}]}}
    board_id, placed = _generate(client, ws, profile_id)
    assert [one["id"] for one in placed] == ["cell", "cell-2"]
    assert len({one["run"]["job_id"] for one in placed}) == 1
    items = _settled(client, board_id, ws)
    assert [one["id"] for one in items] == ["cell", "cell-2"]
    assert all(one["run"]["status"] == "succeeded" and one.get("asset_id") for one in items)


def test_结果取自选一个节点_就只摆一格(connected) -> None:
    client, comfy, ws, profile_id = connected
    comfy.state.outputs = {"9": {"images": [{"filename": "base_00001_.png", "subfolder": "", "type": "output"}]},
                           "12": {"images": [{"filename": "hd_00001_.png", "subfolder": "", "type": "output"}]}}
    board_id, placed = _generate(client, ws, profile_id, parameters={"output_node": "12"})
    assert [one["id"] for one in placed] == ["cell"]
    [cell] = _settled(client, board_id, ws)
    assert cell["run"]["status"] == "succeeded" and cell["asset_id"]


def test_两个节点乘两张_摆四格(connected) -> None:
    client, comfy, ws, profile_id = connected
    comfy.state.outputs = {
        "9": {"images": [{"filename": f"base_{n}.png", "subfolder": "", "type": "output"} for n in (1, 2)]},
        "12": {"images": [{"filename": f"hd_{n}.png", "subfolder": "", "type": "output"} for n in (1, 2)]},
    }
    board_id, placed = _generate(client, ws, profile_id, parameters={"num_images": 2})
    assert [one["id"] for one in placed] == ["cell", "cell-2", "cell-3", "cell-4"]
    items = _settled(client, board_id, ws)
    assert len(items) == 4 and len({one["asset_id"] for one in items}) == 4


def test_两个视频保存节点_摆两格视频(connected) -> None:
    client, comfy, ws, profile_id = connected
    comfy.state.outputs = {"30": {"gifs": [{"filename": "a.mp4", "subfolder": "", "type": "output"}]},
                           "31": {"gifs": [{"filename": "b.mp4", "subfolder": "", "type": "output"}]}}
    uploaded = client.post("/api/assets/import", data={"workspace_id": ws}, files={"file": ("首帧.png", PNG, "image/png")})
    first_frame = {"asset_id": uploaded.json()["id"], "role": "first_frame"}  # 图生视频:首帧必须给
    board_id, placed = _generate(client, ws, profile_id, kind="video", model="two_videos.json", sources=[first_frame])
    assert [(one["id"], one["kind"]) for one in placed] == [("cell", "video"), ("cell-2", "video")]
    items = _settled(client, board_id, ws)
    assert [one["kind"] for one in items] == ["video", "video"] and all(one.get("asset_id") for one in items)
