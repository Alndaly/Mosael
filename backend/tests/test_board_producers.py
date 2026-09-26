"""画板上的产出者注册表(ADR 0021)。

画板上能产出东西的动作只有一个入口 —— `boards.producers.run`,路由只有一条 `POST /api/boards/{id}/run`。
这里钉住注册表本身:有哪几个、各自挂在哪、未知的怎么拒、表单上写明的产出者从哪来(新跑的一格、
智能体放下的一格、升级前的老画板)。
"""

from __future__ import annotations

import base64
import json
import shutil
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.boards import BoardDomainError
from tests.util import board_revision, fresh_client, run_on_board, second_client, wait_status


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _board(client, ws: str, items: list[dict]) -> str:
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": items, "edges": []}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_内置的产出者各自挂在该挂的格子上() -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import producers
    from app.domain.boards.producer_ids import BUILTIN_PRODUCER_IDS
    from app.domain.generation.resolution import KINDS

    fresh_client()
    with SessionLocal() as db:
        registry = producers.list_producers(db, None)
    by_id = {one.id: one for one in registry if not one.id.startswith("node:")}
    assert set(by_id) == {"generate", "speak", "trim", "write", "scene_render"}
    #: canvas 校验表单时认的那张名字表,和注册表是同一份。
    assert set(BUILTIN_PRODUCER_IDS) == set(by_id)
    #: 能挑来填空槽的是这几个(一种格子有两个时面板上给切换);截一段得先有一段素材。场景格永远「还能再渲」。
    assert {one for one in by_id if by_id[one].fills_empty_slot} == {"generate", "speak", "write", "scene_render"}

    #: 生成挂在哪由生成目录说了算,不在画板这边另写一份。
    assert by_id["generate"].hosts == tuple(KINDS)
    assert by_id["write"].hosts == ("note",)
    assert by_id["speak"].hosts == ("audio",)
    assert set(by_id["trim"].hosts) == {"video", "audio"}
    assert by_id["scene_render"].hosts == ("scene",)

    assert {one: by_id[one].permission for one in by_id} == {
        "generate": "edit", "speak": "edit", "trim": "edit", "write": "ai", "scene_render": "edit",
    }
    #: 智能体替人跑时要不要确认卡看这个:本机截取、本机渲白模既不花钱也不出门。
    assert {one for one in by_id if by_id[one].effects == "none"} == {"trim", "scene_render"}
    assert all(one.effects in ("none", "paid", "external") for one in by_id.values())


def test_每个产出者的表单都不收非有限的数() -> None:
    """表单在领域里校验,不经过接口层的 ApiModel —— 同一条规矩要在这里再钉一次。"""
    from app.domain.boards import producers

    from app.core.db import SessionLocal

    fresh_client()
    with SessionLocal() as db:
        registry = producers.list_producers(db, None)
    leaky = [one.id for one in registry if one.form.model_config.get("allow_inf_nan") is not False]
    assert not leaky, f"这些产出者的表单放进了 NaN / Infinity:{leaky}"


def test_新放下的一格挂哪个产出者() -> None:
    from app.domain.boards.producer_ids import SLOT_PRODUCERS

    assert SLOT_PRODUCERS == {"note": "write", "image": "generate", "video": "generate", "audio": "speak",
                              "scene": "scene_render"}
    assert all(SLOT_PRODUCERS.get(kind) is None for kind in ("frame", "document"))


def test_空槽的缺省产出者和注册表对得上() -> None:
    """棘轮:producer_ids.SLOT_PRODUCERS(画布那一侧补齐用的无依赖表)和注册表是同一件事。

    · 表里的每一个都挂得了那种格子、能挑来填空槽 —— 否则补上去的产出者面板挂不上、跑不了;
    · 能填空槽的产出者挂得了的每一种格子都在表里 —— 生成目录多认一种格子,这张表得跟着多一行,
      否则那种新格子放下去什么面板都没有。
    """
    from app.core.db import SessionLocal
    from app.domain.boards import producers
    from app.domain.boards.canvas import ITEM_KINDS
    from app.domain.boards.producer_ids import SLOT_PRODUCERS

    fresh_client()
    with SessionLocal() as db:
        by_id = {one.id: one for one in producers.list_producers(db, None)}
    assert set(SLOT_PRODUCERS) <= set(ITEM_KINDS)
    for kind, producer in SLOT_PRODUCERS.items():
        assert kind in by_id[producer].hosts, f"{producer} 挂不了 {kind}"
        assert by_id[producer].fills_empty_slot, f"{producer} 不能填空槽,却是 {kind} 的缺省"
    fillable = {kind for one in by_id.values() if one.fills_empty_slot for kind in one.hosts}
    assert fillable <= set(SLOT_PRODUCERS), f"这几种格子能被填,却没有缺省产出者:{fillable - set(SLOT_PRODUCERS)}"


def test_写入之后每一个能产出的空槽都写明了产出者() -> None:
    """棘轮:不管哪条路造出来的格子(画布的「添加」、智能体、3D 场景页、脚本),过了 normalize 之后,
    能产出、还没产出的每一格都写明了产出者,而且是挂得了它的那一个;有了产出的媒体格、不产出的种类不补。"""
    from app.core.db import SessionLocal
    from app.domain.boards import normalize_canvas, producers
    from app.domain.boards.canvas import ITEM_KINDS
    from app.domain.boards.producer_ids import DERIVED_BUILTINS, SLOT_PRODUCERS

    fresh_client()
    with SessionLocal() as db:
        by_id = {one.id: one for one in producers.list_producers(db, None)}
    trim = {"asset_id": "src", "start": 0.0, "end": 1.0, "mute": False}
    shapes = {
        "bare": {},
        "draft": {"form": {"prompt": "黄昏的海边", "source_assets": [{"asset_id": "a", "role": "reference_image"}]}},
        "made": {"asset_id": "a1"},
        "named": {"form": {"producer": "trim", "trim": trim}},
    }
    items = []
    for kind in ITEM_KINDS:
        for name, extra in shapes.items():
            item = {"id": f"{kind}-{name}", "kind": kind, "x": 0, "y": 0, **extra}
            if kind == "scene":
                item["scene_id"] = "s1"
            if kind == "frame" or (kind == "note" and name == "named"):
                item.pop("form", None)
            items.append(item)
    once = normalize_canvas({"items": items, "edges": []})
    assert normalize_canvas(once) == once, "再过一遍不该再变"

    written = {item["id"] for item in items if (item.get("form") or {}).get("producer")}
    for item in once["items"]:
        producer = (item.get("form") or {}).get("producer")
        if item["id"] in written:
            continue
        #: 产出派生到右边的格子(3D 场景格)的 asset_id 是缩略图,不是产出:有它照样挂。
        producible = item["kind"] in SLOT_PRODUCERS and (
            item["kind"] == "note" or SLOT_PRODUCERS[item["kind"]] in DERIVED_BUILTINS or not item.get("asset_id"))
        if not producible:
            assert producer is None, f"{item['id']} 不是能产出的空槽,不该被补上产出者"
            continue
        assert producer is not None, f"{item['id']} 是能产出的空槽,却没写明产出者"
        assert item["kind"] in by_id[producer].hosts, f"{item['id']} 挂着 {producer},它挂不了 {item['kind']}"
    forms = {item["id"]: item.get("form") for item in once["items"]}
    #: 草稿原样留着,产出者补在最后(和摆占位时写的位置一致)。
    assert list(forms["video-draft"]) == ["prompt", "source_assets", "producer"]
    assert forms["video-draft"]["producer"] == "generate"
    assert forms["audio-bare"] == {"producer": "speak"}
    assert forms["image-named"]["producer"] == "trim", "写明了的不动"
    assert forms["image-made"] is None


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
    """算子自己不写缺省产出者 —— 落库那一道(normalize)补,和别的新建路是同一条规则。"""
    from app.domain.boards import normalize_canvas
    from app.domain.boards.ops import apply_board_ops

    canvas = normalize_canvas(apply_board_ops({"items": [], "edges": []}, [
        {"kind": "add_item", "type": "note", "item_id": "n", "text": "开场"},
        {"kind": "add_item", "type": "image", "item_id": "i"},
        {"kind": "add_item", "type": "video", "item_id": "v", "asset_id": "clip-1"},
        {"kind": "add_item", "type": "frame", "item_id": "f"},
    ]))
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


def test_升级之后新建却没写明产出者的空槽_迁移补上() -> None:
    """`migrate-board-empty-slots-name-their-producer`:3D 场景页绕开新建格子的缺省,生成那一格带着提示词和
    参考却没写产出者 —— 选中了什么面板都不挂。库里已经存着、之后没再存过的板由这一步补,规则和 normalize 同一条。"""
    from app.core.db import SessionLocal
    from app.db.migrations import _migrate_board_empty_slots_name_their_producer, migration_plan
    from app.db.models import Board
    from app.domain.boards import normalize_canvas

    assert "migrate-board-empty-slots-name-their-producer" in {step.name for step in migration_plan().steps}

    client = fresh_client()
    ws = _workspace(client)
    trim = {"asset_id": "src", "start": 1.0, "end": 2.0, "mute": False}
    draft = {"prompt": "镜头缓缓推进", "source_assets": [{"asset_id": "f1", "role": "first_frame"}],
             "parameters": {"aspect_ratio": "16:9"}}
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟 3D 场景页此前建出来的画板。
        board = Board(workspace_id=ws, name="场景 · 镜头 1", revision=1, canvas={"items": [
            {"id": "scene", "kind": "scene", "x": -440, "y": 0, "scene_id": "s1", "asset_id": "thumb"},
            {"id": "first", "kind": "image", "x": 0, "y": 0, "asset_id": "f1"},
            {"id": "gen", "kind": "video", "x": 460, "y": 100, "form": draft},
            {"id": "bare", "kind": "audio", "x": 0, "y": 0},
            {"id": "note", "kind": "note", "x": 0, "y": 0, "text": "旁白"},
            {"id": "cut", "kind": "audio", "x": 0, "y": 0, "form": {"trim": trim, "producer": "trim"}},
            {"id": "named", "kind": "audio", "x": 0, "y": 0, "form": {"producer": "generate"}},
        ], "edges": [{"id": "e", "source": "first", "target": "gen"}]})
        untouched = Board(workspace_id=ws, name="好的板", revision=2, canvas={"items": [
            {"id": "pic", "kind": "image", "x": 0, "y": 0, "asset_id": "a1"},
            {"id": "n", "kind": "note", "x": 0, "y": 0, "form": {"producer": "write"}},
        ], "edges": []})
        db.add_all([board, untouched])
        db.commit()
        board_id, untouched_id = board.id, untouched.id

    _migrate_board_empty_slots_name_their_producer()
    once, revision = _canvas(board_id)
    _migrate_board_empty_slots_name_their_producer()
    assert _canvas(board_id) == (once, revision), "再跑一次不该再动(版本号也不该再涨)"

    forms = {item["id"]: item.get("form") for item in once["items"]}
    assert forms == {
        "scene": None,
        "first": None,
        "gen": {**draft, "producer": "generate"},
        "bare": {"producer": "speak"},
        "note": {"producer": "write"},
        "cut": {"trim": trim, "producer": "trim"},
        "named": {"producer": "generate"},
    }
    assert revision == 2, "改到的板版本号 +1:开着它的旧快照要撞 409"
    assert _canvas(untouched_id)[1] == 2, "没改到的板版本号不动"
    #: 迁移和 normalize 是同一条规则:迁完的画布再过 normalize 一个字都不变。3D 场景格除外 —— 它挂渲白模是
    #: 后来的规则,由后来的那一步(migrate-board-scene-cells-render-themselves)补,这一步的身体已经冻住了。
    def forms(canvas: dict) -> list:
        return [item.get("form") for item in canvas["items"] if item["kind"] != "scene"]

    assert forms(normalize_canvas(once)) == forms(once)


# ── 节点产出者:内容格的能力、空格子上的生成器 ─────────────────────────────────
#
# 插件工具、声明了能上画板的内置节点,都是 `node:<节点类型>` 产出者。吃画板内容的是内容格的**能力**:
# 宿主的内容就是输入,产出新建成右边的几格并连上线,设置存在宿主的 `form.abilities` 上;凭空出素材的是
# 空格子的**填法**:产出填进那一格,多出来的新建在右边。失败留下设置和原因;停止真的停下插件进程;
# 共享画板上谁点运行用谁自己的连接(ADR 0025 修订「能力住在内容格上」)。

#: 1×1 的 PNG —— 插件交出的「文件」,素材库按图片收。
_PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)).decode()

PLUGIN_ENTRY = f"""
import base64, json, os, sys, time
request = json.loads(sys.stdin.read())
tool, args = request["tool"], request.get("input") or {{}}
if tool == "shout":
    print(json.dumps({{"ok": True, "output": {{"summary": str(args.get("text", "")).upper(), "count": 3}}}}))
elif tool == "paint":
    with open(os.path.join(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"], "pic.png"), "wb") as out:
        out.write(base64.b64decode("{_PNG}"))
    print(json.dumps({{"ok": True, "output": {{"caption": "画好了", "artifact": {{"path": "pic.png"}}}}}}))
elif tool == "many":
    print(json.dumps({{"ok": True, "output": {{"lines": [f"第{{i}}条" for i in range(15)]}}}}))
elif tool == "boom":
    print(json.dumps({{"ok": False, "error": "上游挂了"}}))
elif tool == "sleep":
    time.sleep(120)
    print(json.dumps({{"ok": True, "output": {{}}}}))
"""

#: 工具的声明。shout 吃一段字、写明了输出(summary 是文字、count 不上画板)—— 便签 / 文档的能力;
#: paint 按提示词交出一张图 —— 图片空格子的一种填法;many 的输出没写类型(按值猜);secret 只给宿主调。
PLUGIN_TOOLS = [
    {
        "name": "shout",
        "read_only": True,
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        "node": {"outputs": ["summary", "count"], "output_types": {"summary": "text", "count": "number"},
                 "board_outputs": ["summary"]},
    },
    {
        "name": "paint",
        #: `extra` 是一份原始 JSON(选填):工作流里有编辑器,画板的表单上不出现。
        "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}, "extra": {"type": "object"}}},
        #: `output_media`:交出的那份是一张图 —— 它挂在图片的空格子上。
        "node": {"outputs": ["caption", "asset_id"], "output_types": {"caption": "text"}, "output_media": {"asset_id": "image"}},
    },
    #: 可能交出一个文件(所以是内容变换),这回交的是一列没声明类型的字:按值猜 —— 一个列表落成好几格。
    {"name": "many", "input_schema": {"type": "object", "properties": {}}, "node": {"outputs": ["lines", "asset_id"]}},
    {"name": "boom", "input_schema": {"type": "object", "properties": {}}, "node": {"outputs": ["asset_id"]}},
    {"name": "sleep", "input_schema": {"type": "object", "properties": {}}, "node": {"outputs": ["asset_id"]}},
    {"name": "secret", "input_schema": {"type": "object", "properties": {}}},
    #: 下面四个不是内容变换,不上画板(工作流里照样用):
    #: 列清单(缺省的一个 output,类型不明)、看状态(文字没点名落板,是摘要)、
    #: 装环境(点名落板的只有文字,又不吃任何内容 —— 是一份报告)、必填一份 JSON(画板上填不了)。
    {"name": "listing", "read_only": True,
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "status", "read_only": True, "input_schema": {"type": "object", "properties": {}},
     "node": {"outputs": ["summary"], "output_types": {"summary": "text"}}},
    {"name": "setup", "input_schema": {"type": "object", "properties": {"reinstall": {"type": "boolean"}}},
     "node": {"outputs": ["summary"], "output_types": {"summary": "text"}, "board_outputs": ["summary"]}},
    {"name": "explain",
     "input_schema": {"type": "object", "properties": {"steps": {"type": "array"}}, "required": ["steps"]},
     "node": {"outputs": ["asset_id"]}},
]

#: 上面这份清单里能上画板的那几个(内容变换)。
BOARD_TOOLS = ("shout", "paint", "many", "boom", "sleep")

SHOUT = "node:plugin.dev.test.boardtools.shout"


def _install_plugin(root: Path, package_id: str = "dev.test.boardtools") -> Path:
    """装一个进程插件的包(还没有任何连接)。"""
    from app.core.db import SessionLocal
    from app.db.models import PluginPackage

    plugin_dir = root / package_id
    shutil.rmtree(plugin_dir, ignore_errors=True)
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(PLUGIN_ENTRY), encoding="utf-8")
    manifest = {
        "id": package_id, "name": "画板工具箱", "version": "0.1.0",
        "runtime": {"kind": "process", "entry": "main.py"},
        "tools": {"expose": "all", "declare": PLUGIN_TOOLS, "overrides": {"secret": {"internal": True}}},
        "_path": str(plugin_dir),
    }
    (plugin_dir / "mosael.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=package_id, name="画板工具箱", version="0.1.0", manifest=manifest))
        db.commit()
    return plugin_dir


def _connect(owner_id: str, package_id: str = "dev.test.boardtools", name: str = "我的工具箱") -> str:
    """给 `owner_id` 接一条连接。"""
    from app.core.db import SessionLocal
    from app.db.models import PluginInstance

    from app.domain.plugins.tools import refresh_tools

    with SessionLocal() as db:
        instance = PluginInstance(package_id=package_id, name=name, enabled=True, owner_user_id=owner_id)
        db.add(instance)
        db.commit()
        #: 和插件页新建一条连接时一样:按清单把工具的开关记下来(expose: all → 全开)。
        refresh_tools(db, instance, notify=False)
        return instance.id


def _me(client) -> str:
    return client.get("/api/auth/me").json()["id"]


def _host_board(client, ws: str, *, items: list[dict] | None = None, edges: list[dict] | None = None,
                abilities: dict | None = None, text: str = "hello") -> str:
    """一张板,宿主是便签 `a1`(`abilities` 是它上面存着的能力设置)。"""
    host = {"id": "a1", "kind": "note", "x": 100, "y": 50, "width": 220, "height": 140, "text": text,
            "form": {**({"abilities": abilities} if abilities else {}), "producer": "write"}}
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {
        "items": [*(items or []), host], "edges": edges or []}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _slot_board(client, ws: str, producer: str, *, kind: str = "image", config: dict | None = None) -> str:
    """一张板,空格子 `a1` 挂着生成器 `producer`。"""
    slot = {"id": "a1", "kind": kind, "x": 100, "y": 50, "width": 260, "height": 180,
            "form": {"config": config or {}, "bindings": {}, "producer": producer}}
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [slot], "edges": []}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _run(client, board_id: str, ws: str, producer: str, *, kind: str = "note", config: dict | None = None,
         bindings: dict | None = None):
    """在 `a1` 上跑 `producer`(能力或生成器,由注册表判)。"""
    return run_on_board(client, board_id, ws, producer=producer, item_id="a1", kind=kind, x=100, y=50,
                        form={"config": config or {}, "bindings": bindings or {}})


def _settled(client, board_id: str, ws: str, timeout: float = 20.0) -> dict:
    """等 `a1` 那一轮落终态(回执落回画布),返回那时的画布。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        canvas = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]
        host = next(one for one in canvas["items"] if one["id"] == "a1")
        if (host.get("run") or {}).get("status") in ("succeeded", "failed", "cancelled"):
            return canvas
        time.sleep(0.1)
    raise AssertionError("a1 一直没跑完")


def _derived(canvas: dict) -> list[dict]:
    """`a1` 派生出去的那几格(id 是 `a1-out-…`),按摆放的先后(从左往右、从上往下)。"""
    return sorted((one for one in canvas["items"] if one["id"].startswith("a1-out-")), key=lambda one: (one["x"], one["y"]))


#: 画板上的内置变换:只有内容变换(ADR 0021 修订),各是它吃的那几种格子的能力。
#: 渲白模不在这里:画板上它是 3D 场景格自己会做的事(内置产出者 scene_render,见 test_board_scene_cells_render)。
BOARD_NODES = {
    "transcribe_asset": ("video", "audio"),
    "translate": ("note", "document"),
    "video_to_gif": ("video",),
    "separate_audio": ("video", "audio"),
    "denoise_audio": ("video", "audio"),
}


def test_画板上的内置变换从节点声明里读_是它吃的那几种格子的能力() -> None:
    """RATCHET:`surfaces` 声明和注册表是同一件事,清单只在 NODE_TYPES 里写一次,画板不另列;
    **声明了画板的节点必须是内容变换** —— 流程控制、数据处理、知识库的节点声明了也不算数,这里当场报出来。
    挂在哪也从声明推:吃内容的字段收哪几种格子,它就是那几种格子的能力(ADR 0025 修订)。"""
    from app.core.db import SessionLocal
    from app.core.i18n import MESSAGES
    from app.domain.boards import producers
    from app.domain.boards.transforms import ABILITY, BOARD_GROUPS, content_transform_gap
    from app.domain.workflows import NODE_TYPES, WIRING_CATEGORIES
    from app.domain.workflows.executors import get_executor

    declared = {name for name, spec in NODE_TYPES.items() if "board" in (spec.get("surfaces") or ())}
    assert declared == set(BOARD_NODES)
    #: 决定 3:和内置写字/生成/念重复的、副作用大的、流程控制类不上画板;
    #: 修订:数据搬运和知识库查询也不上(调用工作流、HTTP 请求、模板、JSON 提取、文本处理、检索笔记)。
    for kept_off in ("llm", "ai_generate", "synthesize_speech", "publish", "timeline_append", "start", "output",
                     "condition", "subgraph", "loop_foreach", "code", "delay", "call_workflow", "http_request",
                     "template", "json_extract", "text_transform", "note_search"):
        assert "board" not in (NODE_TYPES[kept_off].get("surfaces") or ()), kept_off
    for name, spec in NODE_TYPES.items():
        assert set(spec.get("surfaces") or ()) <= {"workflow", "board"}, name
        if "board" in (spec.get("surfaces") or ()):
            assert spec["category"] not in WIRING_CATEGORIES, f"{name} 是流程 / 数据 / 知识库节点,不该声明画板"
            assert content_transform_gap(spec) is None, f"{name} 声明了画板却不是内容变换:{content_transform_gap(spec)}"
            assert get_executor(name) is not None, name
            assert set(spec.get("board_outputs") or spec["outputs"]) <= set(spec["outputs"]), name
            #: 按吃什么内容归的组、给创作者看的一句话:内置的都写明,不靠推。
            assert spec.get("board_group") in BOARD_GROUPS, name
            assert spec.get("board_description") in MESSAGES, name
        else:
            for board_only in ("board_outputs", "board_group", "board_description"):
                assert board_only not in spec, f"{name} 没上画板却声明了 {board_only}"

    fresh_client()
    with SessionLocal() as db:
        registry = {one.id: one for one in producers.list_producers(db, None)}
    nodes = {one for one in registry if one.startswith("node:")}
    assert nodes == {f"node:{name}" for name in BOARD_NODES}
    assert {one: registry[one].hosts for one in nodes} == {f"node:{name}": hosts for name, hosts in BOARD_NODES.items()}
    assert all(registry[one].role == ABILITY and not registry[one].fills_empty_slot for one in nodes)
    #: 这几个都在本机做完(对外发请求、调别的流程的那两个已经不在画板上了)。
    assert all(registry[one].effects == "none" for one in nodes)


def test_声明了画板的流程节点注册表也不收_跑的时候说清楚(monkeypatch) -> None:
    """规矩是注册表的一道门,不只是棘轮:哪天有人给 HTTP 请求写回 `surfaces: ["board"]`,画板上也不会多出它;
    画布上存着的那一项点运行,说清楚这件事归工作流。"""
    from app.core.db import SessionLocal
    from app.domain.boards import producers
    from app.domain.workflows import NODE_TYPES

    monkeypatch.setitem(NODE_TYPES, "http_request", {**NODE_TYPES["http_request"], "surfaces": ["workflow", "board"],
                                                     "board_outputs": ["text"]})
    client = fresh_client()
    with SessionLocal() as db:
        assert "node:http_request" not in {one.id for one in producers.list_producers(db, None)}

    ws = _workspace(client)
    for gone in ("node:http_request", "node:text_transform", "node:call_workflow"):
        board_id = _host_board(client, ws, abilities={gone: {"config": {}}})
        refused = _run(client, board_id, ws, gone)
        assert refused.status_code == 400, refused.text
        assert "工作流" in refused.json()["detail"], refused.json()["detail"]


def test_内容变换的规矩() -> None:
    """一条规矩管内置节点和插件工具(boards.transforms.content_transform_gap):"""
    from app.domain.boards.transforms import board_group, content_transform_gap
    from app.domain.plugins.nodes import node_meta

    def tool(**declared) -> dict:
        return node_meta({"name": "t", **declared})

    text_in = {"type": "object", "properties": {"text": {"type": "string"}}}
    #: 吃文字、交出点名落板的文字:内容变换(翻译、改写这一类)。
    assert content_transform_gap(tool(input_schema=text_in, node={
        "outputs": ["text", "count"], "output_types": {"text": "text", "count": "number"}, "board_outputs": ["text"]})) is None
    #: 文字只有类型、没点名落板:不算内容(列清单、看状态的 summary 就是这样)。
    assert content_transform_gap(tool(input_schema=text_in, node={
        "outputs": ["summary"], "output_types": {"summary": "text"}})) == "no_content_output"
    #: 缺省的一个 output(类型不明)不算内容。
    assert content_transform_gap(tool(input_schema=text_in)) == "no_content_output"
    #: 点名的只有 JSON 也不算。
    assert content_transform_gap(tool(input_schema=text_in, node={
        "outputs": ["tags"], "output_types": {"tags": "json"}, "board_outputs": ["tags"]})) == "no_content_output"
    #: 不吃内容、只交出文字:是一份报告。
    assert content_transform_gap(tool(node={
        "outputs": ["summary"], "output_types": {"summary": "text"}, "board_outputs": ["summary"]})) == "no_content_input"
    #: 不吃内容、交出素材:凭空产出(提示词出图、按参数出讲解视频)。
    made = tool(input_schema={"type": "object", "properties": {"style": {"type": "string"}}},
                node={"outputs": ["asset_id", "summary"], "output_types": {"asset_id": "asset"}, "board_outputs": ["asset_id"]})
    assert content_transform_gap(made) is None and board_group(made) == "new"
    #: 按另一个系统里的编号取回(必填):创作者在画板上填不出一个 fs_id —— 不是内容变换。
    fetched = {"outputs": ["asset_id"], "output_types": {"asset_id": "asset"}}
    by_id = tool(input_schema={"type": "object", "properties": {"fs_id": {"type": "string", "format": "external_id"}},
                               "required": ["fs_id"]}, node=fetched)
    assert by_id["config"]["fs_id"]["data_type"] == "external_id"
    assert content_transform_gap(by_id) == "external_id"
    #: 编号选填、也不吃画板内容(不给任务号就取最近几次):交出的素材还是从外面取回来的,不是做出来的。
    recent = tool(input_schema={"type": "object", "properties": {
        "prompt_id": {"type": "string", "format": "external_id"}, "last": {"type": "integer"}}}, node=fetched)
    assert content_transform_gap(recent) == "external_id"
    #: 编号不接上游格子(便签上的字不是任务号),画板表单上也不出现。
    from app.domain.boards.tools import binding_sink
    from app.domain.boards.transforms import board_config_view

    assert binding_sink("prompt_id", recent["config"]["prompt_id"]) is None
    assert "prompt_id" not in board_config_view(recent["config"]) and "last" in board_config_view(recent["config"])
    #: 吃画板上的一张图、编号选填(比如「接着这个任务」):还是一个内容变换,编号在画板上不摆。
    reusing = tool(input_schema={"type": "object", "properties": {
        "image": {"type": "string", "format": "asset", "x-media": "image"},
        "prompt_id": {"type": "string", "format": "external_id"}}}, node=fetched)
    assert content_transform_gap(reusing) is None
    #: 吃一张图、交出一张图:归「处理图片」。
    picture = {"type": "object", "properties": {"image": {"type": "string", "format": "asset", "x-media": "image"}}}
    upscale = tool(input_schema=picture, node={"outputs": ["asset_id"]})
    assert content_transform_gap(upscale) is None and board_group(upscale) == "image"
    #: 吃素材、交出的是链接:上传 / 导出这类不上画板。
    upload = tool(input_schema={"type": "object", "properties": {"asset_id": {"type": "string", "format": "asset"}}},
                  node={"outputs": ["url", "key"]})
    assert content_transform_gap(upload) == "no_content_output"
    #: 必填一份 JSON:画板的表单上填不了。
    assert content_transform_gap(tool(input_schema={"type": "object", "properties": {"steps": {"type": "array"}},
                                                    "required": ["steps"]}, node={"outputs": ["asset_id"]})) == "needs_wiring"
    #: 流程 / 数据 / 知识库分组:不管输出是什么。
    assert content_transform_gap({**upscale, "category": "wfCat_data"}) == "wiring"


def test_随包的插件工具_哪些上画板() -> None:
    """对着仓库里的清单:出片的上画板;列清单、看状态、上传、装环境、按编号取回 / 导入的不上。"""
    from app.domain.boards.transforms import SLOT, board_role, is_content_transform
    from app.domain.plugins.nodes import node_meta

    root = Path(__file__).resolve().parents[2] / "plugins"
    eligible: dict[str, dict] = {}
    for path in sorted(root.glob("*/*/mosael.plugin.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        tools = manifest.get("tools") or {}
        for declared in tools.get("declare") or []:
            meta = node_meta(declared)
            if not declared.get("internal") and is_content_transform(meta):
                eligible[f"{manifest['id']}.{declared['name']}"] = meta
    for name in ("dev.mosael.manim.manim_still", "dev.mosael.remotion.remotion_animation"):
        assert name in eligible, name
        #: 按参数出一段动画 / 一张图:不吃画板内容 —— 是那种素材的空格子的一种填法。
        assert board_role(eligible[name]) == SLOT, name
    for name in ("dev.mosael.baidu-pan.pan_list", "dev.mosael.baidu-pan.pan_search", "dev.mosael.baidu-pan.pan_upload",
                 "dev.mosael.comfyui.server_status", "dev.mosael.comfyui.list_workflows", "dev.mosael.comfyui.list_models",
                 "dev.mosael.comfyui.interrupt", "dev.mosael.comfyui.clear_queue", "dev.mosael.comfyui.free_memory",
                 "dev.mosael.object-storage.storage_upload", "dev.mosael.object-storage.storage_list",
                 "dev.mosael.object-storage.storage_presign", "dev.mosael.manim.manim_setup",
                 "dev.mosael.remotion.remotion_setup",
                 #: 必填一串结构化的步骤 / 小节(JSON):画板的表单上填不了,在工作流或对话里用。
                 "dev.mosael.manim.manim_explainer", "dev.mosael.remotion.remotion_explainer",
                 #: 按另一个系统里的编号取回(任务号、fs_id、对象路径):是导入,不是内容变换 —— 工作流和对话里用。
                 "dev.mosael.comfyui.import_outputs", "dev.mosael.baidu-pan.pan_import",
                 "dev.mosael.object-storage.storage_fetch"):
        assert name not in eligible, name


def test_画板表单只摆创作者看得懂的参数(tmp_path) -> None:
    """参数规矩:节点产出者的表单里没有映射、原始 JSON、代码,没有 `{{…}}` 引用写法;说明是画板那一句。
    接口给的就是这一份 —— 界面和智能体(list_board_producers)看到的一样。"""
    from app.domain.boards.transforms import BOARD_GROUPS, OUTPUT_KINDS

    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    listed = client.get("/api/boards/producers", params={"workspace_id": ws}, headers={"Accept-Language": "zh"})
    assert listed.status_code == 200, listed.text
    tools = [one for one in listed.json() if one["id"].startswith("node:")]
    assert tools
    for entry in tools:
        for key, spec in entry["config"].items():
            assert spec.get("type") not in ("template", "object", "code", "graph"), (entry["id"], key, spec)
            assert spec.get("data_type") != "json", (entry["id"], key)
            assert spec.get("editor") not in ("map", "json"), (entry["id"], key)
            assert "{{" not in str(spec.get("description") or ""), (entry["id"], key)
        assert entry["board_group"] in BOARD_GROUPS and entry["board_group_label"], entry["id"]
        assert entry["board_description"] and "{{" not in entry["board_description"], entry["id"]
    by_id = {one["id"]: one for one in tools}
    #: 模板字段在画板上就是一段字;原始 JSON 的字段不出现;说明是画板那一句。
    assert by_id["node:translate"]["config"]["text"]["type"] == "text"
    assert "extra" not in by_id["node:plugin.dev.test.boardtools.paint"]["config"]
    assert by_id["node:video_to_gif"]["board_description"] == "把一段视频做成 GIF 动图"
    #: 跑一次长出什么(output_kinds,ADR 0025):只算落板的内容,不是节点的全部输出(源素材 id、引擎名不算)。
    #: GIF 是一张图,不是视频 —— 声明说了算,不按工具吃什么猜。
    assert by_id["node:video_to_gif"]["output_kinds"] == ["image"]
    assert by_id["node:separate_audio"]["output_kinds"] == ["audio", "audio"]
    assert by_id["node:translate"]["output_kinds"] == ["note"]
    assert all(one["output_kinds"] and set(one["output_kinds"]) <= set(OUTPUT_KINDS) for one in tools)
    #: 插件工具在 node 块里声明 output_media;没声明、又说不清吃哪种素材的,是 asset。
    assert by_id["node:plugin.dev.test.boardtools.paint"]["output_kinds"] == ["image"]
    assert by_id["node:plugin.dev.test.boardtools.many"]["output_kinds"] == ["asset"]
    assert by_id["node:translate"]["board_group"] == "text" and by_id["node:translate"]["board_group_label"] == "处理文字"
    assert by_id["node:plugin.dev.test.boardtools.paint"]["board_group"] == "new"
    assert by_id["node:plugin.dev.test.boardtools.shout"]["board_group"] == "text"
    #: 能力说清楚挂在哪、宿主的内容填进哪个字段;生成器挂在它产出的那种素材的空格子上。
    assert by_id["node:translate"]["role"] == "ability" and by_id["node:translate"]["host_fields"] == {
        "note": "text", "document": "text"}
    assert by_id["node:video_to_gif"]["host_fields"] == {"video": "asset_id"}
    paint = by_id["node:plugin.dev.test.boardtools.paint"]
    assert paint["role"] == "slot" and paint["hosts"] == ["image"] and paint["host_fields"] == {}
    assert paint["fills_empty_slot"] is True
    #: 说不清产出哪种素材的生成器:三种媒体的空格子都能挑它。
    assert by_id["node:plugin.dev.test.boardtools.many"]["hosts"] == ["image", "video", "audio"]
    #: 内置的没有分组;顺序是注册表的:内置的、内置节点、插件工具(操作条按它排)。
    everyone = [one["id"] for one in listed.json()]
    assert all(one["board_group"] == "" for one in listed.json() if not one["id"].startswith("node:"))
    first_plugin = next(index for index, one in enumerate(everyone) if one.startswith("node:plugin."))
    assert all(not one.startswith("node:") or one.startswith("node:plugin.") for one in everyone[first_plugin:])


def test_插件工具只列执行者自己的连接_跳过只给宿主调的(tmp_path) -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import producers

    client = fresh_client()
    me = _me(client)
    mate = second_client("mate")
    other = _me(mate)
    _install_plugin(tmp_path)
    _install_plugin(tmp_path, "dev.test.othertools")
    _connect(me)
    _connect(other, "dev.test.othertools", name="别人的")

    with SessionLocal() as db:
        mine = {one.id: one for one in producers.list_producers(db, me)}
        theirs = {one.id for one in producers.list_producers(db, other)}
    tools = {one for one in mine if one.startswith("node:plugin.")}
    #: 只有内容变换:列清单、看状态、装环境、必填 JSON 的那几个不在(工作流里照样用)。
    assert tools == {f"node:plugin.dev.test.boardtools.{name}" for name in BOARD_TOOLS}
    #: 只读的不花钱不出门,别的按保守那边算。
    assert mine[SHOUT].effects == "none"
    assert mine["node:plugin.dev.test.boardtools.paint"].effects == "external"
    assert not any(one.startswith("node:plugin.dev.test.boardtools.") for one in theirs), "别人的连接不该出现在我的工具里"
    assert "node:plugin.dev.test.othertools.shout" in theirs

    #: 接口给界面的那一份:节点描述(和工作流节点面板同一份)+ 画板的几样;字段带「能接哪几种上游」。
    ws = _workspace(client)
    listed = client.get("/api/boards/producers", params={"workspace_id": ws})
    assert listed.status_code == 200, listed.text
    by_id = {one["id"]: one for one in listed.json()}
    assert {"generate", "write", "speak", "trim"} <= set(by_id)
    assert by_id["trim"]["fills_empty_slot"] is False and by_id["write"]["fills_empty_slot"] is True
    assert all(by_id[one]["role"] == "slot" for one in ("generate", "write", "speak", "trim", "scene_render"))
    shout = by_id[SHOUT]
    assert shout["type"] == "plugin.dev.test.boardtools.shout"
    #: 出处是插件名(「画板工具箱」),不是连接名(「我的工具箱」)—— 节点按包聚合,连接只是碰巧排第一的那条。
    #: 吃一段字、交出一段字:便签和文档的能力,宿主的字填进 `text`。
    assert shout["hosts"] == ["note", "document"] and shout["plugin_name"] == "画板工具箱"
    assert shout["role"] == "ability" and shout["host_fields"] == {"note": "text", "document": "text"}
    assert shout["config"]["text"]["board_sources"] == ["note", "document"]
    assert shout["config"]["instance_id"]["board_sources"] == [], "选连接的下拉不接上游"
    translate = by_id["node:translate"]
    assert translate["config"]["text"]["board_sources"] == ["note", "document"]
    assert translate["config"]["target_lang"]["board_sources"] == [], "固定选项的字段不接上游"
    #: 素材字段只接它声明的那几种素材(`media`):转 GIF 只吃视频,转写只吃有声音的两种。
    assert by_id["node:video_to_gif"]["config"]["asset_id"]["board_sources"] == ["video"]
    assert by_id["node:transcribe_asset"]["config"]["asset_id"]["board_sources"] == ["video", "audio"]
    #: 渲白模的镜头是从场景里挑的,不接便签(此前「能写字」就能接);场景由它挂着的那一格给。
    assert by_id["scene_render"]["config"]["shot_id"]["board_sources"] == []
    assert "node:plugin.dev.test.boardtools.secret" not in by_id
    assert "node:plugin.dev.test.boardtools.listing" not in by_id

    #: 只给宿主调的工具:画布上存着也不跑,说清楚为什么。
    board_id = _host_board(client, ws)
    refused = _run(client, board_id, ws, "node:plugin.dev.test.boardtools.secret")
    assert refused.status_code == 400, refused.text
    assert "secret" in refused.json()["detail"]

    #: 接着插件、工具也开着,只是它不是内容变换(清单会变,画布上存着这么一项是正常的):
    #: 跑的时候说清楚它归工作流,而不是叫人去插件页建连接。
    refused = _run(client, board_id, ws, "node:plugin.dev.test.boardtools.listing")
    assert refused.status_code == 400, refused.text
    #: 说的是工具的名字(清单里的 label,没写就按调用名给一个可读名),不是调用名。
    assert "Listing" in refused.json()["detail"] and "工作流" in refused.json()["detail"]
    assert "run" not in next(one for one in refused_canvas(client, board_id, ws) if one["id"] == "a1")


def test_便签的能力_吃它自己的字_产出新建在右边并连上线_重跑不覆盖(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    board_id = _host_board(client, ws, text="hello")

    placed = _run(client, board_id, ws, SHOUT)
    assert placed.status_code == 200, placed.text
    host = next(one for one in placed.json()["canvas"]["items"] if one["id"] == "a1")
    assert host["run"]["status"] in ("queued", "running") and host["run"]["ability"] == SHOUT
    #: 能力不换宿主自己的产出者:设置存进 `abilities`,产出者还排在最后、还是写字。
    assert list(host["form"]) == ["abilities", "producer"] and host["form"]["producer"] == "write"
    assert host["form"]["abilities"] == {SHOUT: {"config": {}, "bindings": {}}}

    canvas = _settled(client, board_id, ws)
    host = next(one for one in canvas["items"] if one["id"] == "a1")
    assert host["run"] == {"status": "succeeded", "ability": SHOUT}
    assert host["text"] == "hello", "能力不改宿主自己的内容"
    [made] = _derived(canvas)
    assert made["kind"] == "note" and made["text"] == "HELLO"
    #: 只落 board_outputs 点名的那个(计数不上画板),摆在宿主右边,连一根线过去。
    assert made["x"] > host["x"] + host["width"]
    assert {"source": "a1", "target": made["id"]} in [{"source": e["source"], "target": e["target"]} for e in canvas["edges"]]
    assert made["form"] == {"producer": "write"}, "落成的便签和手放的一样能让 AI 改"

    #: 改了宿主的字再跑:取的是这一刻的字,上一轮的产出留着。
    board = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()
    next(one for one in board["canvas"]["items"] if one["id"] == "a1")["text"] = "again"
    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": board["revision"], "canvas": board["canvas"]})
    assert saved.status_code == 200, saved.text
    _run(client, board_id, ws, SHOUT)
    again = _settled(client, board_id, ws)
    first, second = _derived(again)
    assert first == made, "重跑把上一轮的产出换掉了"
    assert second["text"] == "AGAIN" and second["x"] > first["x"]
    #: 版本号跟着回执涨 —— 客户端手里的旧快照存回来会撞 409,不会把派生出来的格子盖掉。
    stale = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": placed.json()["revision"], "canvas": placed.json()["canvas"]})
    assert stale.status_code == 409


def test_宿主还没有内容_能力起不了任务() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _host_board(client, ws, text="   ")
    refused = _run(client, board_id, ws, "node:translate", config={"target_lang": "en"})
    assert refused.status_code == 400, refused.text
    assert "a1" in refused.json()["detail"] and "翻译" in refused.json()["detail"]
    assert "run" not in next(one for one in refused_canvas(client, board_id, ws) if one["id"] == "a1")
    #: 能力挂不到它吃不了的格子上:翻译不是图片格的能力。
    image_board = _slot_board(client, ws, "generate")
    wrong = run_on_board(client, image_board, ws, producer="node:translate", item_id="a1", kind="image",
                         form={"config": {"target_lang": "en"}, "bindings": {}})
    assert wrong.status_code == 400 and "translate" in wrong.json()["detail"]


def test_空格子上的生成器_对得上的产出填进去_别的新建在右边(tmp_path) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Asset

    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    producer = "node:plugin.dev.test.boardtools.paint"
    board_id = _slot_board(client, ws, producer, kind="image")

    placed = _run(client, board_id, ws, producer, kind="image", config={"prompt": "一只猫"})
    assert placed.status_code == 200, placed.text
    slot = next(one for one in placed.json()["canvas"]["items"] if one["id"] == "a1")
    assert "ability" not in slot["run"] and slot["form"]["producer"] == producer
    job_id = slot["run"]["job_id"]
    assert wait_status(client, job_id, timeout=20) == "succeeded"
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "board_run"
    #: 任务中心 / 通知里那句话带着这一项的名字:此前跑完是「「」跑完了」—— 开始、跑完两句整句重写时没带名字。
    assert job["message"].endswith("跑完了") and "「」" not in job["message"], job["message"]

    canvas = _settled(client, board_id, ws)
    slot = next(one for one in canvas["items"] if one["id"] == "a1")
    #: 那张图填进这一格;说明不是一张图,新建在右边、连上线。
    assert slot["run"] == {"status": "succeeded"} and slot.get("asset_id")
    assert slot["form"]["config"] == {"prompt": "一只猫"}, "生成器的设置跑完不清"
    with SessionLocal() as db:
        asset = db.get(Asset, slot["asset_id"])
        assert asset is not None and asset.workspace_id == ws and asset.kind == "image"
    [caption] = _derived(canvas)
    assert caption["kind"] == "note" and caption["text"] == "画好了"
    assert {edge["target"] for edge in canvas["edges"] if edge["source"] == "a1"} == {caption["id"]}

    #: 没写类型的输出按值猜:一个十五项的列表 —— 一样都填不进图片格,最多新建 12 格,超出的合进最后一张 JSON 便签。
    many = "node:plugin.dev.test.boardtools.many"
    board_id = _slot_board(client, ws, many, kind="image")
    _run(client, board_id, ws, many, kind="image")
    canvas = _settled(client, board_id, ws)
    assert next(one for one in canvas["items"] if one["id"] == "a1")["run"]["status"] == "succeeded"
    derived = _derived(canvas)
    assert len(derived) == 12
    assert [one["text"] for one in derived[:11]] == [f"第{i}条" for i in range(11)]
    assert derived[-1]["text_format"] == "json"
    assert json.loads(derived[-1]["text"]) == [f"第{i}条" for i in range(11, 15)]


def test_跑挂了留下设置和原因(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    producer = "node:plugin.dev.test.boardtools.boom"
    board_id = _slot_board(client, ws, producer, config={"note": "留着"})

    placed = _run(client, board_id, ws, producer, kind="image", config={"note": "留着"})
    assert placed.status_code == 200, placed.text
    canvas = _settled(client, board_id, ws)
    slot = next(one for one in canvas["items"] if one["id"] == "a1")
    assert slot["run"]["status"] == "failed"
    assert "上游挂了" in slot["run"]["error"]
    assert slot["form"]["config"] == {"note": "留着"}
    assert _derived(canvas) == []


def test_停止会杀掉正在跑的插件进程(tmp_path) -> None:
    from app.domain import jobs

    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    producer = "node:plugin.dev.test.boardtools.sleep"
    board_id = _slot_board(client, ws, producer)

    placed = _run(client, board_id, ws, producer, kind="image")
    assert placed.status_code == 200, placed.text
    job_id = next(one for one in placed.json()["canvas"]["items"] if one["id"] == "a1")["run"]["job_id"]
    deadline = time.monotonic() + 15
    while not jobs._CHILDREN.get(job_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert jobs._CHILDREN.get(job_id), "插件进程没有登记到画板这一轮的任务名下"

    started = time.monotonic()
    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    canvas = _settled(client, board_id, ws, timeout=15)
    assert time.monotonic() - started < 15, "插件进程比取消它的任务活得久"
    slot = next(one for one in canvas["items"] if one["id"] == "a1")
    assert slot["run"]["status"] == "cancelled"
    deadline = time.monotonic() + 10
    while jobs._CHILDREN.get(job_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job_id not in jobs._CHILDREN, "被杀掉的插件进程还挂在任务名下"


def test_共享画板上谁点运行就用谁自己的连接(tmp_path) -> None:
    from app.core.db import SessionLocal
    from app.db.models import PluginInvocation

    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    ws = workspace["id"]
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    _install_plugin(tmp_path)
    mine = _connect(_me(owner))
    #: 便签上存着主人选的连接 —— 那是主人的,轮到 mate 点运行时不算数。
    board_id = _host_board(owner, ws, text="hi", abilities={SHOUT: {"config": {"instance_id": mine}}})

    #: mate 没有这个插件的连接:起任务之前就说清楚是哪个插件、去哪儿建。
    refused = _run(mate, board_id, ws, SHOUT, config={"instance_id": mine})
    assert refused.status_code == 400, refused.text
    assert "画板工具箱" in refused.json()["detail"]
    assert "run" not in next(one for one in refused_canvas(owner, board_id, ws) if one["id"] == "a1")

    theirs = _connect(_me(mate), name="mate 的工具箱")
    placed = _run(mate, board_id, ws, SHOUT, config={"instance_id": mine})
    assert placed.status_code == 200, placed.text
    canvas = _settled(owner, board_id, ws)
    [made] = _derived(canvas)
    assert made["text"] == "HI"
    #: 设置原样留着主人选的那条(下一次主人自己点,用的还是他的)。
    host = next(one for one in canvas["items"] if one["id"] == "a1")
    assert host["form"]["abilities"][SHOUT]["config"]["instance_id"] == mine
    with SessionLocal() as db:
        used = {row.instance_id for row in db.query(PluginInvocation).filter(PluginInvocation.tool_name == "shout")}
    assert used == {theirs}, "mate 点的运行用了主人的连接"


def refused_canvas(client, board_id: str, ws: str) -> list[dict]:
    return client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]


def test_数字字段填的不是数_起任务之前就拒() -> None:
    from tests.util import seed_assets

    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"v-1": "video"})
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [
        {"id": "a1", "kind": "video", "x": 0, "y": 0, "asset_id": "v-1"}], "edges": []}})
    board_id = created.json()["id"]
    refused = _run(client, board_id, ws, "node:video_to_gif", kind="video", config={"fps": "好多"})
    assert refused.status_code == 400, refused.text
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    assert "run" not in next(one for one in items if one["id"] == "a1"), "没起任务,那一格不该进「在跑」"


def test_线断了绑定就摘掉_能力的设置照留() -> None:
    from app.domain.boards import normalize_canvas

    canvas = normalize_canvas({
        "items": [
            {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "连着"},
            {"id": "n2", "kind": "note", "x": 0, "y": 0, "text": "线删了"},
            {"id": "v1", "kind": "video", "x": 0, "y": 0, "asset_id": "clip", "form": {"abilities": {
                "node:plugin.x.mux": {
                    "config": {"level": "high"},
                    "bindings": {"voice": [{"from": "n1"}, {"from": "n2"}, {"from": "n1"}], "model": [{"from": "gone"}]},
                },
                "node:video_to_gif": {"config": {"fps": 12}},
            }}},
            {"id": "i1", "kind": "image", "x": 0, "y": 0, "form": {
                "config": {"prompt": "猫"}, "bindings": {"prompt": [{"from": "n2"}]}, "producer": "node:plugin.x.paint"}},
        ],
        "edges": [{"source": "n1", "target": "v1"}],
    })
    by_id = {one["id"]: one for one in canvas["items"]}
    #: 同一格挑两次只算一次;线没了的摘掉;一个字段全摘光了整个字段就没了;设置本身不动。
    assert by_id["v1"]["form"]["abilities"] == {
        "node:plugin.x.mux": {"config": {"level": "high"}, "bindings": {"voice": [{"from": "n1"}]}},
        "node:video_to_gif": {"config": {"fps": 12}},
    }
    assert by_id["i1"]["form"]["bindings"] == {} and by_id["i1"]["form"]["config"] == {"prompt": "猫"}

    #: 没有单独的工具格了:`action` 不是一种格子。
    with pytest.raises(BoardDomainError):
        normalize_canvas({"items": [{"id": "a1", "kind": "action", "x": 0, "y": 0,
                                     "form": {"producer": "node:translate"}}]})
    for bad in ({"text": "n1"}, {"text": [{"source": "n1"}]}, {"text": [{"from": ""}]}):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "n", "kind": "note", "x": 0, "y": 0,
                                         "form": {"abilities": {"node:translate": {"bindings": bad}}}}]})
    for bad_config in ([1], {"x": float("nan")}):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "n", "kind": "note", "x": 0, "y": 0,
                                         "form": {"abilities": {"node:translate": {"config": bad_config}}}}]})
    for bad_abilities in ([1], {"not a producer": {}}, {"node:translate": {"config": {}, "extra": 1}}):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "n", "kind": "note", "x": 0, "y": 0,
                                         "form": {"abilities": bad_abilities}}]})
    #: 正文格式只有便签有。
    with pytest.raises(BoardDomainError):
        normalize_canvas({"items": [{"id": "i", "kind": "image", "x": 0, "y": 0, "text_format": "json"}]})


def test_产出按声明的类型落成格子() -> None:
    """board_outputs:素材是素材、数是字、JSON 是 JSON;只有没声明的 output 才按值猜;空值不落。"""
    from app.domain.boards.tools import board_outputs

    meta = {"outputs": ["text", "length", "segments", "vocals_asset_id", "tail"],
            "output_types": {"segments": "json"}}
    produced = board_outputs(meta, {"text": "你好", "length": 2, "segments": [{"t": 1}], "vocals_asset_id": "a-1",
                                    "tail": ""})
    assert produced == [
        {"type": "text", "text": "你好"},
        {"type": "text", "text": "2"},
        {"type": "json", "value": [{"t": 1}]},
        {"type": "asset", "asset_id": "a-1"},
    ]
    assert board_outputs({**meta, "board_outputs": ["text"]}, {"text": "只要这个", "length": 4}) == [
        {"type": "text", "text": "只要这个"}]
    #: 插件缺省的一个 output:文件(asset_id + asset_name)是素材,别的字段另成一份 JSON。
    assert board_outputs({"outputs": ["output"]}, {"output": {"asset_id": "f-1", "asset_name": "x.zip", "size": 3}}) == [
        {"type": "asset", "asset_id": "f-1"}, {"type": "json", "value": {"size": 3}}]


def test_别的文件落成写着素材名的便签() -> None:
    from app.domain.boards.canvas import _canvas_with_delivered_result

    canvas = {"items": [{"id": "a1", "kind": "audio", "x": 0, "y": 0, "width": 280, "asset_id": "src",
                         "run": {"status": "running", "job_id": "j", "ability": "node:separate_audio"}}], "edges": []}
    merged = _canvas_with_delivered_result(
        canvas, item_id="a1", job_id="j", reason="", cancelled=False, succeeded=True,
        outputs=[{"type": "asset", "asset_id": "doc"}, {"type": "asset", "asset_id": "clip"},
                 {"type": "asset", "asset_id": "elsewhere"}],
        assets={"doc": ("document", "报告.pdf"), "clip": ("audio", "旁白.mp3")},
    )
    host = next(one for one in merged["items"] if one["id"] == "a1")
    #: 宿主自己那段音频不动;这一轮是哪一项能力留在运行态上。
    assert host["asset_id"] == "src" and host["run"] == {"status": "succeeded", "ability": "node:separate_audio"}
    made = {one["id"]: one for one in merged["items"] if one["id"] != "a1"}
    assert [(one["kind"], one.get("text"), one.get("asset_id")) for one in made.values()] == [
        ("note", "报告.pdf", None), ("audio", None, "clip")]
    #: 查不到的素材(别的工作区的)不落。
    assert len(merged["edges"]) == 2


def test_插件自己写的节点表单里_format_asset_也是素材字段() -> None:
    """和从 input_schema 生成的那条同一个认法:画板上才接得到上游的图片,工作流里才有素材选择器。"""
    from app.domain.boards.tools import bindable_kinds
    from app.domain.plugins.nodes import node_meta

    meta = node_meta({"name": "cut", "node": {"config": {"picture": {"type": "template", "format": "asset"}}}})
    assert meta["config"]["picture"]["data_type"] == "asset"
    assert bindable_kinds("picture", meta["config"]["picture"]) == ["image", "video", "audio"]


def test_素材字段只接它声明的那几种素材() -> None:
    """「素材转写」此前没声明收哪种素材:画板格子上写着「接图片、视频或音频」,而转写只吃有声音的两种。
    `media` 可以是一种(字符串)或几种(列表);界面列的、写绑定时查的、运行时取值认的、能力挂在哪几种格子上,
    是同一份。"""
    from app.domain.boards.actions import BoardInputError
    from app.domain.boards.tools import bindable_kinds, check_bindings
    from app.domain.boards.transforms import board_group, board_hosts
    from app.domain.plugins.nodes import node_meta
    from app.domain.workflows import NODE_TYPES

    transcribe = NODE_TYPES["transcribe_asset"]["config"]
    assert bindable_kinds("asset_id", transcribe["asset_id"]) == ["video", "audio"]
    assert bindable_kinds("asset_id", NODE_TYPES["video_to_gif"]["config"]["asset_id"]) == ["video"]
    for audio_or_video in ("separate_audio", "denoise_audio"):
        assert bindable_kinds("asset_id", NODE_TYPES[audio_or_video]["config"]["asset_id"]) == ["video", "audio"]
    #: 没声明的照旧哪种都收(时间线追加、发布)。
    assert bindable_kinds("asset_id", NODE_TYPES["timeline_append"]["config"]["asset_id"]) == ["image", "video", "audio"]

    #: 插件的 `x-media` 也能写几种;一种照旧写成字符串;认不出的丢掉。
    sound = {"type": "object", "properties": {
        "clip": {"type": "string", "format": "asset", "x-media": ["audio", "video", "nonsense"]},
        "cover": {"type": "string", "format": "asset", "x-media": "image"},
    }}
    meta = node_meta({"name": "t", "input_schema": sound, "node": {"outputs": ["asset_id"]}})
    assert meta["config"]["clip"]["media"] == ["video", "audio"] and meta["config"]["cover"]["media"] == "image"
    assert bindable_kinds("clip", meta["config"]["clip"]) == ["video", "audio"]
    #: 两个素材字段收的不是同一种:归「素材」,不归某一种;哪一种格子都能当它的宿主(填进收得下它的那个字段)。
    assert board_group(meta) == "asset"
    assert board_hosts(meta) == ("image", "video", "audio")

    canvas = {"items": [{"id": "img", "kind": "image", "asset_id": "a"}, {"id": "t", "kind": "video"}],
              "edges": [{"source": "img", "target": "t"}]}
    with pytest.raises(BoardInputError) as caught:
        check_bindings(canvas, "t", transcribe, {"asset_id": [{"from": "img"}]}, "transcribe_asset")
    assert caught.value.key == "boardErr_bindingKindMismatch"


def test_能力的设置归宿主_它自己再跑一次也带着() -> None:
    """一格自己的产出者重新跑(重新生成、让 AI 改写)时,摆占位写的是它自己那一份表单 —— 能力的设置是这一格的,
    不跟着这一轮换掉;跑一项能力时,设置合进宿主此刻的表单,自己的产出者和别的几项不动。"""
    from app.domain.boards.canvas import _keeping_abilities, _with_ability

    stored = {"prompt": "旧", "abilities": {"node:translate": {"config": {"target_lang": "en"}}}, "producer": "write"}
    assert _keeping_abilities({"prompt": "新", "model": "m", "producer": "write"}, stored) == {
        "prompt": "新", "model": "m", "abilities": {"node:translate": {"config": {"target_lang": "en"}}}, "producer": "write"}
    assert _keeping_abilities({"prompt": "新"}, {"prompt": "旧"}) == {"prompt": "新"}
    assert _with_ability(stored, "node:shout", {"config": {}, "bindings": {}}) == {
        "prompt": "旧",
        "abilities": {"node:translate": {"config": {"target_lang": "en"}}, "node:shout": {"config": {}, "bindings": {}}},
        "producer": "write",
    }
    assert _with_ability(None, "node:shout", {"config": {}}) == {"abilities": {"node:shout": {"config": {}}}}
