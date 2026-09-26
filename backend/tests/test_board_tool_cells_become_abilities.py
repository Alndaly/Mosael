"""画板上的工具格撤下:`migrate-board-tool-cells-become-abilities`(ADR 0025 修订「能力住在内容格上」)。

把内容变成新内容的工具是内容格自己的能力,凭空出素材的生成器是空格子的一种填法。升级前存着的每一格工具格:

· 能力、接着(绑定且线在)或填的是(素材 id 对得上)一格收得下它的内容格 —— 设置搬进那一格的
  `form.abilities[产出者]`,工具格删掉,连向产出的线改从宿主连出,接着别的字段的上游改连进宿主;
· 生成器 —— 同一个 id、位置、大小、名字,改成它产出的那种素材的空格子,`form.producer` 就是它;
· 其余(认不出、不再是内容变换、找不到宿主、宿主上已经存着这一项的另一套设置)—— 改成便签,设置附在后面。
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import Board
from tests.util import fresh_client

PACKAGE = "dev.test.migrating"

#: `mux` 吃一段视频(必填)和一段音频:视频 / 音频格的能力(视频格上视频是宿主,音频从连进来的上游接);
#: `draw` 按提示词出图:图片空格子的一种填法。
TOOLS = [
    {"name": "mux", "input_schema": {"type": "object", "properties": {
        "video": {"type": "string", "format": "asset", "x-media": "video"},
        "voice": {"type": "string", "format": "asset", "x-media": "audio"},
        "level": {"type": "string", "enum": ["low", "high"]}}, "required": ["video"]},
     "node": {"outputs": ["asset_id"], "output_types": {"asset_id": "asset"}, "output_media": {"asset_id": "video"}}},
    {"name": "draw", "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
     "node": {"outputs": ["asset_id"], "output_types": {"asset_id": "asset"}, "output_media": {"asset_id": "image"}}},
]


def _install(root: Path) -> None:
    from app.db.models import PluginInstance, PluginPackage
    from app.domain.plugins.tools import refresh_tools

    plugin_dir = root / PACKAGE
    shutil.rmtree(plugin_dir, ignore_errors=True)
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent("import json\nprint(json.dumps({'ok': True, 'output': {}}))\n"))
    manifest = {"id": PACKAGE, "name": "迁移用", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": TOOLS}, "_path": str(plugin_dir)}
    (plugin_dir / "mosael.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="迁移用", version="0.1.0", manifest=manifest))
        db.commit()
        instance = PluginInstance(package_id=PACKAGE, name="我的", enabled=True, owner_user_id="someone")
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)


def _canvas(board_id: str) -> tuple[dict, int]:
    with SessionLocal() as db:
        board = db.get(Board, board_id)
        canvas = board.canvas
        return (json.loads(canvas) if isinstance(canvas, str) else canvas), board.revision


def _tool(item_id: str, producer: str, config: dict | None = None, bindings: dict | None = None, **extra) -> dict:
    return {"id": item_id, "kind": "action", "x": 400, "y": 0, "width": 260, "height": 180,
            "form": {"config": config or {}, "bindings": bindings or {}, "producer": producer}, **extra}


def test_工具格搬到它接着的内容格上_生成器变成空格子_其余改成便签(tmp_path: Path) -> None:
    from app.db.migrations import _migrate_board_tool_cells_become_abilities, migration_plan
    from app.domain.boards import normalize_canvas

    assert "migrate-board-tool-cells-become-abilities" in {step.name for step in migration_plan().steps}

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path)
    mux, draw = f"node:plugin.{PACKAGE}.mux", f"node:plugin.{PACKAGE}.draw"
    items = [
        {"id": "au", "kind": "audio", "x": 0, "y": 0, "asset_id": "aud"},
        {"id": "n1", "kind": "note", "x": 0, "y": 300, "text": "hello", "form": {"producer": "write"}},
        {"id": "v1", "kind": "video", "x": 0, "y": 600, "asset_id": "vid"},
        {"id": "v2", "kind": "video", "x": 0, "y": 900, "asset_id": "vid2", "form": {"prompt": "旧的", "producer": "generate"}},
        #: 转写接着音频 au:设置搬过去,工具格删掉,产出改从 au 连出。
        _tool("t1", "node:transcribe_asset", {"engine": "funasr"}, {"asset_id": [{"from": "au"}]},
              run={"status": "succeeded"}),
        {"id": "t1-out-1", "kind": "note", "x": 800, "y": 0, "text": "转出来的字", "form": {"producer": "write"}},
        #: 翻译接着便签 n1。
        _tool("t2", "node:translate", {"target_lang": "en"}, {"text": [{"from": "n1"}]}),
        #: 同一格便签、同一套设置的第二格:并进去。
        _tool("t6", "node:translate", {"target_lang": "en"}, {"text": [{"from": "n1"}]}),
        #: 同一格便签、另一套设置:不能悄悄丢 —— 改成便签。
        _tool("t5", "node:translate", {"target_lang": "ja"}, {"text": [{"from": "n1"}]}, title="日文那版"),
        #: 翻译没接任何一格:改成便签。
        _tool("t3", "node:translate", {"target_lang": "fr"}),
        #: 转 GIF 手填的素材 id 正好是 v1 的那一段:搬到 v1 上(宿主那个字段不带过去)。
        _tool("t4", "node:video_to_gif", {"asset_id": "vid", "fps": 12}),
        #: 多输入的插件能力:视频接 v2(宿主),音频接 au(改连进 v2、绑定照留),level 是设置。
        _tool("t9", mux, {"level": "high"}, {"video": [{"from": "v2"}], "voice": [{"from": "au"}]}),
        {"id": "t9-out-1", "kind": "video", "x": 800, "y": 900, "asset_id": "muxed"},
        #: 插件生成器:改成图片空格子,设置和绑定照留(提示词接便签的线还在)。
        _tool("t10", draw, {"instance_id": "i-1"}, {"prompt": [{"from": "n1"}]}, title="出图"),
        #: 认不出的插件工具、流程节点:改成便签。
        _tool("t7", "node:plugin.dev.test.gone.tool", {"x": 1}),
        _tool("t8", "node:text_transform", {"op": "upper"}),
    ]
    edges = [
        {"id": "e-au-t1", "source": "au", "target": "t1"},
        {"id": "t1->t1-out-1", "source": "t1", "target": "t1-out-1"},
        {"id": "e-n1-t2", "source": "n1", "target": "t2"},
        {"id": "e-n1-t6", "source": "n1", "target": "t6"},
        {"id": "e-n1-t5", "source": "n1", "target": "t5"},
        {"id": "e-v2-t9", "source": "v2", "target": "t9"},
        {"id": "e-au-t9", "source": "au", "target": "t9"},
        {"id": "t9->t9-out-1", "source": "t9", "target": "t9-out-1"},
        {"id": "e-n1-t10", "source": "n1", "target": "t10"},
        #: 连进工具格、却没被绑定用到的线:随它去掉。
        {"id": "e-v1-t2", "source": "v1", "target": "t2"},
    ]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟升级前落库的画布。
        board = Board(workspace_id=ws, name="旧板", revision=5, canvas={"items": items, "edges": edges})
        untouched = Board(workspace_id=ws, name="新板", revision=2, canvas={"items": [
            {"id": "n", "kind": "note", "x": 0, "y": 0, "text": "hi", "form": {"producer": "write"}}], "edges": []})
        db.add_all([board, untouched])
        db.commit()
        board_id, untouched_id = board.id, untouched.id
        before = board.canvas

    _migrate_board_tool_cells_become_abilities()
    once, revision = _canvas(board_id)
    _migrate_board_tool_cells_become_abilities()
    assert _canvas(board_id) == (once, revision), "再跑一次不该再动(版本号也不该再涨)"

    by_id = {item["id"]: item for item in once["items"]}
    assert not any(one["kind"] == "action" for one in once["items"])
    for gone in ("t1", "t2", "t6", "t4", "t9"):
        assert gone not in by_id, gone
    #: 设置搬进宿主的 `abilities`,宿主自己的表单不动,产出者排最后。
    assert by_id["au"]["form"] == {"abilities": {"node:transcribe_asset": {"config": {"engine": "funasr"}, "bindings": {}}}}
    assert by_id["n1"]["form"] == {"abilities": {"node:translate": {"config": {"target_lang": "en"}, "bindings": {}}},
                                   "producer": "write"}
    assert by_id["v1"]["form"] == {"abilities": {"node:video_to_gif": {"config": {"fps": 12}, "bindings": {}}}}
    assert by_id["v2"]["form"] == {"prompt": "旧的", "abilities": {
        mux: {"config": {"level": "high"}, "bindings": {"voice": [{"from": "au"}]}}}, "producer": "generate"}
    assert by_id["v2"]["asset_id"] == "vid2" and by_id["au"]["asset_id"] == "aud"
    #: 生成器:同一个 id、位置、大小、名字的图片空格子。
    slot = by_id["t10"]
    assert {key: slot[key] for key in ("kind", "x", "y", "width", "height", "title")} == {
        "kind": "image", "x": 400, "y": 0, "width": 260, "height": 180, "title": "出图"}
    assert slot["form"] == {"config": {"instance_id": "i-1"}, "bindings": {"prompt": [{"from": "n1"}]}, "producer": draw}
    #: 便签:同一个 id、位置、大小、名字;正文说清楚、设置附在后面;运行态不带。
    for note_id in ("t5", "t3", "t7", "t8"):
        note = by_id[note_id]
        assert note["kind"] == "note" and note["form"] == {"producer": "write"} and "run" not in note, note_id
        assert (note["x"], note["width"]) == (400, 260) and "原来的设置" in note["text"], note_id
    assert by_id["t5"]["title"] == "日文那版" and '"ja"' in by_id["t5"]["text"] and "n1" in by_id["t5"]["text"]
    assert "「翻译」" in by_id["t3"]["text"] and "操作条" in by_id["t3"]["text"]
    assert "「文本处理」" in by_id["t8"]["text"] and "工作流" in by_id["t8"]["text"]
    #: 产出一格不动。
    for kept in ("t1-out-1", "t9-out-1"):
        assert by_id[kept] == next(one for one in before["items"] if one["id"] == kept), kept

    pairs = sorted((edge["source"], edge["target"]) for edge in once["edges"])
    assert pairs == sorted([
        ("au", "t1-out-1"),  # 连向产出的线改从宿主连出
        ("n1", "t5"),  # 改成便签的:线都还在
        ("au", "v2"),  # 多输入工具的另一个输入改连进宿主
        ("v2", "t9-out-1"),
        ("n1", "t10"),  # 生成器接提示词的那根线还在
    ]), pairs
    assert len({edge["id"] for edge in once["edges"]}) == len(once["edges"])
    assert revision == 6, "升级那一刻还开着这张板的客户端要撞 409"
    assert _canvas(untouched_id)[1] == 2, "没有工具格的板一个字不动"
    #: 迁完的画布照现在的规则存得下。
    normalize_canvas(once)
