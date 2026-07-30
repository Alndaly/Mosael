from __future__ import annotations

import json
import time

from app.core.config import settings
from tests.test_publish import make_video_asset
from tests.util import fresh_client


def _wait_for(client, task_id: str, *, timeout: float = 5.0) -> dict:
    """交付在后台线程里跑,轮询到终态为止。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tasks = client.get(f"/api/delivery/tasks?workspace_id={_ws_of(client, task_id)}").json()
        for task in tasks:
            if task["id"] == task_id and task["status"] in ("succeeded", "failed"):
                return task
        time.sleep(0.05)
    raise AssertionError("交付任务未在超时内到达终态")


_WS: dict[str, str] = {}


def _ws_of(client, task_id: str) -> str:
    return _WS[task_id]


def test_folder_delivery_copies_file_and_writes_sidecar(tmp_path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = make_video_asset(client, ws["id"])
    outdir = tmp_path / "交付"

    target = client.post(
        "/api/delivery/targets",
        json={"workspace_id": ws["id"], "kind": "folder", "name": "本地", "config": {"directory": str(outdir)}},
    )
    assert target.status_code == 200, target.text

    started = client.post(
        "/api/delivery/start",
        json={
            "workspace_id": ws["id"],
            "target_id": target.json()["id"],
            "asset_id": asset["id"],
            "title": "成片A",
            "tags": ["x"],
        },
    )
    assert started.status_code == 200, started.text
    _WS[started.json()["id"]] = ws["id"]
    done = _wait_for(client, started.json()["id"])
    assert done["status"] == "succeeded", done

    copied = outdir / "成片A.mp4"
    assert copied.exists()
    sidecar = json.loads((outdir / "成片A.mp4.json").read_text(encoding="utf-8"))
    assert sidecar["title"] == "成片A"
    assert sidecar["tags"] == ["x"]


def test_delivery_target_requires_its_config() -> None:
    """folder 没给 directory 就该在建目标时失败,而不是等到跑起来才炸。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    res = client.post("/api/delivery/targets", json={"workspace_id": ws["id"], "kind": "folder", "config": {}})
    assert res.status_code == 422


def test_unknown_delivery_kind_is_rejected() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    res = client.post("/api/delivery/targets", json={"workspace_id": ws["id"], "kind": "ftp", "config": {}})
    assert res.status_code == 422


def test_delivery_target_does_not_create_a_browser_profile() -> None:
    """这是这次拆分的核心:交付目标不需要登录身份。

    拆分前 folder/webhook 走的是 create_account,而它**无条件**建一个 BrowserProfile ——
    于是每建一个「本地目录」,浏览器池里就多一个永远不会有登录态的空壳档案,还占一个永远
    不会被使用的 Chromium 分区名。
    """
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    before = client.get(f"/api/browser/profiles?workspace_id={ws['id']}").json()
    client.post(
        "/api/delivery/targets",
        json={"workspace_id": ws["id"], "kind": "folder", "config": {"directory": str(settings.data_dir / "out")}},
    )
    after = client.get(f"/api/browser/profiles?workspace_id={ws['id']}").json()
    assert len(after) == len(before), "建交付目标不应产生浏览器档案"


def test_delivery_kinds_are_listed() -> None:
    client = fresh_client()
    kinds = client.get("/api/delivery/kinds").json()
    assert {k["kind"] for k in kinds} == {"folder", "webhook"}
