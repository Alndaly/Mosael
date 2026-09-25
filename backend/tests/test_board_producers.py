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
        "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
        "node": {"outputs": ["caption", "asset_id"], "output_types": {"caption": "text"}},
    },
    #: 声明了输出名、没声明类型:值是一个列表,按值猜 —— 一个列表落成好几格。
    {"name": "many", "input_schema": {"type": "object", "properties": {}}, "node": {"outputs": ["lines"]}},
    {"name": "boom", "input_schema": {"type": "object", "properties": {}}},
    {"name": "sleep", "input_schema": {"type": "object", "properties": {}}},
    {"name": "secret", "input_schema": {"type": "object", "properties": {}}},
]


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


def test_工具格能跑的节点从节点声明里读_和第一批清单一致() -> None:
    """RATCHET:`surfaces` 声明和注册表是同一件事。清单只在 NODE_TYPES 里写一次,画板不另列。"""
    from app.core.db import SessionLocal
    from app.domain.boards import producers
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.executors import get_executor

    first_batch = {
        "transcribe_asset", "translate", "text_transform", "json_extract", "template", "video_to_gif",
        "separate_audio", "denoise_audio", "note_search", "scene_render", "call_workflow", "http_request",
    }
    declared = {name for name, spec in NODE_TYPES.items() if "board" in (spec.get("surfaces") or ())}
    assert declared == first_batch
    #: 决定 3:和内置写字/生成/念重复的、副作用大的、流程控制类不上画板。
    for kept_off in ("llm", "ai_generate", "synthesize_speech", "publish", "timeline_append", "start", "output",
                     "condition", "subgraph", "loop_foreach", "code", "delay"):
        assert "board" not in (NODE_TYPES[kept_off].get("surfaces") or ()), kept_off
    for name, spec in NODE_TYPES.items():
        assert set(spec.get("surfaces") or ()) <= {"workflow", "board"}, name
        if "board" in (spec.get("surfaces") or ()):
            assert get_executor(name) is not None, name
            assert set(spec.get("board_outputs") or spec["outputs"]) <= set(spec["outputs"]), name
        else:
            assert "board_outputs" not in spec, f"{name} 没上画板却声明了 board_outputs"

    fresh_client()
    with SessionLocal() as db:
        registry = {one.id: one for one in producers.list_producers(db, None)}
    nodes = {one for one in registry if one.startswith("node:")}
    assert nodes == {f"node:{name}" for name in first_batch}
    assert all(registry[one].hosts == ("action",) for one in nodes)
    #: 后果落在应用之外的(发请求、调别的流程)要确认卡。
    assert {one for one in nodes if registry[one].effects == "external"} == {"node:http_request", "node:call_workflow"}


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
    assert tools == {f"node:plugin.dev.test.boardtools.{name}" for name in ("shout", "paint", "many", "boom", "sleep")}
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
    transform = by_id["node:text_transform"]
    assert transform["config"]["text"]["board_sources"] == ["note", "document"]
    assert transform["config"]["op"]["board_sources"] == [], "固定选项的字段不接上游"
    assert by_id["node:video_to_gif"]["config"]["asset_id"]["board_sources"] == ["image", "video", "audio"]
    assert by_id["node:scene_render"]["config"]["scene_id"]["board_sources"] == ["scene"]
    assert "node:plugin.dev.test.boardtools.secret" not in by_id

    #: 只给宿主调的工具:画布上存着也不跑,说清楚为什么。
    board_id = _action_board(client, ws, "node:plugin.dev.test.boardtools.secret")
    refused = _run_tool(client, board_id, ws, "node:plugin.dev.test.boardtools.secret")
    assert refused.status_code == 400, refused.text
    assert "secret" in refused.json()["detail"]


def test_内置的文字处理跑在便签上_产出新建在右边并连上线_重跑不覆盖() -> None:
    client = fresh_client()
    ws = _workspace(client)
    notes = [
        {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "hello"},
        {"id": "n2", "kind": "note", "x": 0, "y": 200, "text": "board"},
    ]
    #: 线的先后是 n2 在前 —— 拼起来按连线的先后,不按绑定里写的顺序。
    edges = [{"id": "e2", "source": "n2", "target": "a1"}, {"id": "e1", "source": "n1", "target": "a1"}]
    bindings = {"text": [{"from": "n1"}, {"from": "n2"}]}
    board_id = _action_board(client, ws, "node:text_transform", config={"op": "upper"}, bindings=bindings,
                             items=notes, edges=edges)

    placed = _run_tool(client, board_id, ws, "node:text_transform", config={"op": "upper"}, bindings=bindings)
    assert placed.status_code == 200, placed.text
    action = next(one for one in placed.json()["canvas"]["items"] if one["id"] == "a1")
    assert action["run"]["status"] in ("queued", "running")
    assert list(action["form"]) [-1] == "producer" and action["form"]["producer"] == "node:text_transform"

    canvas = _settled(client, board_id, ws)
    action = next(one for one in canvas["items"] if one["id"] == "a1")
    assert action["run"] == {"status": "succeeded"}
    #: 工具格就是一份能反复跑的配置 —— 跑完不清表单。
    assert action["form"]["config"] == {"op": "upper"} and action["form"]["bindings"] == bindings
    [made] = _derived(canvas)
    assert made["kind"] == "note" and made["text"] == "BOARD\n\nHELLO"
    #: 只落 board_outputs 点名的那个(字数不上画板),摆在工具格右边。
    assert made["x"] > action["x"] + action["width"]
    assert made["form"] == {"producer": "write"}, "落成的便签和手放的一样能让 AI 改"

    _run_tool(client, board_id, ws, "node:text_transform", config={"op": "lower"}, bindings=bindings)
    again = _settled(client, board_id, ws)
    first, second = _derived(again)
    assert first == made, "重跑把上一轮的产出换掉了"
    assert second["text"] == "board\n\nhello" and second["x"] > first["x"]
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
    board_id = _action_board(client, ws, "node:note_search")
    refused = _run_tool(client, board_id, ws, "node:note_search", config={"query": "猫", "limit": "好多"})
    assert refused.status_code == 400, refused.text
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    assert "run" not in next(one for one in items if one["id"] == "a1"), "没起任务,工具格不该进「在跑」"


def test_线断了绑定就摘掉_工具格不能当上游() -> None:
    from app.domain.boards import normalize_canvas

    canvas = normalize_canvas({
        "items": [
            {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "连着"},
            {"id": "n2", "kind": "note", "x": 0, "y": 0, "text": "线删了"},
            {"id": "t0", "kind": "action", "x": 0, "y": 0, "form": {"producer": "node:template"}},
            {"id": "a1", "kind": "action", "x": 0, "y": 0, "form": {
                "producer": "node:text_transform",
                "config": {"op": "trim"},
                "bindings": {"text": [{"from": "n1"}, {"from": "n2"}, {"from": "n1"}], "find": [{"from": "t0"}],
                             "replace": [{"from": "gone"}]},
            }},
        ],
        "edges": [{"source": "n1", "target": "a1"}, {"source": "t0", "target": "a1"}],
    })
    action = next(one for one in canvas["items"] if one["id"] == "a1")
    #: 同一格挑两次只算一次;线没了的摘掉;接在另一个工具格上的摘掉;一个字段全摘光了整个字段就没了。
    assert action["form"]["bindings"] == {"text": [{"from": "n1"}]}
    assert action["form"]["config"] == {"op": "trim"}

    for bad in ({"text": "n1"}, {"text": [{"source": "n1"}]}, {"text": [{"from": ""}]}):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "a1", "kind": "action", "x": 0, "y": 0,
                                         "form": {"producer": "node:template", "bindings": bad}}]})
    for bad_config in ([1], {"x": float("nan")}):
        with pytest.raises(BoardDomainError):
            normalize_canvas({"items": [{"id": "a1", "kind": "action", "x": 0, "y": 0,
                                         "form": {"producer": "node:template", "config": bad_config}}]})
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
