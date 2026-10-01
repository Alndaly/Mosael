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


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ({"version": "1"}, "pluginErr_manifestMissingField"),
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
