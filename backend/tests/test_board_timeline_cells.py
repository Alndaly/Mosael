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


def test_复制画板_时间线格各自复制一条_不和原板共用() -> None:
    """共用的话在副本里剪一刀原板跟着变,两边的撤销还会互相撤掉对方的步骤。"""
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    _asset(ws, "v1", "video", duration=4.0, width=720, height=1280)
    client.post(f"/api/sequences/{sequence}/append", json={"asset_id": "v1"})
    client.patch(f"/api/boards/{board}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board, ws),
        "canvas": {"items": [{"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": sequence},
                             {"id": "t2", "kind": "sequence", "x": 400, "y": 0, "sequence_id": sequence}], "edges": []}})

    copy = client.post(f"/api/boards/{board}/duplicate", json={"workspace_id": ws, "name": "副本"})
    assert copy.status_code == 200, copy.text
    ids = {item["sequence_id"] for item in copy.json()["canvas"]["items"]}
    assert len(ids) == 1 and sequence not in ids, "副本指向自己的那一条;同一条时间线的两格复制后仍是同一条"
    with SessionLocal() as db:
        original, copied = db.get(Sequence, sequence), db.get(Sequence, ids.pop())
        assert copied.project_id == db.get(Board, copy.json()["id"]).project_id != original.project_id
        assert (copied.width, copied.height) == (720, 1280)
        clips = [(clip.asset_id, clip.timeline_start, clip.src_out) for track in copied.tracks for clip in track.clips]
        assert clips == [("v1", 0.0, 4.0)]
        assert {track.id for track in copied.tracks}.isdisjoint({track.id for track in original.tracks})


def test_画板上复制一格时间线格_照原件复制一条时间线_别处的拒() -> None:
    """画板上「复制」一格时间线格和整板复制同一条:副本指向自己的那一条,在副本里剪一刀原件不跟着变。"""
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    _asset(ws, "v1", "video", duration=4.0, width=720, height=1280)
    client.post(f"/api/sequences/{sequence}/append", json={"asset_id": "v1"})

    made = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws, "copy_of": sequence})
    assert made.status_code == 200, made.text
    copied_id = made.json()["sequence_id"]
    assert copied_id != sequence
    with SessionLocal() as db:
        original, copied = db.get(Sequence, sequence), db.get(Sequence, copied_id)
        assert copied.project_id == original.project_id, "同一张画板的项目里"
        assert [(clip.asset_id, clip.src_out) for track in copied.tracks for clip in track.clips] == [("v1", 4.0)]
        assert {track.id for track in copied.tracks}.isdisjoint({track.id for track in original.tracks})

    other = client.post("/api/workspaces", json={"name": "别处"}).json()["id"]
    other_board = client.post("/api/boards", json={"workspace_id": other, "name": "B"}).json()["id"]
    elsewhere = client.post(f"/api/boards/{other_board}/sequences", json={"workspace_id": other}).json()["sequence_id"]
    refused = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws, "copy_of": elsewhere})
    assert refused.status_code == 400, refused.text


def test_空槽连进时间线格_生成出来之后接到末尾_只接一次() -> None:
    """连线那一刻它还是空槽,没什么可接;产出落下时补接 —— 线在它就在。同一封回执送两次(占位落下时的补送和正常的
    那封撞在一起)只接一次;没连着时间线的格子照旧。"""
    from types import SimpleNamespace

    from app.domain.boards import deliver_generated, receipt_to_item

    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    _asset(ws, "made", "video", duration=3.0, width=720, height=1280)
    slot = {"id": "v", "kind": "video", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-v"},
            "form": {"producer": "generate", "prompt": "海浪"}}
    saved = client.patch(f"/api/boards/{board}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board, ws),
        "canvas": {"items": [slot, {"id": "t", "kind": "sequence", "x": 400, "y": 0, "sequence_id": sequence}],
                   "edges": [{"id": "e", "source": "v", "target": "t"}]}})
    assert saved.status_code == 200, saved.text

    job = SimpleNamespace(id="job-v", status="succeeded", result={"asset_ids": ["made"]}, created_by=None)
    with SessionLocal() as db:
        deliver_generated(db, job, receipt_to_item(board, "v"))
        deliver_generated(db, job, receipt_to_item(board, "v"))
    with SessionLocal() as db:
        clips = [(clip.asset_id, clip.src_out) for track in db.get(Sequence, sequence).tracks for clip in track.clips]
    assert clips == [("made", 3.0)], clips


def test_画板上的撤销带着版本号_时间线在别处改过就不撤别人的那一步() -> None:
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    _asset(ws, "v1", "video", duration=4.0, width=720, height=1280)
    _asset(ws, "v2", "video", duration=3.0, width=720, height=1280)
    mine = client.post(f"/api/sequences/{sequence}/append", json={"asset_id": "v1"}).json()["revision"]
    #: 剪辑页(或智能体)又在同一条时间线上接了一段。
    client.post(f"/api/sequences/{sequence}/append", json={"asset_id": "v2"})

    refused = client.post(f"/api/sequences/{sequence}/undo?expected_revision={mine}")
    assert refused.status_code == 409, refused.text
    clips = [clip["asset_id"] for track in client.get(f"/api/sequences/{sequence}").json()["tracks"] for clip in track["clips"]]
    assert sorted(clips) == ["v1", "v2"], "别处接的那一段没被撤掉"

    current = client.get(f"/api/sequences/{sequence}").json()["revision"]
    undone = client.post(f"/api/sequences/{sequence}/undo?expected_revision={current}")
    assert undone.status_code == 200, undone.text
    redone = client.post(f"/api/sequences/{sequence}/redo?expected_revision={undone.json()['revision']}")
    assert redone.status_code == 200, redone.text
    assert client.post(f"/api/sequences/{sequence}/redo?expected_revision={current}").status_code == 409
    assert client.post(f"/api/sequences/{sequence}/undo").status_code == 200, "不带版本号(剪辑页)照旧撤最新一步"


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


# ── 智能体(edit_board)认识时间线格 ─────────────────────────────────────────


def _edit_card(client, ws: str, board_id: str, operations: list[dict]):
    return client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "edit_board", "requested_by": "agent",
        "payload": {"board_id": board_id, "operations": operations}})


def test_智能体放一格新的时间线_批准了才建_连进来的素材接到末尾() -> None:
    client, ws, board = _setup()
    _asset(ws, "v1", "video", duration=4.0, width=720, height=1280)
    _asset(ws, "pic", "image", width=720, height=1280)
    client.patch(f"/api/boards/{board}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board, ws),
        "canvas": {"items": [{"id": "v", "kind": "video", "x": 0, "y": 0, "asset_id": "v1"},
                             {"id": "p", "kind": "image", "x": 0, "y": 300, "asset_id": "pic"},
                             {"id": "slot", "kind": "video", "x": 0, "y": 600}], "edges": []}})
    with SessionLocal() as db:
        before = db.query(Sequence).count()

    card = _edit_card(client, ws, board, [
        {"kind": "add_item", "type": "sequence", "item_id": "t1"},
        {"kind": "connect", "source": "v", "target": "t1"},
        {"kind": "connect", "source": "p", "target": "t1"},
        {"kind": "connect", "source": "slot", "target": "t1"},
    ])
    assert card.status_code == 200, card.text
    with SessionLocal() as db:
        assert db.query(Sequence).count() == before, "干跑不建时间线:用户还没点同意"
    approved = client.post(f"/api/confirmations/{card.json()['id']}/approve").json()
    assert approved["status"] == "executed", approved
    assert approved["result"]["appended_clips"] == 2, "空槽没什么可接"

    canvas = client.get(f"/api/boards/{board}", params={"workspace_id": ws}).json()["canvas"]
    cell = next(one for one in canvas["items"] if one["id"] == "t1")
    assert cell["form"] == {"producer": "sequence_export"}
    assert cell["text"].startswith("樱花短片 · 时间线")
    body = client.get(f"/api/sequences/{cell['sequence_id']}").json()
    video = sorted(next(t for t in body["tracks"] if t["kind"] == "video")["clips"], key=lambda one: one["timeline_start"])
    assert [one["asset_id"] for one in video] == ["v1", "pic"], "按连线的先后接到末尾"
    with SessionLocal() as db:
        assert db.get(Sequence, cell["sequence_id"]).project_id == db.get(Board, board).project_id

    #: 再连一次同一根线不再接一遍;已经连着的也不重接。
    again = _edit_card(client, ws, board, [{"kind": "connect", "source": "v", "target": "t1"},
                                           {"kind": "set_title", "item_id": "t1", "title": "成片"}])
    assert client.post(f"/api/confirmations/{again.json()['id']}/approve").json()["result"]["appended_clips"] == 0


def test_智能体引用已有的时间线_别处的拒() -> None:
    client, ws, board = _setup()
    mine = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    card = _edit_card(client, ws, board, [{"kind": "add_item", "type": "sequence", "sequence_id": mine}])
    assert card.status_code == 200, card.text
    assert client.post(f"/api/confirmations/{card.json()['id']}/approve").json()["status"] == "executed"
    assert any(one.get("sequence_id") == mine
               for one in client.get(f"/api/boards/{board}", params={"workspace_id": ws}).json()["canvas"]["items"])

    other = client.post("/api/workspaces", json={"name": "别处"}).json()["id"]
    other_board = client.post("/api/boards", json={"workspace_id": other, "name": "B"}).json()["id"]
    elsewhere = client.post(f"/api/boards/{other_board}/sequences", json={"workspace_id": other}).json()["sequence_id"]
    refused = _edit_card(client, ws, board, [{"kind": "add_item", "type": "sequence", "sequence_id": elsewhere}])
    assert refused.status_code == 422, refused.text


def test_智能体给时间线格写导出设置_不认识的值开卡就拒() -> None:
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    client.patch(f"/api/boards/{board}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board, ws),
        "canvas": {"items": [{"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": sequence}], "edges": []}})
    card = _edit_card(client, ws, board, [{"kind": "set_form", "item_id": "t", "config": {"resolution": "720p"}}])
    assert card.status_code == 200, card.text
    assert client.post(f"/api/confirmations/{card.json()['id']}/approve").json()["status"] == "executed"
    item = next(one for one in client.get(f"/api/boards/{board}", params={"workspace_id": ws}).json()["canvas"]["items"])
    assert item["form"] == {"config": {"resolution": "720p"}, "producer": "sequence_export"}
    refused = _edit_card(client, ws, board, [{"kind": "set_form", "item_id": "t", "config": {"resolution": "4k"}}])
    assert refused.status_code == 422, refused.text


def test_工具说明里讲清时间线格() -> None:
    import mcp_server
    from app.domain.agent.prompt import SYSTEM_PROMPT_TEMPLATE as SYSTEM_PROMPT

    assert "sequence" in mcp_server.edit_board.__doc__ and "TIMELINE ITEM" in mcp_server.edit_board.__doc__
    assert "sequence_export" in mcp_server.get_board.__doc__
    assert "sequence_export" in mcp_server.list_board_producers.__doc__
    assert "时间线格" in SYSTEM_PROMPT
