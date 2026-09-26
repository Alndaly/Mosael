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


def test_内置的四个产出者各自挂在该挂的格子上() -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import producers
    from app.domain.boards.producer_ids import BUILTIN_PRODUCER_IDS
    from app.domain.generation.resolution import KINDS

    fresh_client()
    with SessionLocal() as db:
        registry = producers.list_producers(db, None)
    by_id = {one.id: one for one in registry if not one.id.startswith("node:")}
    assert set(by_id) == {"generate", "speak", "trim", "write"}
    #: canvas 校验表单时认的那张名字表,和注册表是同一份。
    assert set(BUILTIN_PRODUCER_IDS) == set(by_id)
    #: 能挑来填空槽的是这三个(一种格子有两个时面板上给切换);截一段得先有一段素材。
    assert {one for one in by_id if by_id[one].fills_empty_slot} == {"generate", "speak", "write"}

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

    from app.core.db import SessionLocal

    fresh_client()
    with SessionLocal() as db:
        registry = producers.list_producers(db, None)
    leaky = [one.id for one in registry if one.form.model_config.get("allow_inf_nan") is not False]
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


# ── P2:工具格(`action`)跑一个节点 ─────────────────────────────────────────────
#
# 插件工具、声明了能上画板的内置节点,都是 `node:<节点类型>` 产出者,挂在工具格上。产出新建成右边
# 的几格并连上线;失败留下表单和原因;停止真的停下插件进程;共享画板上谁点运行用谁自己的连接。

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

#: 工具的声明。shout 写明了输出(summary 是文字、count 不上画板);paint 交出一个文件;
#: many 的输出没写类型(按值猜);secret 只给宿主调。
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
        "node": {"outputs": ["caption", "asset_id"], "output_types": {"caption": "text"}},
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


def _action_board(client, ws: str, producer: str, *, config: dict | None = None, bindings: dict | None = None,
                  items: list[dict] | None = None, edges: list[dict] | None = None) -> str:
    action = {"id": "a1", "kind": "action", "x": 100, "y": 50, "width": 280, "height": 150,
              "form": {"config": config or {}, "bindings": bindings or {}, "producer": producer}}
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {
        "items": [*(items or []), action], "edges": edges or []}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _run_tool(client, board_id: str, ws: str, producer: str, *, config: dict | None = None,
              bindings: dict | None = None):
    return run_on_board(client, board_id, ws, producer=producer, item_id="a1", kind="action", x=100, y=50,
                        form={"config": config or {}, "bindings": bindings or {}})


def _settled(client, board_id: str, ws: str, timeout: float = 20.0) -> dict:
    """等工具格那一轮落终态(回执落回画布),返回那时的画布。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        canvas = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]
        action = next(one for one in canvas["items"] if one["id"] == "a1")
        if (action.get("run") or {}).get("status") in ("succeeded", "failed", "cancelled"):
            return canvas
        time.sleep(0.1)
    raise AssertionError("工具格一直没跑完")


def _derived(canvas: dict) -> list[dict]:
    """工具格连出去的那几格,按摆放的先后(从上往下)。"""
    targets = {edge["target"] for edge in canvas["edges"] if edge["source"] == "a1"}
    return sorted((one for one in canvas["items"] if one["id"] in targets), key=lambda one: (one["x"], one["y"]))


#: 画板上的内置工具:只有内容变换(ADR 0021 修订)。
BOARD_NODES = {"transcribe_asset", "translate", "video_to_gif", "separate_audio", "denoise_audio", "scene_render"}


def test_工具格能跑的节点从节点声明里读_只有内容变换() -> None:
    """RATCHET:`surfaces` 声明和注册表是同一件事,清单只在 NODE_TYPES 里写一次,画板不另列;
    **声明了画板的节点必须是内容变换** —— 流程控制、数据处理、知识库的节点声明了也不算数,这里当场报出来。"""
    from app.core.db import SessionLocal
    from app.core.i18n import MESSAGES
    from app.domain.boards import producers
    from app.domain.boards.transforms import BOARD_GROUPS, content_transform_gap
    from app.domain.workflows import NODE_TYPES, WIRING_CATEGORIES
    from app.domain.workflows.executors import get_executor

    declared = {name for name, spec in NODE_TYPES.items() if "board" in (spec.get("surfaces") or ())}
    assert declared == BOARD_NODES
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
            #: 添加菜单里归哪一组、给创作者看的一句话:内置的都写明,不靠推。
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
    assert all(registry[one].hosts == ("action",) for one in nodes)
    #: 这几个都在本机做完(对外发请求、调别的流程的那两个已经不在画板上了)。
    assert all(registry[one].effects == "none" for one in nodes)


def test_声明了画板的流程节点注册表也不收_跑的时候说清楚(monkeypatch) -> None:
    """规矩是注册表的一道门,不只是棘轮:哪天有人给 HTTP 请求写回 `surfaces: ["board"]`,画板上也不会多出它;
    画布上存着的那一格点运行,说清楚这件事归工作流。"""
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
        board_id = _action_board(client, ws, gone)
        refused = _run_tool(client, board_id, ws, gone)
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
    #: 不吃内容、交出素材:凭空产出(提示词出图、按参数出讲解视频、从存储取回一个文件)。
    made = tool(input_schema={"type": "object", "properties": {"key": {"type": "string"}}},
                node={"outputs": ["asset_id", "summary"], "output_types": {"asset_id": "asset"}, "board_outputs": ["asset_id"]})
    assert content_transform_gap(made) is None and board_group(made) == "new"
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
    """对着仓库里的清单:取回文件、导入、出片的上画板;列清单、看状态、上传、装环境的不上。"""
    from app.domain.boards.transforms import is_content_transform
    from app.domain.plugins.nodes import node_meta

    root = Path(__file__).resolve().parents[2] / "plugins"
    eligible = set()
    for path in sorted(root.glob("*/*/mosael.plugin.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        tools = manifest.get("tools") or {}
        for declared in tools.get("declare") or []:
            if not declared.get("internal") and is_content_transform(node_meta(declared)):
                eligible.add(f"{manifest['id']}.{declared['name']}")
    for name in ("dev.mosael.object-storage.storage_fetch", "dev.mosael.baidu-pan.pan_import",
                 "dev.mosael.comfyui.import_outputs", "dev.mosael.manim.manim_still", "dev.mosael.remotion.remotion_animation"):
        assert name in eligible, name
    for name in ("dev.mosael.baidu-pan.pan_list", "dev.mosael.baidu-pan.pan_search", "dev.mosael.baidu-pan.pan_upload",
                 "dev.mosael.comfyui.server_status", "dev.mosael.comfyui.list_workflows", "dev.mosael.comfyui.list_models",
                 "dev.mosael.comfyui.interrupt", "dev.mosael.comfyui.clear_queue", "dev.mosael.comfyui.free_memory",
                 "dev.mosael.object-storage.storage_upload", "dev.mosael.object-storage.storage_list",
                 "dev.mosael.object-storage.storage_presign", "dev.mosael.manim.manim_setup",
                 "dev.mosael.remotion.remotion_setup",
                 #: 必填一串结构化的步骤 / 小节(JSON):画板的表单上填不了,在工作流或对话里用。
                 "dev.mosael.manim.manim_explainer", "dev.mosael.remotion.remotion_explainer"):
        assert name not in eligible, name


def test_画板表单只摆创作者看得懂的参数(tmp_path) -> None:
    """参数规矩:工具格的表单里没有映射、原始 JSON、代码,没有 `{{…}}` 引用写法;说明是画板那一句。
    接口给的就是这一份 —— 界面和智能体(list_board_producers)看到的一样。"""
    from app.domain.boards.transforms import BOARD_GROUPS

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
    #: 模板字段在画板上就是一段字;原始 JSON 的字段不出现;3D 场景那格的说明(教 `{{…}}` 写法的)不带过来。
    assert by_id["node:translate"]["config"]["text"]["type"] == "text"
    assert "extra" not in by_id["node:plugin.dev.test.boardtools.paint"]["config"]
    assert "description" not in by_id["node:scene_render"]["config"]["scene_id"]
    assert by_id["node:video_to_gif"]["board_description"] == "把一段视频做成 GIF 动图"
    #: 工具格上「产出」那一行说的是落板的内容,不是节点的全部输出(源素材 id、引擎名不算)。
    assert by_id["node:video_to_gif"]["board_products"] == ["asset_id"]
    assert by_id["node:separate_audio"]["board_products"] == ["vocals_asset_id", "background_asset_id"]
    assert by_id["node:translate"]["board_products"] == ["text"]
    assert all(set(one["board_products"]) <= set(one["outputs"]) and one["board_products"] for one in tools)
    #: 按吃什么内容分组、同组挨在一起(菜单按相邻的同名组归组)。
    groups = [one["board_group"] for one in tools]
    assert groups == sorted(groups, key=BOARD_GROUPS.index)
    assert by_id["node:translate"]["board_group"] == "text" and by_id["node:translate"]["board_group_label"] == "处理文字"
    assert by_id["node:plugin.dev.test.boardtools.paint"]["board_group"] == "new"
    assert by_id["node:plugin.dev.test.boardtools.shout"]["board_group"] == "text"
    #: 内置的四个不在「添加 → 工具」里,不带分组。
    assert all(one["board_group"] == "" for one in listed.json() if not one["id"].startswith("node:"))


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
    assert mine["node:plugin.dev.test.boardtools.shout"].effects == "none"
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
    shout = by_id["node:plugin.dev.test.boardtools.shout"]
    assert shout["type"] == "plugin.dev.test.boardtools.shout"
    assert shout["hosts"] == ["action"] and shout["plugin_name"] == "我的工具箱"
    assert shout["config"]["text"]["board_sources"] == ["note", "document"]
    assert shout["config"]["instance_id"]["board_sources"] == [], "选连接的下拉不接上游"
    translate = by_id["node:translate"]
    assert translate["config"]["text"]["board_sources"] == ["note", "document"]
    assert translate["config"]["target_lang"]["board_sources"] == [], "固定选项的字段不接上游"
    assert by_id["node:video_to_gif"]["config"]["asset_id"]["board_sources"] == ["image", "video", "audio"]
    assert by_id["node:scene_render"]["config"]["scene_id"]["board_sources"] == ["scene"]
    assert "node:plugin.dev.test.boardtools.secret" not in by_id
    assert "node:plugin.dev.test.boardtools.listing" not in by_id

    #: 只给宿主调的工具:画布上存着也不跑,说清楚为什么。
    board_id = _action_board(client, ws, "node:plugin.dev.test.boardtools.secret")
    refused = _run_tool(client, board_id, ws, "node:plugin.dev.test.boardtools.secret")
    assert refused.status_code == 400, refused.text
    assert "secret" in refused.json()["detail"]

    #: 接着插件、工具也开着,只是它不是内容变换(清单会变,画布上存着这么一格是正常的):
    #: 跑的时候说清楚它归工作流,而不是叫人去插件页建连接。
    board_id = _action_board(client, ws, "node:plugin.dev.test.boardtools.listing")
    refused = _run_tool(client, board_id, ws, "node:plugin.dev.test.boardtools.listing")
    assert refused.status_code == 400, refused.text
    assert "listing" in refused.json()["detail"] and "工作流" in refused.json()["detail"]
    assert "run" not in next(one for one in refused_canvas(client, board_id, ws) if one["id"] == "a1")


def test_工具格吃便签的字_产出新建在右边并连上线_重跑不覆盖(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    shout = "node:plugin.dev.test.boardtools.shout"
    notes = [
        {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hello"},
        {"id": "n2", "kind": "note", "x": 0, "y": 200, "text": "board"},
    ]
    #: 线的先后是 n2 在前 —— 拼起来按连线的先后,不按绑定里写的顺序。
    edges = [{"id": "e2", "source": "n2", "target": "a1"}, {"id": "e1", "source": "n1", "target": "a1"}]
    bindings = {"text": [{"from": "n1"}, {"from": "n2"}]}
    board_id = _action_board(client, ws, shout, bindings=bindings, items=notes, edges=edges)

    placed = _run_tool(client, board_id, ws, shout, bindings=bindings)
    assert placed.status_code == 200, placed.text
    action = next(one for one in placed.json()["canvas"]["items"] if one["id"] == "a1")
    assert action["run"]["status"] in ("queued", "running")
    assert list(action["form"]) [-1] == "producer" and action["form"]["producer"] == shout

    canvas = _settled(client, board_id, ws)
    action = next(one for one in canvas["items"] if one["id"] == "a1")
    assert action["run"] == {"status": "succeeded"}
    #: 工具格就是一份能反复跑的配置 —— 跑完不清表单。
    assert action["form"]["config"] == {} and action["form"]["bindings"] == bindings
    [made] = _derived(canvas)
    assert made["kind"] == "note" and made["text"] == "BOARD\n\nHELLO"
    #: 只落 board_outputs 点名的那个(计数不上画板),摆在工具格右边。
    assert made["x"] > action["x"] + action["width"]
    assert made["form"] == {"producer": "write"}, "落成的便签和手放的一样能让 AI 改"

    #: 改了上游便签的字再跑:取的是这一刻的字,上一轮的产出留着。
    board = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()
    next(one for one in board["canvas"]["items"] if one["id"] == "n1")["text"] = "again"
    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": board["revision"], "canvas": board["canvas"]})
    assert saved.status_code == 200, saved.text
    _run_tool(client, board_id, ws, shout, bindings=bindings)
    again = _settled(client, board_id, ws)
    first, second = _derived(again)
    assert first == made, "重跑把上一轮的产出换掉了"
    assert second["text"] == "BOARD\n\nAGAIN" and second["x"] > first["x"]
    #: 版本号跟着回执涨 —— 客户端手里的旧快照存回来会撞 409,不会把派生出来的格子盖掉。
    stale = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": placed.json()["revision"], "canvas": placed.json()["canvas"]})
    assert stale.status_code == 409


def test_插件工具跑通_文件落成图片格_文字落成便签(tmp_path) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Asset

    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    producer = "node:plugin.dev.test.boardtools.paint"
    board_id = _action_board(client, ws, producer)

    placed = _run_tool(client, board_id, ws, producer, config={"prompt": "一只猫"})
    assert placed.status_code == 200, placed.text
    job_id = next(one for one in placed.json()["canvas"]["items"] if one["id"] == "a1")["run"]["job_id"]
    assert wait_status(client, job_id, timeout=20) == "succeeded"
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["kind"] == "board_run"

    canvas = _settled(client, board_id, ws)
    caption, picture = sorted(_derived(canvas), key=lambda one: one["kind"] != "note")
    assert caption == {**caption, "kind": "note", "text": "画好了"}
    assert picture["kind"] == "image"
    with SessionLocal() as db:
        asset = db.get(Asset, picture["asset_id"])
        assert asset is not None and asset.workspace_id == ws and asset.kind == "image"
    #: 每一格都有一根从工具格连过去的线。
    assert {edge["target"] for edge in canvas["edges"] if edge["source"] == "a1"} == {caption["id"], picture["id"]}

    #: 没写类型的输出按值猜:一个十五项的列表 —— 最多新建 12 格,超出的合进最后一张 JSON 便签。
    many = "node:plugin.dev.test.boardtools.many"
    board_id = _action_board(client, ws, many)
    _run_tool(client, board_id, ws, many)
    derived = _derived(_settled(client, board_id, ws))
    assert len(derived) == 12
    assert [one["text"] for one in derived[:11]] == [f"第{i}条" for i in range(11)]
    assert derived[-1]["text_format"] == "json"
    assert json.loads(derived[-1]["text"]) == [f"第{i}条" for i in range(11, 15)]


def test_跑挂了留下表单和原因(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    producer = "node:plugin.dev.test.boardtools.boom"
    board_id = _action_board(client, ws, producer, config={"note": "留着"})

    placed = _run_tool(client, board_id, ws, producer, config={"note": "留着"})
    assert placed.status_code == 200, placed.text
    canvas = _settled(client, board_id, ws)
    action = next(one for one in canvas["items"] if one["id"] == "a1")
    assert action["run"]["status"] == "failed"
    assert "上游挂了" in action["run"]["error"]
    assert action["form"]["config"] == {"note": "留着"}
    assert _derived(canvas) == []


def test_停止会杀掉正在跑的插件进程(tmp_path) -> None:
    from app.domain import jobs

    client = fresh_client()
    ws = _workspace(client)
    _install_plugin(tmp_path)
    _connect(_me(client))
    producer = "node:plugin.dev.test.boardtools.sleep"
    board_id = _action_board(client, ws, producer)

    placed = _run_tool(client, board_id, ws, producer)
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
    action = next(one for one in canvas["items"] if one["id"] == "a1")
    assert action["run"]["status"] == "cancelled"
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
    producer = "node:plugin.dev.test.boardtools.shout"
    #: 表单上存着主人选的连接 —— 那是主人的,轮到 mate 点运行时不算数。
    board_id = _action_board(owner, ws, producer, config={"instance_id": mine, "text": "hi"})

    #: mate 没有这个插件的连接:起任务之前就说清楚是哪个插件、去哪儿建。
    refused = _run_tool(mate, board_id, ws, producer, config={"instance_id": mine, "text": "hi"})
    assert refused.status_code == 400, refused.text
    assert "画板工具箱" in refused.json()["detail"]
    assert "run" not in next(one for one in refused_canvas(owner, board_id, ws) if one["id"] == "a1")

    theirs = _connect(_me(mate), name="mate 的工具箱")
    placed = _run_tool(mate, board_id, ws, producer, config={"instance_id": mine, "text": "hi"})
    assert placed.status_code == 200, placed.text
    canvas = _settled(owner, board_id, ws)
    [made] = _derived(canvas)
    assert made["text"] == "HI"
    #: 表单原样留着主人选的那条(下一次主人自己点,用的还是他的)。
    action = next(one for one in canvas["items"] if one["id"] == "a1")
    assert action["form"]["config"]["instance_id"] == mine
    with SessionLocal() as db:
        used = {row.instance_id for row in db.query(PluginInvocation).filter(PluginInvocation.tool_name == "shout")}
    assert used == {theirs}, "mate 点的运行用了主人的连接"


def refused_canvas(client, board_id: str, ws: str) -> list[dict]:
    return client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]


def test_数字字段填的不是数_起任务之前就拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _action_board(client, ws, "node:video_to_gif")
    refused = _run_tool(client, board_id, ws, "node:video_to_gif", config={"fps": "好多"})
    assert refused.status_code == 400, refused.text
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    assert "run" not in next(one for one in items if one["id"] == "a1"), "没起任务,工具格不该进「在跑」"


def test_线断了绑定就摘掉_工具格不能当上游() -> None:
    from app.domain.boards import normalize_canvas

    canvas = normalize_canvas({
        "items": [
            {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "连着"},
            {"id": "n2", "kind": "note", "x": 0, "y": 0, "text": "线删了"},
            {"id": "t0", "kind": "action", "x": 0, "y": 0, "form": {"producer": "node:video_to_gif"}},
            {"id": "a1", "kind": "action", "x": 0, "y": 0, "form": {
                "producer": "node:translate",
                "config": {"target_lang": "en"},
                "bindings": {"text": [{"from": "n1"}, {"from": "n2"}, {"from": "n1"}], "engine": [{"from": "t0"}],
                             "model": [{"from": "gone"}]},
            }},
        ],
        "edges": [{"source": "n1", "target": "a1"}, {"source": "t0", "target": "a1"}],
    })
    action = next(one for one in canvas["items"] if one["id"] == "a1")
    #: 同一格挑两次只算一次;线没了的摘掉;接在另一个工具格上的摘掉;一个字段全摘光了整个字段就没了。
    assert action["form"]["bindings"] == {"text": [{"from": "n1"}]}
    assert action["form"]["config"] == {"target_lang": "en"}

    for bad in ({"text": "n1"}, {"text": [{"source": "n1"}]}, {"text": [{"from": ""}]}):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "a1", "kind": "action", "x": 0, "y": 0,
                                         "form": {"producer": "node:translate", "bindings": bad}}]})
    for bad_config in ([1], {"x": float("nan")}):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "a1", "kind": "action", "x": 0, "y": 0,
                                         "form": {"producer": "node:translate", "config": bad_config}}]})
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

    canvas = {"items": [{"id": "a1", "kind": "action", "x": 0, "y": 0, "width": 280,
                         "run": {"status": "running", "job_id": "j"}}], "edges": []}
    merged = _canvas_with_delivered_result(
        canvas, item_id="a1", job_id="j", reason="", cancelled=False, succeeded=True,
        outputs=[{"type": "asset", "asset_id": "doc"}, {"type": "asset", "asset_id": "clip"},
                 {"type": "asset", "asset_id": "elsewhere"}],
        assets={"doc": ("document", "报告.pdf"), "clip": ("audio", "旁白.mp3")},
    )
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
