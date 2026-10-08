"""清单、版本号、工作流文件、画板快照、索引条目与报错语言。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosael_formats import board_snapshot, i18n, plugin_index, versions, workflow_file
from mosael_formats.plugin_manifest import ManifestError, parse

REPO = Path(__file__).resolve().parents[3]
SHA_A = "a" * 64
SHA_B = "b" * 64


# ---------------- i18n ----------------


def test_每个_key_两种语言都有() -> None:
    for key, entry in i18n.MESSAGES.items():
        assert set(entry) == set(i18n.LOCALES), key
        assert all(text.strip() for text in entry.values()), key


def test_报错跟着此刻的语言说() -> None:
    error = ManifestError("pluginErr_manifestMissingField", path="p", field="id")
    token = i18n.CURRENT_LOCALE.set("en")
    try:
        assert str(error) == "Plugin manifest p is missing a required field: id"
    finally:
        i18n.CURRENT_LOCALE.reset(token)
    assert "缺少必填字段" in str(error)


def test_数据自带的文案按语言挑() -> None:
    assert i18n.pick_text({"zh": "你好", "en": "Hello"}, "en-US") == "Hello"
    assert i18n.pick_text({"en": "Hello"}, "zh") == "Hello"
    assert i18n.pick_text("plain", "en") == "plain"


# ---------------- 清单 ----------------


def test_清单解析按当时的语言挑名字() -> None:
    raw = {"id": "a.b", "version": "1.0.0", "name": {"zh": "中文名", "en": "English"}}
    token = i18n.CURRENT_LOCALE.set("en")
    try:
        assert parse(raw, "x").name == "English"
    finally:
        i18n.CURRENT_LOCALE.reset(token)


def test_一句话简介按语言挑_介绍取第一条工具集() -> None:
    raw = {
        "id": "a.b", "version": "1.0.0", "name": "n",
        "summary": {"zh": "一句话", "en": "One line"},
        "toolsets": [{"id": "s", "description": {"zh": "长的介绍", "en": "A longer introduction"}}],
    }
    token = i18n.CURRENT_LOCALE.set("en")
    try:
        manifest = parse(raw, "x")
        assert (manifest.summary, manifest.description) == ("One line", "A longer introduction")
    finally:
        i18n.CURRENT_LOCALE.reset(token)
    assert parse({"id": "a.b", "version": "1.0.0", "name": "n"}, "x").summary == ""


def test_交出来的那一类东西叫什么_按语言挑_不写是空串() -> None:
    """ComfyUI 交的是工作流和表单:插件页那一行、清单标题、搜索框、刷新按钮都按它说,不叫「模型」(宿主不写死哪一家)。"""
    raw = {"id": "a.b", "version": "1.0.0", "name": "n", "provides": ["generation"], "runtime": {"kind": "process", "entry": "m.py"},
           "tools": {"declare": [{"name": "gen", "provides": ["generation"]}]},
           "generation_noun": {"zh": "工作流", "en": "workflows"}}
    token = i18n.CURRENT_LOCALE.set("en")
    try:
        assert parse(raw, "x").generation_noun == "workflows"
    finally:
        i18n.CURRENT_LOCALE.reset(token)
    assert parse({**raw, "generation_noun": None}, "x").generation_noun == ""


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ({"version": "1"}, "pluginErr_manifestMissingField"),
        # 一句话简介写成一段:卡片只剩省略号。**每种语言都查** —— 只查挑出来的那种,换个界面语言才露馅。
        ({"id": "a", "version": "1", "name": "n", "summary": "长" * 141}, "pluginErr_manifestSummaryTooLong"),
        ({"id": "a", "version": "1", "name": "n", "summary": {"zh": "短", "en": "x" * 141}}, "pluginErr_manifestSummaryTooLong"),
        # 交出来的那一类东西叫什么:一个词;没认领生成能力的插件写了是白写
        ({"id": "a", "version": "1", "name": "n", "generation_noun": "工作流"}, "pluginErr_manifestGenerationNoun"),
        ({"id": "a", "version": "1", "name": "n", "provides": ["generation"], "runtime": {"kind": "process", "entry": "m.py"},
          "tools": {"declare": [{"name": "gen", "provides": ["generation"]}]},
          "generation_noun": {"zh": "工作流", "en": "x" * 17}}, "pluginErr_manifestGenerationNoun"),
        ({"id": "../x", "version": "1", "name": "n"}, "pluginErr_manifestBadId"),
        ({"id": "a", "version": "1", "name": "n", "instance": {"credentials": [{"key": "MOSAEL_X"}]}},
         "pluginErr_manifestReservedKey"),
        # 出站代理是宿主替连接定的:配置里一个 `https_proxy` 大写后正好是那一格,填了也不会生效。
        ({"id": "a", "version": "1", "name": "n", "instance": {"config": [{"key": "https_proxy"}]}},
         "pluginErr_manifestReservedKey"),
        ({"id": "a", "version": "1", "name": "n", "instance": {"credentials": [{"key": "NODE_USE_ENV_PROXY"}]}},
         "pluginErr_manifestReservedKey"),
        ({"id": "a", "version": "1", "name": "n", "tools": {"declare": [{"name": "a.b"}]}},
         "pluginErr_manifestBadToolName"),
        # 认领调用类能力的工具是普通工具(ADR 0033):素材入参要按契约写,智能体、工作流才知道那一格交一份素材。
        ({"id": "a", "version": "1", "name": "n", "provides": ["document_parse"], "runtime": {"kind": "process", "entry": "m.py"},
          "tools": {"declare": [{"name": "p", "provides": ["document_parse"],
                                 "input_schema": {"type": "object", "properties": {"file": {"type": "string"}}}}]}},
         "pluginErr_manifestCapabilityContract"),
        ({"id": "a", "version": "1", "name": "n", "provides": ["transcription"], "runtime": {"kind": "process", "entry": "m.py"},
          "tools": {"declare": [{"name": "p", "provides": ["transcription"], "input_schema": {"type": "object", "properties": {
              "file": {"type": "string", "format": "asset", "x-media": ["audio", "video"], "x-audio": "original"}}}}]}},
         "pluginErr_manifestCapabilityContract"),
        ({"id": "a", "version": "1", "name": "n", "tools": {"declare": [{"name": "p", "input_schema": {
            "type": "object", "properties": {"f": {"type": "string", "format": "asset", "x-audio": "mp3"}}}}]}},
         "pluginErr_manifestBadAudioPrepare"),
        # node.config 把一格标成素材,input_schema 里却不是:表单给素材选择器,插件收到的却是素材 id
        ({"id": "a", "version": "1", "name": "n", "tools": {"declare": [{"name": "p",
            "input_schema": {"type": "object", "properties": {"img": {"type": "string"}}},
            "node": {"config": {"img": {"type": "template", "format": "asset"}}}}]}},
         "pluginErr_manifestNodeAssetNotInSchema"),
        # overrides 给声明过的工具换的 node 块是同一件事(它整块顶替工具自己的 node)
        ({"id": "a", "version": "1", "name": "n", "tools": {
            "declare": [{"name": "p", "input_schema": {"type": "object", "properties": {"img": {"type": "string"}}}}],
            "overrides": {"p": {"node": {"config": {"img": {"type": "template", "format": "asset"}}}}}}},
         "pluginErr_manifestNodeAssetNotInSchema"),
    ],
)
def test_清单的硬规矩(raw: dict, key: str) -> None:
    with pytest.raises(ManifestError) as caught:
        parse(raw, "x")
    assert caught.value.key == key


def test_仓库里的插件清单全部合格() -> None:
    manifests = sorted((REPO / "plugins").glob("*/*/mosael.plugin.json"))
    assert manifests, "找不到仓库里的插件清单"
    for path in manifests:
        parse(json.loads(path.read_text(encoding="utf-8")), str(path))


def test_仓库里的插件_每个工具参数都有中英文名字() -> None:
    """工具的参数在插件页「试一下」、工作流节点的表单里显示成一格。没写 `title` 的,宿主只能拿工作流的通用字段名
    兜底 —— 恰好在通用词表里的(标题、画幅、画质)是中文,别的(Subtitle、Steps、Summary、Theme)露出参数的键名,
    同一张表单中英混杂(用户截图:Manim 讲解视频)。仓库里的插件是给别人照着写的样板,每一格都写全。"""
    missing: list[str] = []

    def walk(props: dict, where: str) -> None:
        for key, spec in (props or {}).items():
            title = spec.get("title")
            if not (isinstance(title, dict) and title.get("zh") and title.get("en")):
                missing.append(f"{where}{key}")
            if spec.get("type") == "array" and isinstance(spec.get("items"), dict):
                walk(spec["items"].get("properties") or {}, f"{where}{key}[].")
            if spec.get("type") == "object":
                walk(spec.get("properties") or {}, f"{where}{key}.")

    for path in sorted((REPO / "plugins").glob("*/*/mosael.plugin.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for tool in (manifest.get("tools") or {}).get("declare") or []:
            walk((tool.get("input_schema") or {}).get("properties") or {}, f"{path.parent.name} · {tool['name']}: ")
    assert missing == [], "这些参数没有按语言写 title:\n" + "\n".join(missing)


# ---------------- 版本号 ----------------


def test_版本号的先后() -> None:
    assert versions.compare("0.10.0", "0.9.0") == 1
    assert versions.compare("1.0.0-beta", "1.0.0") == -1
    assert versions.compare("v1.2", "1.2.0") == 0
    assert versions.compare("latest", "1.0.0") is None
    assert versions.is_semver("1.2.3") and not versions.is_semver("1.2.3.4")


# ---------------- 索引条目 ----------------


def test_索引条目和官网那份_registry_json_同形() -> None:
    registry = json.loads((REPO / "website/public/plugins/registry.json").read_text(encoding="utf-8"))
    for one in registry["plugins"]:
        assert tuple(one) == plugin_index.ENTRY_KEYS
    raw = {
        "id": "a.b",
        "version": "1.0.0",
        "name": "n",
        "tools": {"declare": [{"name": "t", "read_only": True}, {"name": "u"}], "default_effects": "paid"},
    }
    entry = plugin_index.index_entry(raw, download="https://x.test/a.zip", bundled=False)
    assert tuple(entry) == plugin_index.ENTRY_KEYS
    #: 一句话简介原样带过去(可以按语言分),由读的一方挑语言;没写就是空串。
    assert entry["summary"] == ""
    assert plugin_index.index_entry({**raw, "summary": {"zh": "一句话"}}, download="", bundled=False)["summary"] == {"zh": "一句话"}
    assert [tool["effects"] for tool in entry["tools"]] == ["none", "paid"]


# ---------------- 工作流文件 ----------------


def test_官网上的官方工作流文件全部合格() -> None:
    files = sorted((REPO / "website/public/workflows").glob("*.mosael-workflow.json"))
    assert files
    for path in files:
        envelope = workflow_file.read_workflow_file(json.loads(path.read_text(encoding="utf-8")))
        workflow_file.check_graph(envelope.graph)
        assert workflow_file.summarize_graph(envelope.graph).node_count > 0


def test_不是工作流文件() -> None:
    with pytest.raises(workflow_file.WorkflowFileError) as caught:
        workflow_file.read_workflow_file({"format": "something-else", "graph": {}})
    assert caught.value.key == "workflowFileErr_notWorkflowFile"


def test_版本比我们新() -> None:
    with pytest.raises(workflow_file.WorkflowFileError) as caught:
        workflow_file.read_workflow_file({"format": "mosael-workflow", "version": 99, "graph": {}})
    assert caught.value.key == "workflowFileErr_tooNew"


def test_图的骨架() -> None:
    with pytest.raises(workflow_file.WorkflowFileError):
        workflow_file.check_graph({"nodes": [{"id": "a", "type": "x"}], "edges": [{"source": "a", "target": "b"}]})
    with pytest.raises(workflow_file.WorkflowFileError):
        workflow_file.check_graph({"nodes": [{"id": "a", "type": "x"}, {"id": "a", "type": "y"}]})


def test_认出运行代码的节点_连内嵌子图里的也算() -> None:
    graph = {
        "nodes": [
            {"id": "s", "type": "start"},
            {"id": "p", "type": "plugin.dev.example.hello.say_hello"},
            {"id": "l", "type": "loop_foreach", "config": {"body": {"nodes": [{"id": "c", "type": "code"}], "edges": []}}},
        ],
        "edges": [{"source": "s", "target": "l"}],
    }
    workflow_file.check_graph(graph)
    summary = workflow_file.summarize_graph(graph)
    assert summary.node_count == 4
    assert summary.has_code and summary.code_node_types == ["code"]
    assert summary.plugin_ids == ["dev.example.hello"]


# ---------------- 画板快照 ----------------


def snapshot(**overrides) -> dict:
    base = {
        "schema": board_snapshot.SCHEMA,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "items": [
            {"id": "i1", "kind": "image", "x": 0, "y": 0, "width": 260, "height": 180, "title": "图",
             "media": {"sha256": SHA_A, "content_type": "image/png", "width": 1024, "height": 1024, "thumb_sha256": SHA_B}},
            {"id": "n1", "kind": "note", "x": 300, "y": 0, "width": 220, "height": 140, "text": "…", "color": "yellow"},
            {"id": "d1", "kind": "document", "title": "文", "markdown": "# 正文", "revision": 13},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "i1"}],
    }
    base.update(overrides)
    return base


def test_合格的快照收集到全部哈希() -> None:
    summary = board_snapshot.validate_snapshot(snapshot())
    assert summary.item_count == 3
    assert summary.hashes == {SHA_A, SHA_B}
    assert summary.images[0].thumb_sha256 == SHA_B


@pytest.mark.parametrize(
    "bad",
    [
        {"schema": "mosael.board-snapshot/2"},
        {"extra": 1},
        {"viewport": {"x": 0, "y": 0, "zoom": 0}},
        {"items": [{"id": "a", "kind": "image", "media": {"sha256": "NOT-A-HASH"}}]},
        {"items": [{"id": "a", "kind": "image", "x": float("inf")}]},
        {"items": [{"id": "a", "kind": "note"}, {"id": "a", "kind": "note"}]},
        {"items": [{"id": "a", "kind": "image", "src": "file:///Users/me/a.png"}]},
        {"edges": [{"id": "e", "source": "i1", "target": "missing"}]},
    ],
)
def test_不合格的快照(bad: dict) -> None:
    with pytest.raises(board_snapshot.SnapshotError):
        board_snapshot.validate_snapshot(snapshot(**bad))


def test_格子数上限() -> None:
    items = [{"id": f"n{i}", "kind": "note"} for i in range(5)]
    with pytest.raises(board_snapshot.SnapshotError) as caught:
        board_snapshot.validate_snapshot(snapshot(items=items, edges=[]), max_items=4)
    assert caught.value.key == "snapshotErr_tooManyItems"


def test_overrides里多标的素材_升级时去掉_升完解析得过() -> None:
    """规则收紧到 overrides 之后,装着的 v5 清单(那时 overrides 不查)要能被升级链改合格,否则读它就抛。"""
    from mosael_formats.plugin_manifest_upgrade import MANIFEST_VERSION, upgrade

    raw = {"id": "a", "version": "1", "name": "n", "manifest_version": 5, "runtime": {"kind": "process", "entry": "m.py"},
           "tools": {"declare": [{"name": "p", "input_schema": {"type": "object", "properties": {
               "img": {"type": "string"}, "ok": {"type": "array", "items": {"type": "string", "format": "asset"}}}}}],
               "overrides": {"p": {"node": {"config": {"img": {"type": "template", "format": "asset"},
                                                       "ok": {"format": "asset"}}}},
                             "mcp_only": {"node": {"config": {"x": {"format": "asset"}}}}}}}
    assert upgrade(raw) and raw["manifest_version"] == MANIFEST_VERSION
    overrides = raw["tools"]["overrides"]
    assert "format" not in overrides["p"]["node"]["config"]["img"]
    assert overrides["p"]["node"]["config"]["ok"]["format"] == "asset", "两边一致的不动"
    assert overrides["mcp_only"]["node"]["config"]["x"]["format"] == "asset", "没有声明可对照的不动"
    parse(raw, "x")


def test_清单v7_skills改名toolsets_幂等_两个都在时以toolsets为准() -> None:
    """ADR 0040 §8:「技能」现在指智能体按需读的做法,插件清单里那份工具目录改叫工具集。"""
    from mosael_formats.plugin_manifest_upgrade import MANIFEST_VERSION, upgrade

    assert MANIFEST_VERSION >= 7
    skills = [{"id": "s", "description": {"zh": "长的介绍", "en": "A longer introduction"}}]
    runtime = {"kind": "process", "entry": "m.py"}
    raw = {"id": "a", "version": "1", "name": "n", "manifest_version": 6, "runtime": runtime, "skills": skills}
    assert upgrade(raw)
    assert raw == {"id": "a", "version": "1", "name": "n", "manifest_version": MANIFEST_VERSION, "runtime": runtime,
                   "toolsets": skills}
    assert not upgrade(raw), "升过的不再动"
    assert parse(raw, "x").description == "长的介绍"

    both = {"id": "a", "version": "1", "name": "n", "manifest_version": 6, "skills": [{"id": "old"}],
            "toolsets": [{"id": "new"}]}
    upgrade(both)
    assert "skills" not in both and both["toolsets"] == [{"id": "new"}]


def test_当前版本的清单里不认skills这个键() -> None:
    """只认当前形状:v7 的清单写 `skills` 就是没写工具集(读取路径里没有「老写法」那一支)。"""
    manifest = parse({"id": "a", "version": "1", "name": "n", "manifest_version": 7,
                      "skills": [{"id": "s", "description": "x"}]}, "x")
    assert manifest.toolsets == [] and manifest.description == ""


# ---------------- 本机服务(清单版本 8,ADR 0041) ----------------


def _with_service(**changes: object) -> dict:
    """一份声明了本机服务的进程插件清单:有 `server_url` 那一格配置、有回答 service_* 的那个工具。"""
    raw: dict = {
        "id": "a.b", "version": "1.0.0", "name": "n", "manifest_version": 8,
        "runtime": {"kind": "process", "entry": "main.py"},
        "instance": {"config": [{"key": "server_url", "label": "地址", "type": "string"}]},
        "tools": {"declare": [{"name": "gen", "description": "x"}]},
        "services": [{"key": "comfyui", "title": {"zh": "ComfyUI 服务", "en": "ComfyUI"}, "tool": "gen"}],
    }
    raw.update(changes)
    return raw


def test_清单v8_本机服务按声明解析_标题按语言挑() -> None:
    token = i18n.CURRENT_LOCALE.set("en")
    try:
        manifest = parse(_with_service(), "x")
    finally:
        i18n.CURRENT_LOCALE.reset(token)
    assert [(one.key, one.title, one.tool) for one in manifest.services] == [("comfyui", "ComfyUI", "gen")]
    assert manifest.service("comfyui") is manifest.services[0]
    assert manifest.service("nope") is None
    assert parse({"id": "a", "version": "1", "name": "n"}, "x").services == [], "没写就是没有服务"


@pytest.mark.parametrize(
    ("services", "key"),
    [
        ({"key": "comfyui"}, "pluginErr_manifestServicesShape"),
        (["comfyui"], "pluginErr_manifestServicesShape"),
        ([{"key": "Comfy UI", "title": "t", "tool": "gen"}], "pluginErr_manifestServiceBadKey"),
        ([{"title": "t", "tool": "gen"}], "pluginErr_manifestServiceBadKey"),
        ([{"key": "comfyui", "title": "t", "tool": "gen"}, {"key": "comfyui", "title": "u", "tool": "gen"}],
         "pluginErr_manifestServiceDuplicate"),
        ([{"key": "comfyui", "title": " ", "tool": "gen"}], "pluginErr_manifestMissingField"),
        ([{"key": "comfyui", "title": "t", "tool": "nope"}], "pluginErr_manifestServiceUnknownTool"),
        ([{"key": "comfyui", "title": "t"}], "pluginErr_manifestServiceUnknownTool"),
    ],
)
def test_本机服务写错在装的那一刻就说(services: object, key: str) -> None:
    with pytest.raises(ManifestError) as caught:
        parse(_with_service(services=services), "x")
    assert caught.value.key == key


def test_本机服务只能由进程插件声明() -> None:
    raw = _with_service(runtime={"kind": "mcp", "url": "https://mcp.example.com"})
    with pytest.raises(ManifestError) as caught:
        parse(raw, "x")
    assert caught.value.key == "pluginErr_manifestServiceNeedsProcess"


@pytest.mark.parametrize(
    "config",
    [[], [{"key": "host", "label": "地址"}], [{"key": "server_url", "label": "地址", "type": "number"}]],
)
def test_声明了本机服务就得有_server_url_那一格文本配置(config: list) -> None:
    """宿主把算出来的地址写进 `server_url`:没有这一格(或它不是文本),插件、工作台、模型库就读不到本机服务的地址。"""
    with pytest.raises(ManifestError) as caught:
        parse(_with_service(instance={"config": config}), "x")
    assert caught.value.key == "pluginErr_manifestServiceNeedsAddress"


def test_清单v8_老清单就是没有服务_手写过的同名键升级时丢掉() -> None:
    """版本 8 之前 `services` 不是字段:升级不替它补任何东西;手写过一个(当时没人校验)就丢掉,免得按新规矩整份装不上。"""
    from mosael_formats.plugin_manifest_upgrade import MANIFEST_VERSION, upgrade

    assert MANIFEST_VERSION == 8
    runtime = {"kind": "process"}
    plain = {"id": "a", "version": "1", "name": "n", "manifest_version": 7, "runtime": runtime}
    assert upgrade(plain)
    assert plain == {"id": "a", "version": "1", "name": "n", "manifest_version": 8, "runtime": runtime}

    stray = {"id": "a", "version": "1", "name": "n", "manifest_version": 7, "services": "随手写的"}
    assert upgrade(stray)
    assert "services" not in stray and parse(stray, "x").services == []
    assert not upgrade(stray), "升过的不再动"

    current = _with_service()
    assert not upgrade(current), "版本 8 的清单不经过这一步"
    assert parse(current, "x").services[0].key == "comfyui"
