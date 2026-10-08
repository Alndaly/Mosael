"""一张工作流几张表单(ADR 0045 第二步,插件 1.21.0):存储格式第 2 版、上一版的文件怎么改写过来、表单是工作流的几个入口。

- 读写:`extra.mosael = {"version": 2, "forms": [{id, title, description, graph_items}]}`,节点上 `properties.mosael.forms.<表单 id>`;
  `result` 按工作流记。新表单插件起 6 位 id;节点上指着不在的表单、`forms` 里 id 重复或不合规的不进任何表单,下次保存清掉;
- `upgrade` / `upgrade_marks`:上一版(第 1 版)改写过来,**只动 mosael 那几处**(逐字节核对),那台机器上刚改过的跳过;
- 入口:每张表单一个(`<路径>#<id>` / `wf_<12 位>_<id>`),按存的顺序挨在完整工作流后面;一次性的改名只报 id 是 `app` 的那张;
- 上一版的文件还没改写时,指着 `#app` 的格子和工具说清楚「到工作流库里升级」,不说成「表单没了」;目录报这台上还有几张要升级。
- `explain`:宿主记着、目录里没有的入口为什么不在 —— 表单是旧格式(要升级)、表单删了、工作流不在了,各说各的。

纯函数的部分不连任何服务;要写文件的对着 tests/fake_comfyui.py。
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from tests.fake_comfyui import OBJECT_INFO, FakeComfyUI, multi_reference_ui

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
ENTRY = "tools/main.py"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service",
            "shared_models", "workflows", "tooling", "library", "sources", "install", "model_files", "families",
            "workflow_library", "workflow_import", "app_form", "json_style")

QUICK = {"id": "app", "title": "快速出图", "description": "", "items": [{"node": "6", "input": "text", "main": True}]}
FINE = {"title": "精调", "description": "再露步数", "items": [
    {"node": "6", "input": "text", "main": True}, {"node": "3", "input": "steps", "label": "步数"}, {"node": "", "input": "size"}]}


@pytest.fixture(scope="module")
def app_form():
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import app_form as module

        yield module
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _v1(ui: dict[str, Any], *, app: bool = True) -> dict[str, Any]:
    """上一版(1.20 之前)存的样子:图上 `{"version": 1, "app": …}`,节点上 `expose`;#17 标成结果。"""
    stored = copy.deepcopy(ui)
    stored["extra"]["mosael"] = {"version": 1, **({"app": {"title": "快速出图", "description": "只填一句话",
                                                           "graph_items": {"seed": {"order": 1}}}} if app else {})}
    for node in stored["nodes"]:
        if node["id"] == 6:
            node["properties"]["mosael"] = {"expose": {"text": {"order": 0, "main": True}}}
        if node["id"] == 17:
            node["properties"]["mosael"] = {"result": True}
    return stored


# --- 读写 ---------------------------------------------------------------------


def test_两张表单_按存的顺序读回来_各有各的项_结果按工作流记(app_form) -> None:
    ui = app_form.apply(multi_reference_ui(), [QUICK, FINE], ["17"])
    head = ui["extra"]["mosael"]
    assert head["version"] == 2 and [one["id"] for one in head["forms"]][0] == "app"
    new_id = head["forms"][1]["id"]
    assert re.fullmatch(r"[a-z0-9]{6}", new_id), "新表单插件起 6 位随机 id"
    by_id = {node["id"]: node for node in ui["nodes"]}
    assert by_id[6]["properties"]["mosael"] == {"forms": {"app": {"text": {"order": 0, "main": True}},
                                                          new_id: {"text": {"order": 0, "main": True}}}}
    assert by_id[3]["properties"]["mosael"] == {"forms": {new_id: {"steps": {"order": 1, "label": "步数"}}}}
    assert by_id[17]["properties"]["mosael"] == {"result": True}, "「以后只要这张」不属于哪一张表单"
    marks = app_form.read(ui)
    assert [(one.id, one.title) for one in marks.forms] == [("app", "快速出图"), (new_id, "精调")]
    assert [mark.key for mark in marks.forms[1].exposed] == ["6.text", "3.steps", "size"]
    assert marks.results == ("17",) and marks.stray == ()
    again = app_form.apply(ui, [FINE | {"id": new_id}, QUICK], ["17"])
    assert [one.id for one in app_form.read(again).forms] == [new_id, "app"], "换顺序只换顺序,id 跟着表单走"


def test_写的时候_id重复或不合规就拒_什么都不写(app_form) -> None:
    from lines import ComfyError

    for forms in ([QUICK, QUICK], [QUICK | {"id": "Bad-Id"}], [QUICK | {"id": "toolongid"}]):
        with pytest.raises(ComfyError, match="id"):
            app_form.apply(multi_reference_ui(), forms, [])
    with pytest.raises(ComfyError, match="20"):
        app_form.apply(multi_reference_ui(), [{"title": str(n), "items": []} for n in range(21)], [])


def test_图上的标记不是这一版_写的时候就拒_不当成没有表单重写(app_form) -> None:
    """第 1 版、更新版插件写的、认不出版本的:这一版读成「没有表单」,照它重写就把作者的表单抹掉了(PLG-1)。第 1 版先经
    `upgrade` 改写;`extra.mosael` 根本不是对象(手改坏的)里没有能丢的东西,照常覆盖。"""
    from lines import ComfyError

    for head, said in (({"version": 1, "app": {"title": "快速出图"}}, "旧格式"), ({"version": 1}, "旧格式"),
                       ({"version": 3, "forms": []}, "第 3 版"), ({"forms": []}, "第 \\? 版")):
        ui = multi_reference_ui()
        ui["extra"]["mosael"] = head
        before = copy.deepcopy(ui)
        for forms, results in (([QUICK], []), ([], ["17"]), ([], [])):
            with pytest.raises(ComfyError, match=said):
                app_form.apply(ui, forms, results)
        assert ui == before
    upgraded = app_form.upgrade(_v1(multi_reference_ui()))
    assert app_form.read(app_form.apply(upgraded, [QUICK], ["17"])).forms[0].id == "app", "改写过来就能改了"
    broken = multi_reference_ui()
    broken["extra"]["mosael"] = "坏了"
    assert app_form.apply(broken, [QUICK], [])["extra"]["mosael"]["version"] == 2


def test_对不上任何一张表单的标记_不进表单_列成失效_下次保存清掉(app_form) -> None:
    ui = app_form.apply(multi_reference_ui(), [QUICK], [])
    by_id = {node["id"]: node for node in ui["nodes"]}
    by_id[3]["properties"]["mosael"] = {"forms": {"gone42": {"steps": {"order": 0}}}}
    ui["extra"]["mosael"]["forms"] += [{"id": "app", "title": "重复"}, {"id": "BAD", "title": "不合规"}]
    marks = app_form.read(ui)
    assert [one.id for one in marks.forms] == ["app"] and marks.forms[0].title == "快速出图"
    assert len(marks.stray) == 3, "节点上指着不在的表单、重复的 id、不合规的 id"
    summary = app_form.summary(marks, app_form.resolve(marks, {}, OBJECT_INFO, {}, []))
    assert summary["stray"] == 3 and [one["id"] for one in summary["forms"]] == ["app"]
    cleaned = app_form.apply(ui, [QUICK], [])
    assert "mosael" not in {node["id"]: node for node in cleaned["nodes"]}[3]["properties"]
    assert app_form.read(cleaned).stray == ()


# --- 上一版改写过来 --------------------------------------------------------------


def test_上一版_有表单的改写成forms_app_结果原样_别的一个字都不动(app_form) -> None:
    source = _v1(multi_reference_ui())
    assert app_form.read(source).upgradable, "上一版:不读,但能改写"
    upgraded = app_form.upgrade(source)
    assert upgraded["extra"]["mosael"] == {"version": 2, "forms": [
        {"id": "app", "title": "快速出图", "description": "只填一句话", "graph_items": {"seed": {"order": 1}}}]}
    by_id = {node["id"]: node for node in upgraded["nodes"]}
    assert by_id[6]["properties"]["mosael"] == {"forms": {"app": {"text": {"order": 0, "main": True}}}}
    assert by_id[17]["properties"]["mosael"] == {"result": True}
    assert list(by_id[6]["properties"]) == list({node["id"]: node for node in source["nodes"]}[6]["properties"]), \
        "键在原来的位置:写回去时别的字节不挪"
    marks = app_form.read(upgraded)
    assert [(one.id, one.title) for one in marks.forms] == [("app", "快速出图")]
    assert [mark.key for mark in marks.forms[0].exposed] == ["6.text", "seed"] and marks.results == ("17",)
    assert app_form.upgrade(upgraded) is None, "已经是这一版:不用改"
    assert source == _v1(multi_reference_ui()), "不改入参"


def test_上一版_只有结果标记的_forms是空的_残留的expose去掉(app_form) -> None:
    upgraded = app_form.upgrade(_v1(multi_reference_ui(), app=False))
    assert upgraded["extra"]["mosael"] == {"version": 2, "forms": []}
    by_id = {node["id"]: node for node in upgraded["nodes"]}
    assert "mosael" not in by_id[6]["properties"], "上一版没有表单时节点上的 expose 本来就不算"
    assert by_id[17]["properties"]["mosael"] == {"result": True}
    assert app_form.upgrade(multi_reference_ui()) is None, "没有标记的图不用改"


# --- 对着假 ComfyUI:改写、入口、说清楚去升级 -------------------------------------------


@pytest.fixture
def comfy(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path / "data"))
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    with FakeComfyUI() as server:
        server.state.object_info = json.loads(json.dumps(OBJECT_INFO))
        server.state.workflows = {"multi.json": multi_reference_ui()}
        yield server


def _host(op: str, url: str, **payload: Any) -> dict[str, Any]:
    return runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": op, **payload}, {"SERVER_URL": url},
                                timeout=60).output


def _stored_as(comfy, name: str, value: dict[str, Any]) -> str:
    """ComfyUI 自己存的样子(JSON.stringify:紧凑),原文留着,逐字节比。"""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    comfy.state.workflows[name] = json.loads(text)
    comfy.state.raw_texts[f"workflows/{name}"] = text
    return text


def _without_marks(text: str) -> Any:
    value = json.loads(text)
    for node in value["nodes"]:
        node.get("properties", {}).pop("mosael", None)
    value.get("extra", {}).pop("mosael", None)
    return value


def _marks_blanked(text: str) -> str:
    """原文里每个 `"mosael": <值>` 的值换成同一个占位:两份原文这样比,不同的字节只可能在 mosael 那几格里。"""
    decoder, out, start = json.JSONDecoder(), [], 0
    while (at := text.find('"mosael"', start)) >= 0:
        colon = text.index(":", at) + 1
        while text[colon] in " \t\r\n":
            colon += 1
        _, end = decoder.raw_decode(text, colon)
        out.append(text[start:colon] + "…")
        start = end
    return "".join(out) + text[start:]


def test_upgrade_marks_只动mosael那几处_刚改过的跳过_不是上一版的不动(comfy) -> None:
    source = _v1(multi_reference_ui())
    source["extra"]["ds"] = {"scale": 1.0, "offset": [0.00001, -3.5]}
    #: 别的工具存的(Python 的写法:`1.0`、`1e-05`):写回去照原来的写,不换成 JavaScript 的 `1`、`0.00001`
    before = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    assert '"scale":1.0' in before and "1e-05" in before
    comfy.state.workflows["multi.json"] = json.loads(before)
    comfy.state.raw_texts["workflows/multi.json"] = before
    comfy.state.workflows["plain.json"] = multi_reference_ui()
    _stored_as(comfy, "busy.json", _v1(multi_reference_ui()))
    listed = {one["path"]: one["modified"] for one in _host("workflows", comfy.url)["workflows"]}
    assert {one["path"]: one["app"]["upgradable"] for one in _host("workflows", comfy.url)["workflows"]} == {
        "multi.json": True, "plain.json": False, "busy.json": True}
    comfy.state.touch("busy.json")  # 维护者看着列表的时候,有人在 ComfyUI 里存了这张
    done = _host("upgrade_marks", comfy.url, paths=[{"path": path, "modified": listed[path]} for path in listed]
                 + [{"path": "gone.json", "modified": 1}])
    done.pop("_duration_ms", None)
    assert done == {"upgraded": ["multi.json"], "stale": ["busy.json"], "skipped": ["plain.json"], "gone": ["gone.json"],
                    "failed": []}
    after = comfy.state.raw_texts["workflows/multi.json"]
    assert "\n" not in after and _without_marks(after) == _without_marks(before), "照原来的排版写回,mosael 以外一个字都不变"
    assert _marks_blanked(after) == _marks_blanked(before), "逐字节:不同的字节都在 mosael 那几格里(小数照原来的写法)"
    assert json.loads(after)["extra"]["mosael"]["forms"][0]["id"] == "app"
    writes = [call[1] for call in comfy.state.calls if call[0] == "WRITE"]
    assert writes == ["workflows/multi.json"], "只写改成了的那一张"


def test_上一版的文件_入口只剩完整工作流_指着app的说清楚去升级_目录报几张要升级(comfy, tmp_path: Path) -> None:
    _stored_as(comfy, "multi.json", _v1(multi_reference_ui()))
    catalog = _host("models", comfy.url)
    assert [one["id"] for one in catalog["models"] if one["id"].startswith("multi.json")] == ["multi.json"]
    assert catalog["library_upgrades"] == 1 and catalog["moved"] == [], "还没改写:没有表单入口,也不报改名"
    scratch = tmp_path / "out"
    scratch.mkdir()
    hooks = runtime.StreamHooks(on_progress=lambda *_: None, on_task=lambda _: None, is_cancelled=lambda: False)
    request = {"op": "generate", "kind": "image", "model": "multi.json#app", "prompt": "a cat", "parameters": {},
               "inputs": [], "resume": None}
    with pytest.raises(runtime.PluginRuntimeError, match="旧格式.*工作流库.*升级"):
        runtime.stream_tool(PLUGIN, ENTRY, "comfyui_generation", request, {"SERVER_URL": comfy.url},
                            hooks=hooks, scratch_dir=scratch, timeout=60)
    full_tool = next(one["name"] for one in _host("tools", comfy.url)["tools"]
                     if one.get("workflow", {}).get("path") == "multi.json")
    with pytest.raises(runtime.PluginRuntimeError, match="旧格式"):
        runtime.stream_tool(PLUGIN, ENTRY, full_tool + "_app", {"prompt": "a cat"}, {"SERVER_URL": comfy.url},
                            hooks=hooks, scratch_dir=scratch, timeout=60)

    listed = {one["path"]: one["modified"] for one in _host("workflows", comfy.url)["workflows"]}
    _host("upgrade_marks", comfy.url, paths=[{"path": "multi.json", "modified": listed["multi.json"]}])
    catalog = _host("models", comfy.url)
    assert [one["id"] for one in catalog["models"] if one["id"].startswith("multi.json")] == ["multi.json", "multi.json#app"]
    assert catalog["library_upgrades"] == 0
    assert catalog["moved"] == [{"key": "form-entries", "from": "multi.json", "to": "multi.json#app"}], \
        "从 1.20 之前直接升上来的:改写之后照样报这条,宿主没做过就做一次"


def test_几张表单几个入口_挨在完整工作流后面_改名只报app那张_app回答带着模型id和工具名(comfy) -> None:
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], forms=[QUICK, FINE], results=[])
    new_id = comfy.state.workflows["multi.json"]["extra"]["mosael"]["forms"][1]["id"]
    catalog = _host("models", comfy.url)
    models = {one["id"]: one for one in catalog["models"] if one["id"].startswith("multi.json")}
    assert list(models) == ["multi.json", "multi.json#app", f"multi.json#{new_id}"]
    assert models[f"multi.json#{new_id}"]["label"] == "精调"
    assert models[f"multi.json#{new_id}"]["group"] == {"id": "multi.json", "label": "multi", "entry": "form", "order": 2}, \
        "第二张表单排第 2(完整工作流是 0)"
    assert {"3.steps", "size"} <= set(models[f"multi.json#{new_id}"]["parameters"])
    assert catalog["moved"] == [{"key": "form-entries", "from": "multi.json", "to": "multi.json#app"}], \
        "新建的表单从来没有老引用,不报"
    tools = {one["name"]: one for one in _host("tools", comfy.url)["tools"]
             if one.get("workflow", {}).get("path") == "multi.json"}
    full = next(name for name, one in tools.items() if one["group"]["entry"] == "full")
    assert set(tools) == {full, f"{full}_app", f"{full}_{new_id}"}
    assert tools[f"{full}_{new_id}"]["label"] == {"zh": "工作流 · 精调", "en": "Workflow · 精调"}
    assert tools[full]["agent"] is False

    answer = _host("app", comfy.url, path="multi.json")["app"]
    assert [(one["id"], one["model"], one["tool"]) for one in answer["forms"]] == [
        ("app", "multi.json#app", f"{full}_app"), (new_id, f"multi.json#{new_id}", f"{full}_{new_id}")]
    live = _host("app", comfy.url, content=comfy.state.workflows["multi.json"], path="multi.json")["app"]
    assert live["forms"] == answer["forms"], "工作台给画布上那张:带着路径就说得出模型 id 和工具名"


def test_没起标题的表单叫未命名表单(comfy) -> None:
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], forms=[QUICK | {"title": ""}], results=[])
    model = next(one for one in _host("models", comfy.url)["models"] if one["id"] == "multi.json#app")
    assert model["label"] == {"zh": "未命名表单", "en": "Untitled form"}


def test_explain_记着的入口为什么不在_旧格式_表单删了_工作流不在了_各说各的(comfy) -> None:
    _stored_as(comfy, "old.json", _v1(multi_reference_ui()))
    seen = _host("app", comfy.url, path="multi.json")
    _host("annotate", comfy.url, path="multi.json", modified=seen["modified"], forms=[QUICK], results=[])
    before = len(comfy.state.calls)
    said = {one["id"]: one for one in _host("explain", comfy.url, ids=[
        "old.json#app", "multi.json#k3x9a2", "gone.json", "gone.json#app", "multi.json", "multi.json#app",
        "builtin:txt2img", "不是这台的"])["models"]}
    assert set(said) == {"old.json#app", "multi.json#k3x9a2", "gone.json", "gone.json#app"}, \
        "还在的入口、内置文生图、认不出的 id 不回"
    old = said["old.json#app"]
    assert old["upgrade"] is True and "旧格式" in old["reason"]["zh"] and "查看并升级" in old["reason"]["zh"]
    assert old["label"] == {"zh": "old 的表单", "en": "Form of old"}, "不读上一版的表单内容:标题照「X 的表单」说"
    assert old["group"] == {"id": "old.json", "label": "old", "entry": "form"}
    deleted = said["multi.json#k3x9a2"]
    assert deleted["upgrade"] is False and "已经没有这张表单" in deleted["reason"]["zh"]
    assert "已经没有工作流「gone」" in said["gone.json"]["reason"]["zh"] and said["gone.json"]["label"] == "gone"
    assert said["gone.json#app"]["label"] == {"zh": "gone 的表单", "en": "Form of gone"}
    assert all(call[0] == "GET" for call in comfy.state.calls[before:]), "只读"
