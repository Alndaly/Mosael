"""画板上**一个概念一个入口**:和生成模型是同一件事的插件工具不再是工具格(ADR 0021 修订)。

ComfyUI 的一张工作流既是生成模型(图片 / 视频格的模型选择器里),又是一个工具(画板的「添加」菜单里)——
同一件事两个入口。只有工具做得到的(交回全部输出节点、文字产出、拿 alpha 当蒙版、取回预览)留给工具;
生成表达得了的(只有一个图 / 视频 / 音频输出节点)在画板上只留生成:结果落在原位、有张数、用量、6 小时。

宿主不认识 ComfyUI:插件报出的工具声明 `mirrors`(见 docs/PLUGIN_MANIFEST),规矩是
`boards.transforms.content_transform_gap` 的 `mirrored_by_generation` —— 声明了、而且点运行的人在生成目录里
用得上那个模型(同一条连接下的)。存着的这种工具格由对账改写成生成格(boards.plugin_references)。

另外钉住 `wiring_outputs`:只给连线用的输出从不落板(一次运行不再多出一张重复的图和几张 JSON / 摘要便签)。
"""

from __future__ import annotations

from pathlib import Path

from tests.test_board_producers import _install_plugin, _me, _run_tool, _workspace
from tests.util import fresh_client, second_client

PACKAGE = "dev.test.boardtools"
MIRRORED = "wf_portrait"
NOT_MIRRORED = "wf_upscale"

#: 两个运行时报出的工具(形状照 ComfyUI 插件报的那种):一个和生成模型 portrait.json 是同一件事,
#: 一个有两个输出节点(只有工具交得全)。
REPORTED = [
    {
        "name": MIRRORED,
        "label": "工作流 · portrait",
        "description": "在 ComfyUI 上原样跑「portrait」这张工作流。",
        "input_schema": {"type": "object", "properties": {
            "prompt": {"type": "string"},
            "image_10": {"type": "string", "format": "asset", "x-media": "image"},
            "steps_3": {"type": "integer"},
            "width": {"type": "integer"},
        }},
        "node": {"outputs": ["image_9", "asset_id", "asset_ids", "summary", "prompt_id"],
                 "output_types": {"image_9": "asset", "asset_id": "asset", "asset_ids": "json", "summary": "text",
                                  "prompt_id": "text"},
                 "board_outputs": ["image_9"], "wiring_outputs": ["asset_id", "asset_ids", "summary", "prompt_id"]},
        "mirrors": {"generation_model": "portrait.json", "kind": "image", "prompt": "prompt",
                    "parameters": {"steps_3": "3.steps"}, "sources": {"image_10": "reference_image"}},
    },
    {
        "name": NOT_MIRRORED,
        "label": "工作流 · upscale",
        "description": "在 ComfyUI 上原样跑「upscale」这张工作流。",
        "input_schema": {"type": "object", "properties": {
            "image_1": {"type": "string", "format": "asset", "x-media": "image"}}, "required": ["image_1"]},
        "node": {"outputs": ["image_4", "image_5", "asset_id"],
                 "output_types": {"image_4": "asset", "image_5": "asset", "asset_id": "asset"},
                 "board_outputs": ["image_4", "image_5"], "wiring_outputs": ["asset_id"]},
    },
]


def _connect_reporting(owner_id: str, *, with_model: bool, name: str = "我的 ComfyUI") -> tuple[str, str]:
    """给 `owner_id` 接一条连接,它报出上面两个工具;`with_model` 时它的生成目录里有 portrait.json。
    返回 (连接 id, 生成连接 id)。"""
    from app.core.db import SessionLocal
    from app.db.models import PluginInstance, ProviderModel
    from app.domain.plugins.dynamic_tools import clean_mirror
    from app.domain.plugins.tools import refresh_tools
    from app.domain.providers import adopt_plugin_connection

    reported = [{**tool, **({"mirrors": clean_mirror(tool["mirrors"])} if "mirrors" in tool else {})} for tool in REPORTED]
    with SessionLocal() as db:
        instance = PluginInstance(package_id=PACKAGE, name=name, enabled=True, owner_user_id=owner_id,
                                  discovered_tools=reported)
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        profile = adopt_plugin_connection(db, plugin_instance_id=instance.id, owner_user_id=owner_id,
                                          vendor=f"plugin:{PACKAGE}", name=name, enabled=True)
        if with_model:
            db.add(ProviderModel(provider_profile_id=profile.id, model_id="portrait.json", display_name="portrait",
                                 enabled=True, capability_ids=["image"]))
        db.commit()
        return instance.id, profile.id


def test_只给连线用的输出从不落板() -> None:
    from app.domain.boards.tools import board_outputs, landing_outputs
    from app.domain.plugins.nodes import node_meta

    meta = node_meta(REPORTED[0])
    assert meta["wiring_outputs"] == ["asset_id", "asset_ids", "summary", "prompt_id"]
    assert landing_outputs(meta) == ["image_9"]
    #: 没点名落板的:缺省是「全部不是只给连线用的」,不再是全部。
    unnamed = node_meta({**REPORTED[0], "node": {k: v for k, v in REPORTED[0]["node"].items() if k != "board_outputs"}})
    assert landing_outputs(unnamed) == ["image_9"]
    #: 点了名又说是给连线用的:两句话打架,信后者。
    both = node_meta({**REPORTED[0], "node": {**REPORTED[0]["node"], "board_outputs": ["image_9", "asset_id"]}})
    assert landing_outputs(both) == ["image_9"]
    collected = {"image_9": "a1", "asset_id": "a1", "asset_ids": ["a1"], "summary": "1 张图", "prompt_id": "p1"}
    assert board_outputs(meta, collected) == [{"type": "asset", "asset_id": "a1"}], "一次运行只落一张图"


def test_没声明类型的输出_值是这一轮收进来的文件就是素材() -> None:
    """ComfyUI 的自定义输出节点声明成 `output_12`(类型不明):交回的是那个节点的文件,落成素材格,
    而不是一张写着素材 id 的便签。"""
    from app.domain.boards.tools import board_outputs

    meta = {"outputs": ["image_9", "output_12", "asset_ids"], "output_types": {"image_9": "asset", "asset_ids": "json"},
            "wiring_outputs": ["asset_ids"]}
    assert board_outputs(meta, {"image_9": "a1", "output_12": "a2", "asset_ids": ["a1", "a2"]}) == [
        {"type": "asset", "asset_id": "a1"}, {"type": "asset", "asset_id": "a2"}]
    assert board_outputs(meta, {"output_12": "一段字", "asset_ids": []}) == [{"type": "text", "text": "一段字"}]


def test_同一件事的规矩() -> None:
    from app.domain.boards.transforms import content_transform_gap
    from app.domain.plugins.nodes import node_meta

    meta = node_meta(REPORTED[0])
    #: 没人告诉它「用得上」(棘轮、没有执行者)时照常是内容变换 —— 规矩本身不查库。
    assert content_transform_gap(meta) is None
    assert content_transform_gap(meta, generation_has=lambda mirror: False) is None
    assert content_transform_gap(meta, generation_has=lambda mirror: mirror["generation_model"] == "portrait.json") == (
        "mirrored_by_generation")
    #: 没声明 mirrors 的,用得上什么都不相干。
    assert content_transform_gap(node_meta(REPORTED[1]), generation_has=lambda mirror: True) is None
    #: 本来就不是内容变换的,说的是原来那个原因。
    report = node_meta({**REPORTED[0], "input_schema": {"type": "object", "properties": {}},
                        "node": {"outputs": ["summary"], "output_types": {"summary": "text"}}})
    assert content_transform_gap(report, generation_has=lambda mirror: True) == "no_content_output"


def test_形状不对的_mirrors_整条不认() -> None:
    from app.domain.plugins.dynamic_tools import clean_mirror

    assert clean_mirror({"kind": "image"}) is None
    assert clean_mirror({"generation_model": "a.json", "kind": "图片"}) is None
    assert clean_mirror("a.json") is None
    assert clean_mirror({"generation_model": "people/人像.json", "kind": "image", "parameters": {"steps_3": 3, "cfg_3": "3.cfg"},
                         "sources": {"image_10": "reference_image"}, "prompt": "prompt"}) == {
        "generation_model": "people/人像.json", "kind": "image", "prompt": "prompt",
        "parameters": {"cfg_3": "3.cfg"}, "sources": {"image_10": "reference_image"}}


def test_节点面板的说明里说一声用生成节点() -> None:
    from app.domain.plugins.nodes import node_meta

    assert "「AI 生成素材」节点选这个模型" in node_meta(REPORTED[0])["description"]
    assert "AI 生成素材" not in node_meta(REPORTED[1])["description"]


def test_用得上那个生成模型的人_画板上只有生成那一个入口(tmp_path: Path) -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import producers

    client = fresh_client()
    me = _me(client)
    mate = second_client("mate")
    other = _me(mate)
    _install_plugin(tmp_path)
    _connect_reporting(me, with_model=True)
    _connect_reporting(other, with_model=False, name="别人的 ComfyUI")

    with SessionLocal() as db:
        mine = {one.id for one in producers.list_producers(db, me)}
        theirs = {one.id for one in producers.list_producers(db, other)}
    mirrored, kept = f"node:plugin.{PACKAGE}.{MIRRORED}", f"node:plugin.{PACKAGE}.{NOT_MIRRORED}"
    assert mirrored not in mine and kept in mine, "我的生成目录里有 portrait.json:画板上走生成"
    assert mirrored in theirs and kept in theirs, "他的生成目录里没有那个模型:工具格照旧是唯一的入口"

    #: 画布上存着的那一格(对账还没改到):跑的时候说清楚去用生成,而不是「它不交出素材」。
    ws = _workspace(client)
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [
        {"id": "a1", "kind": "action", "x": 0, "y": 0, "form": {"producer": mirrored, "config": {}, "bindings": {}}}],
        "edges": []}})
    refused = _run_tool(client, created.json()["id"], ws, mirrored)
    assert refused.status_code == 400, refused.text
    assert "portrait" in refused.json()["detail"] and "生成" in refused.json()["detail"], refused.json()["detail"]


def test_存着的工具格改写成那种素材的生成格(tmp_path: Path) -> None:
    from app.core.db import SessionLocal
    from app.domain.boards.plugin_references import rewrite_mirrored_tools

    client = fresh_client()
    me = _me(client)
    _install_plugin(tmp_path)
    instance_id, profile_id = _connect_reporting(me, with_model=True)
    ws = _workspace(client)
    mirrored, kept = f"node:plugin.{PACKAGE}.{MIRRORED}", f"node:plugin.{PACKAGE}.{NOT_MIRRORED}"
    items = [
        {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "海边的柴犬"},
        {"id": "i1", "kind": "image", "x": 0, "y": 200, "asset_id": "asset-up"},
        #: 提示词接上游便签、参考图接上游图片、步数和宽度填了值、选了连接。
        {"id": "a1", "kind": "action", "x": 300, "y": 40, "width": 280, "height": 150, "title": "出图",
         "run": {"status": "succeeded"},
         "form": {"producer": mirrored, "config": {"prompt": "旧的字", "steps_3": "30", "width": "832",
                                                   "instance_id": instance_id},
                  "bindings": {"prompt": [{"from": "n1"}], "image_10": [{"from": "i1"}]}}},
        #: 手挑了参考图、写了提示词。
        {"id": "a2", "kind": "action", "x": 300, "y": 400,
         "form": {"producer": mirrored, "config": {"prompt": "一只猫", "image_10": "asset-picked"}, "bindings": {}}},
        #: 在跑的那一格等它落终态。
        {"id": "a3", "kind": "action", "x": 300, "y": 700, "run": {"status": "running", "job_id": "j1"},
         "form": {"producer": mirrored, "config": {}, "bindings": {}}},
        #: 没被生成取代的工具不动。
        {"id": "a4", "kind": "action", "x": 300, "y": 1000, "form": {"producer": kept, "config": {}, "bindings": {}}},
    ]
    edges = [{"id": "e1", "source": "n1", "target": "a1"}, {"id": "e2", "source": "i1", "target": "a1"}]
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": items, "edges": edges}})
    assert created.status_code == 200, created.text
    board_id, revision = created.json()["id"], created.json()["revision"]

    with SessionLocal() as db:
        assert rewrite_mirrored_tools(db) == 1
        assert rewrite_mirrored_tools(db) == 0, "改过的不再改:重复跑是安全的"

    board = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()
    assert board["revision"] == revision + 1, "开着这张板的旧快照要撞 409,不能把改写盖回去"
    by_id = {one["id"]: one for one in board["canvas"]["items"]}
    first = by_id["a1"]
    #: id、位置、名字不变;工具格的尺寸和上一轮的运行状态不带过去。
    assert (first["kind"], first["x"], first["y"], first["title"]) == ("image", 300, 40, "出图")
    assert "width" not in first and "run" not in first
    assert first["form"] == {
        #: 提示词接的是上游便签:留空,连线还在,生成格的面板照上游便签填(和运行时「绑定优先」同一个结果)。
        "prompt": "",
        "provider": f"plugin:{PACKAGE}",
        "provider_profile_id": profile_id,
        "model": "portrait.json",
        #: 宽度在生成里是一格「尺寸」,对不过去,丢掉。
        "parameters": {"3.steps": "30"},
        "source_assets": [{"asset_id": "asset-up", "role": "reference_image", "from": "i1"}],
        "producer": "generate",
    }
    assert {(edge["source"], edge["target"]) for edge in board["canvas"]["edges"]} == {("n1", "a1"), ("i1", "a1")}
    assert by_id["a2"]["kind"] == "image" and by_id["a2"]["form"]["prompt"] == "一只猫"
    assert by_id["a2"]["form"]["source_assets"] == [{"asset_id": "asset-picked", "role": "reference_image"}]
    assert by_id["a3"]["kind"] == "action", "在跑的那一格不动"
    assert by_id["a4"]["kind"] == "action" and by_id["a4"]["form"]["producer"] == kept


def test_说不准用哪条连接就不改(tmp_path: Path) -> None:
    """没选连接的工具格,两条连接(各自的生成连接)给出的不是同一个答案:不改 —— 和 replaces 同一条。"""
    from app.core.db import SessionLocal
    from app.domain.boards.plugin_references import rewrite_mirrored_tools

    client = fresh_client()
    me = _me(client)
    _install_plugin(tmp_path)
    _connect_reporting(me, with_model=True)
    _connect_reporting(me, with_model=True, name="另一台")
    ws = _workspace(client)
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [
        {"id": "a1", "kind": "action", "x": 0, "y": 0,
         "form": {"producer": f"node:plugin.{PACKAGE}.{MIRRORED}", "config": {}, "bindings": {}}}], "edges": []}})
    with SessionLocal() as db:
        assert rewrite_mirrored_tools(db) == 0
    board = client.get(f"/api/boards/{created.json()['id']}", params={"workspace_id": ws}).json()
    assert board["canvas"]["items"][0]["kind"] == "action"


def test_清单刷新之后和每次启动都跑这一步() -> None:
    """mirrors 只有插件报出清单之后才有:挂在清单刷新之后(和 replaces 同一个钩子)和启动对账上。"""
    import inspect

    from app.db import migrations
    from app.domain.boards import plugin_references

    assert "reconcile_plugin_tool_cells" in inspect.getsource(migrations._rewrite_replaced_plugin_tools)
    assert "rewrite_mirrored_tools" in inspect.getsource(plugin_references.reconcile_plugin_tool_cells)
    assert "reconcile_plugin_tool_cells" in inspect.getsource(plugin_references._after_refresh)
