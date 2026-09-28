"""画板上的时间线格(ADR 0030):格子背后是一条正常的 Mosael 时间线,放在画板自己的同名项目里;连线进来就是接到末尾。"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Board, Project, Sequence
from tests.util import board_revision, fresh_client


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board = client.post("/api/boards", json={"workspace_id": ws, "name": "樱花短片"}).json()["id"]
    return client, ws, board


def _asset(ws: str, asset_id: str, kind: str, **info) -> None:
    with SessionLocal() as db:
        db.add(Asset(id=asset_id, workspace_id=ws, kind=kind, name=asset_id, file_key=f"{asset_id}.bin", media_info=info))
        db.commit()


def test_画板第一次建时间线时建同名项目_之后都放进去_画板改名不丢() -> None:
    client, ws, board = _setup()
    first = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws})
    assert first.status_code == 200, first.text
    client.patch(f"/api/boards/{board}", json={"workspace_id": ws, "name": "改了名", "base_revision": board_revision(client, board, ws)})
    second = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()
    with SessionLocal() as db:
        project_id = db.get(Board, board).project_id
        project = db.get(Project, project_id)
        assert project.name == "樱花短片" and project.workspace_id == ws
        assert {db.get(Sequence, first.json()["sequence_id"]).project_id, db.get(Sequence, second["sequence_id"]).project_id} == {project_id}
    assert first.json()["name"].endswith("时间线 1") and second["name"].endswith("时间线 2")


def test_项目被删了就再建一个() -> None:
    client, ws, board = _setup()
    client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws})
    with SessionLocal() as db:
        old = db.get(Board, board).project_id
    client.delete(f"/api/projects/{old}")
    made = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws})
    assert made.status_code == 200, made.text
    with SessionLocal() as db:
        assert db.get(Board, board).project_id not in (None, old)


def test_时间线格存得下_要带_id_别处的时间线存不下() -> None:
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]

    def save(item):
        return client.patch(f"/api/boards/{board}", json={"workspace_id": ws, "base_revision": board_revision(client, board, ws),
                                                          "canvas": {"items": [item], "edges": []}})

    assert save({"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": sequence}).status_code == 200
    assert save({"id": "t2", "kind": "sequence", "x": 0, "y": 0}).status_code == 400
    other = client.post("/api/workspaces", json={"name": "别处"}).json()["id"]
    other_board = client.post("/api/boards", json={"workspace_id": other, "name": "B"}).json()["id"]
    elsewhere = client.post(f"/api/boards/{other_board}/sequences", json={"workspace_id": other}).json()["sequence_id"]
    refused = save({"id": "t3", "kind": "sequence", "x": 0, "y": 0, "sequence_id": elsewhere})
    assert refused.status_code == 400, refused.text


def test_接到末尾_画幅跟着第一段_音频进音频轨_图片定格五秒() -> None:
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    _asset(ws, "v1", "video", duration=4.0, width=720, height=1280)
    _asset(ws, "v2", "video", duration=3.0, width=1920, height=1080)
    _asset(ws, "pic", "image", width=720, height=1280)
    _asset(ws, "music", "audio", duration=10.0)
    _asset(ws, "blank", "video")
    for asset_id in ("v1", "v2", "pic", "music"):
        response = client.post(f"/api/sequences/{sequence}/append", json={"asset_id": asset_id})
        assert response.status_code == 200, response.text
    body = response.json()
    assert (body["width"], body["height"]) == (720, 1280), "画幅跟着第一段(竖屏),不跟后面的"
    tracks = {track["kind"]: track for track in body["tracks"]}
    video = sorted(tracks["video"]["clips"], key=lambda clip: clip["timeline_start"])
    assert [(clip["asset_id"], clip["timeline_start"], clip["src_out"]) for clip in video] == [
        ("v1", 0.0, 4.0), ("v2", 4.0, 3.0), ("pic", 7.0, 5.0)]
    assert [(clip["asset_id"], clip["timeline_start"]) for clip in tracks["audio"]["clips"]] == [("music", 0.0)]
    assert client.post(f"/api/sequences/{sequence}/append", json={"asset_id": "blank"}).status_code == 422


def test_迁移_画板记着项目这一列() -> None:
    from app.db.migrations import migration_plan

    assert "migrate-boards-remember-their-project" in {step.name for step in migration_plan().steps}


def test_时间线格挂导出_存下时写明产出者() -> None:
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    saved = client.patch(f"/api/boards/{board}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board, ws),
        "canvas": {"items": [{"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": sequence}], "edges": []}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["canvas"]["items"][0]["form"] == {"producer": "sequence_export"}


def test_导出设置照剪辑页那一份_不认识的值说清楚() -> None:
    import pytest

    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors.subjobs import export_params

    assert export_params({}) is None, "一样都没填就按默认档导出"
    assert export_params({"resolution": "720p", "quality": "compact", "ai_label": "no"}) == {
        "resolution": "720p", "quality": "compact", "ai_label": False}
    assert export_params({"resolution": "original", "ai_label": "yes"}) == {"resolution": "original", "ai_label": True}
    with pytest.raises(WorkflowDomainError):
        export_params({"resolution": "4k"})


def test_导出档位和剪辑页的请求体是同一张表() -> None:
    from typing import get_args

    from app.api.schemas.sequences import ExportRequest
    from app.domain.boards.producers import SequenceExportConfig
    from app.domain.export_presets import EXPORT_QUALITIES, EXPORT_RESOLUTIONS

    for model in (ExportRequest, SequenceExportConfig):
        assert set(get_args(model.model_fields["resolution"].annotation)) == set(EXPORT_RESOLUTIONS)
        assert set(get_args(model.model_fields["quality"].annotation)) == set(EXPORT_QUALITIES)


def test_在时间线格上导出_成片落成右边一格视频_时间线格不动(monkeypatch) -> None:
    import time
    from types import SimpleNamespace

    from app.domain import render
    from app.domain.workflows.executors import subjobs
    from tests.util import run_on_board

    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    _asset(ws, "final", "video", duration=6.0, width=1080, height=1920)
    asked: list[tuple[str, dict | None]] = []

    def fake_export(db, sequence_id, export_params=None, *, created_by):
        asked.append((sequence_id, export_params))
        return SimpleNamespace(id="render-job")

    monkeypatch.setattr(render, "start_export", fake_export)
    monkeypatch.setattr(subjobs, "wait_for_job", lambda job_id, release=None: SimpleNamespace(result={"asset_id": "final"}))
    client.patch(f"/api/boards/{board}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board, ws),
        "canvas": {"items": [{"id": "t", "kind": "sequence", "x": 0, "y": 0, "width": 560, "height": 400,
                              "sequence_id": sequence}], "edges": []}})

    placed = run_on_board(client, board, ws, producer="sequence_export", item_id="t", kind="sequence",
                          form={"config": {"resolution": "720p", "ai_label": "no"}})
    assert placed.status_code == 200, placed.text
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        canvas = client.get(f"/api/boards/{board}", params={"workspace_id": ws}).json()["canvas"]
        host = next(one for one in canvas["items"] if one["id"] == "t")
        if (host.get("run") or {}).get("status") in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert host["run"] == {"status": "succeeded"}, host
    assert asked == [(sequence, {"resolution": "720p", "quality": "standard", "ai_label": False})]
    #: 时间线格自己不动;表单照存,下一次照它再导。
    assert host["sequence_id"] == sequence and "asset_id" not in host
    assert host["form"] == {"config": {"resolution": "720p", "ai_label": "no"}, "producer": "sequence_export"}
    made = [one for one in canvas["items"] if one["id"] != "t"]
    assert [(one["kind"], one["asset_id"]) for one in made] == [("video", "final")]
    assert made[0]["x"] > host["x"] + host["width"]
    assert canvas["edges"] == [{"id": f"t->{made[0]['id']}", "source": "t", "target": made[0]["id"]}]

    #: 只能挂在时间线格上;设置不在那几档里就拒。
    assert run_on_board(client, board, ws, producer="sequence_export", item_id="t", kind="sequence",
                        form={"config": {"resolution": "4k"}}).status_code == 422


def test_迁移_已经放下的时间线格写明导出_别的格子不动() -> None:
    import json

    from app.db.migrations import _migrate_board_sequence_cells_name_their_producer, migration_plan

    assert "migrate-board-sequence-cells-name-their-producer" in {step.name for step in migration_plan().steps}
    client, ws, _ = _setup()
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟升级前落库的画布。
        board = Board(workspace_id=ws, name="旧板", revision=3, canvas={"items": [
            {"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": "s1"},
            {"id": "n", "kind": "note", "x": 0, "y": 0, "text": "旁白", "form": {"producer": "write"}},
        ], "edges": []})
        untouched = Board(workspace_id=ws, name="新板", revision=2, canvas={"items": [
            {"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": "s2", "form": {"producer": "sequence_export"}},
        ], "edges": []})
        db.add_all([board, untouched])
        db.commit()
        board_id, untouched_id = board.id, untouched.id

    def read(board_id: str) -> tuple[dict, int]:
        with SessionLocal() as db:
            row = db.get(Board, board_id)
            return (json.loads(row.canvas) if isinstance(row.canvas, str) else row.canvas), row.revision

    _migrate_board_sequence_cells_name_their_producer()
    once, revision = read(board_id)
    _migrate_board_sequence_cells_name_their_producer()
    assert read(board_id) == (once, revision) and revision == 4, "再跑一次不该再动"
    items = {item["id"]: item for item in once["items"]}
    assert items["t"]["form"] == {"producer": "sequence_export"} and items["t"]["sequence_id"] == "s1"
    assert items["n"]["form"] == {"producer": "write"}
    assert read(untouched_id)[1] == 2
