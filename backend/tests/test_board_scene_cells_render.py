"""3D 场景格自己渲白模参考:内置产出者 `scene_render` 挂在场景格上,「渲染白模参考」工具格撤下画板。

此前一格场景格旁边还要放一格工具格,在工具格上挑场景、挑镜头、挑渲什么 —— 同一件事的两半。现在渲染是场景格
自己会做的事(和「剪一段」挂在视频 / 音频格上同一个样子),跑的是工作流那个节点的同一个执行器,产出新建成
场景格右边的几格。已有画板由迁移 `migrate-board-scene-cells-render-themselves` 改过来。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import Board
from tests.test_scene_workflow_nodes import LAYOUT
from tests.util import fresh_client, run_on_board


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _scene(ws: str, layout: dict | None = None) -> str:
    from app.domain.scene_types import SceneContent
    from app.domain.scenes import create_scene

    import copy

    content = copy.deepcopy(layout or LAYOUT)
    for one in content["objects"]:
        #: LAYOUT 的关键帧故意倒着写(那是给「节点负责排好序」的测试用的);直接建场景要先排好。
        one.get("track", []).sort(key=lambda frame: frame["time"])
    with SessionLocal() as db:
        return create_scene(db, ws, "教室", SceneContent.model_validate(content)).id


def _thumbnail(ws: str, tmp_path: Path) -> str:
    from PIL import Image

    from app.domain.assets.importer import register_file_asset

    path = tmp_path / "thumb.png"
    Image.new("RGB", (8, 8), "#888888").save(path)
    with SessionLocal() as db:
        return register_file_asset(db, workspace_id=ws, project_id=None, source_path=path, name="缩略图").id


def test_渲白模是挂在场景格上的内置产出者_工具格撤下画板() -> None:
    from app.domain.boards import producers
    from app.domain.boards.producer_ids import SLOT_PRODUCERS, derives_outputs, runs_from_draft
    from app.domain.scenes import REFERENCE_RENDERS
    from app.domain.workflows import NODE_TYPES

    client = fresh_client()
    with SessionLocal() as db:
        registry = {one.id: one for one in producers.list_producers(db, None)}
    render = registry["scene_render"]
    assert render.hosts == ("scene",) and render.effects == "none" and render.permission == "edit"
    assert "node:scene_render" not in registry, "工具格那一份不再在画板上"
    #: 工作流里照旧在。
    assert NODE_TYPES["scene_render"]["surfaces"] == ["workflow"]
    #: 新放下的场景格挂它;产出新建在右边(场景格的 asset_id 是缩略图,不是产出)。
    assert SLOT_PRODUCERS["scene"] == "scene_render"
    assert derives_outputs({"kind": "scene", "form": {"producer": "scene_render"}})
    assert runs_from_draft("scene_render") and not runs_from_draft("generate")
    #: 渲什么的取值就是节点那张表。
    assert set(producers.SceneRenderConfig.model_fields["render"].annotation.__args__) == set(REFERENCE_RENDERS)

    ws = _workspace(client)
    listed = client.get("/api/boards/producers", params={"workspace_id": ws}, headers={"Accept-Language": "zh"}).json()
    entry = next(one for one in listed if one["id"] == "scene_render")
    assert entry["hosts"] == ["scene"] and entry["runs_from_draft"] is True and entry["effects"] == "none"
    #: 字段就是节点声明的那几个(不抄一份),少了场景 —— 场景由那一格给。
    assert list(entry["config"]) == ["shot_id", "render", "project_id"]
    shot = entry["config"]["shot_id"]
    assert shot["options_from"] == "scene_shots" and shot["sole_option_default"] is True
    assert shot["depends_on"] == "scene_id" and shot["board_sources"] == []
    assert entry["config"]["render"]["options"] == list(REFERENCE_RENDERS)
    assert entry["config"]["render"]["option_labels"]["both"] == "静帧和运镜视频"
    assert "allow_custom" not in entry["config"]["render"], "画板上没有 {{…}},渲什么只在三种里挑"
    assert entry["config"]["project_id"]["advanced"] is True
    assert entry["output_kinds"] == ["image", "image", "video"]
    assert entry["board_description"] == "选一个镜头,渲出首尾帧或运镜视频"
    assert entry["board_group"] == "", "不进「添加 → 工具」"
    assert not any(one["id"] == "node:scene_render" for one in listed)


def test_新放下的场景格写明产出者_有缩略图也一样() -> None:
    from app.domain.boards import normalize_canvas

    canvas = normalize_canvas({"items": [
        {"id": "s1", "kind": "scene", "x": 0, "y": 0, "scene_id": "sc"},
        {"id": "s2", "kind": "scene", "x": 0, "y": 0, "scene_id": "sc", "asset_id": "thumb"},
    ], "edges": []})
    assert [item["form"] for item in canvas["items"]] == [{"producer": "scene_render"}] * 2
    assert canvas["items"][1]["asset_id"] == "thumb"


def _settled(client, board_id: str, ws: str, item_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        canvas = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]
        item = next(one for one in canvas["items"] if one["id"] == item_id)
        if (item.get("run") or {}).get("status") in ("succeeded", "failed", "cancelled"):
            return canvas
        time.sleep(0.1)
    raise AssertionError("场景格一直没渲完")


def test_在场景格上渲_首尾帧落成右边的图片格_场景格不动(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    scene_id = _scene(ws)
    thumb = _thumbnail(ws, tmp_path)
    scene = {"id": "s1", "kind": "scene", "x": 0, "y": 0, "width": 320, "height": 220, "scene_id": scene_id,
             "asset_id": thumb, "title": "教室"}
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [scene], "edges": []}})
    assert created.status_code == 200, created.text
    board_id = created.json()["id"]

    placed = run_on_board(client, board_id, ws, producer="scene_render", item_id="s1", kind="scene",
                          form={"config": {"render": "stills"}})
    assert placed.status_code == 200, placed.text
    host = next(one for one in placed.json()["canvas"]["items"] if one["id"] == "s1")
    assert host["run"]["status"] in ("queued", "running")
    #: 摆占位不清缩略图:它不是上一次的产出。
    assert host["asset_id"] == thumb and host["scene_id"] == scene_id
    job = client.get(f"/api/jobs/{host['run']['job_id']}").json()
    assert job["kind"] == "board_run", "和工具格同一种任务:计量、取消、归属都走它"

    canvas = _settled(client, board_id, ws, "s1")
    host = next(one for one in canvas["items"] if one["id"] == "s1")
    assert host["run"] == {"status": "succeeded"}, host
    assert host["asset_id"] == thumb and host["scene_id"] == scene_id and host["title"] == "教室"
    #: 表单就是下一次运行那一份,跑完不清。
    assert host["form"] == {"config": {"render": "stills"}, "producer": "scene_render"}
    targets = {edge["target"] for edge in canvas["edges"] if edge["source"] == "s1"}
    made = sorted((one for one in canvas["items"] if one["id"] in targets), key=lambda one: one["y"])
    #: 只落首帧和尾帧(镜头语言、跳过的模型是给工作流连线的);摆在场景格右边,一格一根线。
    assert [one["kind"] for one in made] == ["image", "image"]
    assert all(one["x"] > host["x"] + host["width"] for one in made)
    from app.db.models import Asset

    with SessionLocal() as db:
        assert all(db.get(Asset, one["asset_id"]).source == "graybox" for one in made)

    #: 再渲一次:新的一列,上一轮的留着。
    run_on_board(client, board_id, ws, producer="scene_render", item_id="s1", kind="scene",
                 form={"config": {"render": "stills"}})
    again = _settled(client, board_id, ws, "s1")
    assert {one["id"] for one in made} <= {one["id"] for one in again["items"]}
    assert len([edge for edge in again["edges"] if edge["source"] == "s1"]) == 4


def test_好几个镜头没挑_跑挂了说清楚_场景格留着() -> None:
    client = fresh_client()
    ws = _workspace(client)
    two = {**LAYOUT, "shots": [*LAYOUT["shots"], {"id": "shot-2", "name": "反打", "duration": 3, "camera_id": "cam-1"}]}
    scene_id = _scene(ws, two)
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [
        {"id": "s1", "kind": "scene", "x": 0, "y": 0, "scene_id": scene_id}], "edges": []}})
    board_id = created.json()["id"]
    placed = run_on_board(client, board_id, ws, producer="scene_render", item_id="s1", kind="scene", form={})
    assert placed.status_code == 200, placed.text
    canvas = _settled(client, board_id, ws, "s1")
    host = canvas["items"][0]
    assert host["run"]["status"] == "failed" and "反打" in host["run"]["error"]
    assert host["scene_id"] == scene_id and len(canvas["items"]) == 1

    #: 渲什么不在那三种里:表单校验就拒(画板上没有 {{…}})。
    refused = run_on_board(client, board_id, ws, producer="scene_render", item_id="s1", kind="scene",
                           form={"config": {"render": "{{x}}"}})
    assert refused.status_code == 422, refused.text
    #: 只能挂在场景格上。
    refused = run_on_board(client, board_id, ws, producer="scene_render", item_id="n1", kind="note", form={})
    assert refused.status_code == 400, refused.text


def test_智能体在场景格上写设置_替人点运行不开卡() -> None:
    from app.domain.boards import normalize_canvas
    from app.domain.boards.canvas import BoardDomainError
    from app.domain.boards.ops import apply_board_ops

    canvas = normalize_canvas({"items": [{"id": "s1", "kind": "scene", "x": 0, "y": 0, "scene_id": "sc"}], "edges": []})
    edited = apply_board_ops(canvas, [{"kind": "set_form", "item_id": "s1", "config": {"shot_id": "shot-1", "render": "both"}}])
    assert edited["items"][0]["form"] == {"config": {"shot_id": "shot-1", "render": "both"}, "producer": "scene_render"}
    try:
        apply_board_ops(canvas, [{"kind": "set_form", "item_id": "s1", "bindings": {"shot_id": [{"from": "n1"}]}}])
    except BoardDomainError as exc:
        assert exc.key == "boardErr_bindingFieldNotBindable"
    else:
        raise AssertionError("渲白模没有接上游的字段")

    client = fresh_client()
    ws = _workspace(client)
    scene_id = _scene(ws)
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [
        {"id": "s1", "kind": "scene", "x": 0, "y": 0, "scene_id": scene_id}], "edges": []}})
    board_id = created.json()["id"]
    from tests.test_board_agent_tools import _card, _settle_card

    refused = _card(client, ws, "edit_board", {"board_id": board_id, "operations": [
        {"kind": "set_form", "item_id": "s1", "config": {"render": "sideways"}}]})
    assert refused.status_code >= 400, "写不进这个产出者认不得的设置"
    card = _card(client, ws, "run_board_item", {"board_id": board_id, "item_id": "s1"})
    assert card.status_code == 200, card.text
    #: 本机渲染不花钱不出门:卡留痕,不等人点。
    done = _settle_card(client, card.json()["id"])
    assert done["status"] == "executed", done.get("error")
    assert done["decision_mode"] == "no-card" and done["result"]["item_id"] == "s1"
    canvas = _settled(client, board_id, ws, "s1")
    assert canvas["items"][0]["run"] == {"status": "succeeded"}


def _canvas(board_id: str) -> tuple[dict, int]:
    with SessionLocal() as db:
        board = db.get(Board, board_id)
        canvas = board.canvas
        return (json.loads(canvas) if isinstance(canvas, str) else canvas), board.revision


def _tool(item_id: str, config: dict, bindings: dict | None = None, **extra) -> dict:
    return {"id": item_id, "kind": "action", "x": 400, "y": 0, "width": 260, "height": 180,
            "form": {"config": config, "bindings": bindings or {}, "producer": "node:scene_render"}, **extra}


def test_迁移_工具格的设置搬到场景格上_没有场景格的改成便签() -> None:
    from app.db.migrations import _migrate_board_scene_cells_render_themselves, migration_plan
    from app.domain.boards import normalize_canvas

    assert "migrate-board-scene-cells-render-themselves" in {step.name for step in migration_plan().steps}

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟升级前落库的画布。
        board = Board(workspace_id=ws, name="旧板", revision=5, canvas={
            "items": [
                {"id": "sa", "kind": "scene", "x": 0, "y": 0, "scene_id": "scene-a", "asset_id": "thumb"},
                {"id": "sb", "kind": "scene", "x": 0, "y": 400, "scene_id": "scene-b"},
                {"id": "n1", "kind": "note", "x": -300, "y": 0, "text": "说明", "form": {"producer": "write"}},
                #: 接着场景格 sa:设置搬过去,工具格删掉,产出改从 sa 连出。
                _tool("r1", {"shot_id": "shot-2", "render": "both", "project_id": "{{x}}"},
                      {"scene_id": [{"from": "sa"}]}, run={"status": "succeeded"}),
                {"id": "r1-out-1", "kind": "image", "x": 800, "y": 0, "asset_id": "first"},
                {"id": "r1-out-2", "kind": "video", "x": 800, "y": 300, "asset_id": "clip"},
                #: 填的是 sb 的场景:同样搬过去(没有产出)。
                _tool("r2", {"scene_id": "scene-b", "render": "video"}),
                #: 又一格接着 sa、镜头不同:它的选择不能悄悄丢 —— 改成便签。
                _tool("r3", {"shot_id": "shot-9"}, {"scene_id": [{"from": "sa"}]}, title="反打那一镜"),
                #: 填的场景这张板上没有格子:改成便签。
                _tool("r4", {"scene_id": "elsewhere", "shot_id": "shot-1"}),
                {"id": "r4-out-1", "kind": "image", "x": 800, "y": 900, "asset_id": "old"},
                #: 别的工具格一个字不动。
                {"id": "t1", "kind": "action", "x": 400, "y": 1200,
                 "form": {"config": {}, "bindings": {"text": [{"from": "n1"}]}, "producer": "node:translate"}},
            ],
            "edges": [
                {"id": "e-sa-r1", "source": "sa", "target": "r1"},
                {"id": "r1->r1-out-1", "source": "r1", "target": "r1-out-1"},
                {"id": "r1->r1-out-2", "source": "r1", "target": "r1-out-2"},
                #: sa 本来就连着 r1-out-2(当参考):不再多一根。
                {"id": "e-sa-out2", "source": "sa", "target": "r1-out-2"},
                {"id": "e-n1-r1", "source": "n1", "target": "r1"},
                {"id": "e-sa-r3", "source": "sa", "target": "r3"},
                {"id": "r4->r4-out-1", "source": "r4", "target": "r4-out-1"},
                {"id": "e-n1-t1", "source": "n1", "target": "t1"},
            ],
        })
        #: 没有工具格、场景格也写明了产出者的板:一个字不动,版本号不动。
        untouched = Board(workspace_id=ws, name="新板", revision=2, canvas={"items": [
            {"id": "s", "kind": "scene", "x": 0, "y": 0, "scene_id": "scene-a", "form": {"producer": "scene_render"}},
        ], "edges": []})
        db.add_all([board, untouched])
        db.commit()
        board_id, untouched_id = board.id, untouched.id
        before = board.canvas

    _migrate_board_scene_cells_render_themselves()
    once, revision = _canvas(board_id)
    _migrate_board_scene_cells_render_themselves()
    assert _canvas(board_id) == (once, revision), "再跑一次不该再动(版本号也不该再涨)"

    items = {item["id"]: item for item in once["items"]}
    assert "r1" not in items and "r2" not in items
    assert items["sa"]["form"] == {"config": {"shot_id": "shot-2", "render": "both"}, "producer": "scene_render"}
    assert items["sa"]["asset_id"] == "thumb" and items["sa"]["scene_id"] == "scene-a"
    assert items["sb"]["form"] == {"config": {"render": "video"}, "producer": "scene_render"}
    for kept in ("r1-out-1", "r1-out-2", "r4-out-1", "n1", "t1"):
        assert items[kept] == next(one for one in before["items"] if one["id"] == kept), kept
    for gone, title in (("r3", "反打那一镜"), ("r4", None)):
        note = items[gone]
        assert note["kind"] == "note" and note["form"] == {"producer": "write"} and "run" not in note
        assert "3D 场景格" in note["text"] and "原来的设置" in note["text"]
        assert (note["x"], note["y"], note["width"], note["height"]) == (400, 0, 260, 180)
        assert note.get("title") == title
    assert '"shot-9"' in items["r3"]["text"]

    pairs = [(edge["source"], edge["target"]) for edge in once["edges"]]
    assert sorted(pairs) == sorted([
        ("sa", "r1-out-1"), ("sa", "r1-out-2"), ("sa", "r3"), ("r4", "r4-out-1"), ("n1", "t1"),
    ]), pairs
    assert len({edge["id"] for edge in once["edges"]}) == len(once["edges"])
    assert revision == 6, "升级那一刻还开着这张板的客户端要撞 409"
    assert _canvas(untouched_id)[1] == 2
    #: 迁完的画布照现在的规则存得下。
    normalize_canvas(once)
