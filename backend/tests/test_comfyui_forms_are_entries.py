"""表单是工作流的入口(ADR 0045 第一步)在宿主这一侧:同一张工作流的完整工作流和它的表单各是一项,名字分两层。

维护者:krea2-text-2-image.json 上做了表单「快速用krea2生图」,Mosael 里到处只叫表单名 —— 认不出是哪张图,也拿不到全部
参数。插件现在报两个入口,各带 `group`(来自哪张工作流);宿主这里钉的是:

- 生成选项、插件页「提供了哪些模型」、工具清单、节点注册表都带着 `group`(名字按看的人的语言挑好),**不拼成一句**;
- 同一张工作流的几个入口挨在一起,完整工作流在前;
- 完整工作流的工具(插件标了 `agent: false`)不进智能体的工具表,工作流节点和插件页里照常有它;
- 生成的模型 id 放得下表单入口(`<路径>#<表单 id>`,比路径长)。
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.domain.agent.tool_manifest import agent_tool_specs
from tests.fake_comfyui import PORTRAIT_ID, FakeComfyUI, comfyui_grants
from tests.util import fresh_client, user_id

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"
PORTRAIT_TOOL = "wf_" + PORTRAIT_ID.replace("-", "")[:12]


def _formed(ui: dict[str, Any], title: str) -> dict[str, Any]:
    """portrait.json 做了一张表单 `title`(只挑了提示词那一格)。"""
    stored = copy.deepcopy(ui)
    stored["extra"] = {"mosael": {"version": 2, "forms": [{"id": "app", "title": title, "description": "", "graph_items": {}}]}}
    prompt = next(one for one in stored["nodes"] if one["id"] == 6)
    prompt["properties"] = {"mosael": {"forms": {"app": {"text": {"order": 0, "main": True}}}}}
    return stored


@pytest.fixture
def connected():
    with FakeComfyUI() as comfy:
        comfy.state.workflows["portrait.json"] = _formed(comfy.state.workflows["portrait.json"], "快速出图")
        client = fresh_client()
        created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
        assert created.status_code == 200, created.text
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
        assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
        yield client, comfy, instance_id


def _options(client, kind: str, **headers: str) -> list[dict[str, Any]]:
    listed = client.get(f"/api/generation/options?kind={kind}", headers=headers).json()
    return [one for one in listed if one["provider"] == VENDOR]


def test_生成选项_同一张工作流两项_名字分两层_挨在一起完整的在前(connected) -> None:
    client, _, _ = connected
    options = _options(client, "image")
    assert [one["model"] for one in options] == ["builtin:txt2img", "portrait.json", "portrait.json#app"]
    full, form = options[1], options[2]
    assert (form["model_label"], form["group"]) == ("快速出图", {"id": "portrait.json", "label": "portrait", "entry": "form", "order": 1})
    assert (full["model_label"], full["group"]) == ("portrait", {"id": "portrait.json", "label": "portrait", "entry": "full", "order": 0})
    assert options[0]["group"] is None, "内置文生图不是存着的工作流,不属于哪一组"
    assert "form" in form["capabilities"] and "form" not in full["capabilities"]
    assert "3.steps" in full["capabilities"]["parameter_schema"] and "3.steps" not in form["capabilities"].get(
        "parameter_schema", {}), "完整工作流是全部能填的项,表单只有挑的那几格"


def test_插件页提供的模型和工具_带着组_完整工作流不进智能体的工具表(connected) -> None:
    client, _, instance_id = connected
    models = client.get(f"/api/plugins/instances/{instance_id}/models").json()
    groups = {one["id"]: one["group"] for one in models}
    assert groups["portrait.json#app"] == {"id": "portrait.json", "label": "portrait", "entry": "form", "order": 1}
    assert groups["builtin:txt2img"] is None

    instance = next(one for one in client.get("/api/plugins").json() if one["id"] == PACKAGE)["instances"][0]
    tools = {one["name"]: one for one in instance["tools"]}
    full, form = tools[PORTRAIT_TOOL], tools[PORTRAIT_TOOL + "_app"]
    assert (full["group"]["entry"], full["agent"]) == ("full", False)
    assert (form["group"]["entry"], form["agent"]) == ("form", True)
    assert full["exposed"] and form["exposed"], "两个都是新工具:照插件的推荐开着"

    with SessionLocal() as db:
        names = {spec.name for spec in agent_tool_specs(db, user_id())}
    assert any(name.endswith(f"__{PORTRAIT_TOOL}_app") for name in names), "表单入口给智能体"
    assert not any(name.endswith(f"__{PORTRAIT_TOOL}") for name in names), \
        "有表单的图:完整工作流不进智能体的工具表(插件说 agent: false)"
    toolsets = [one for one in client.get("/api/agent/toolsets").json() if one["source"] == VENDOR]
    listed = {tool["name"] for one in toolsets for tool in one["tools"]}
    assert toolsets and PORTRAIT_TOOL + "_app" in listed
    assert PORTRAIT_TOOL not in listed, "给别的智能体的工具集同一条规矩:此前照列,给出去的是一个调不到的工具名(PLG-15)"

    node_types = {one["type"]: one for one in client.get("/api/workflows/node-types").json()}
    assert node_types[f"plugin.{PACKAGE}.{PORTRAIT_TOOL}"]["group"]["entry"] == "full", "工作流里照常能加完整工作流"
    assert node_types[f"plugin.{PACKAGE}.{PORTRAIT_TOOL}_app"]["group"] == {
        "id": "portrait.json", "label": "portrait", "entry": "form", "order": 1}


def test_表单入口的模型id比路径长_生成接口收得下(connected) -> None:
    """表单入口的 id 比路径多 `#` 和表单 id:生成接口的上限和模型行一样长(160),长路径的边上不该被接口拒。"""
    client, _, _ = connected
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    long_model = ("p" * 145) + ".json#app"
    assert len(long_model) > 120
    created = client.post("/api/generation/sessions", json={"workspace_id": workspace, "model": long_model})
    assert created.status_code == 200, created.text


def test_工作台按路径找工作流工具_有表单的找到的是表单入口_完整工作流不绕回来(connected) -> None:
    """`plugin_tools` / `run_plugin_tool` 按路径找那张工作流的工具:一张有表单的工作流两个入口路径相同,找到的是表单入口;
    按名字点完整工作流(`agent: false`)也找不到 —— 这条路不把不进智能体工具表的那个绕回来(ADR 0045 §5)。"""
    from app.db.models import User
    from app.domain.agent import plugin_lookup

    with SessionLocal() as db:
        me = db.get(User, user_id())
        tool, _name = plugin_lookup.resolve(db, me, "portrait.json")
        assert tool["name"] == PORTRAIT_TOOL + "_app"
        assert plugin_lookup.resolve(db, me, "portrait")[0]["name"] == PORTRAIT_TOOL + "_app"
        with pytest.raises(plugin_lookup.PluginLookupError):
            plugin_lookup.resolve(db, me, PORTRAIT_TOOL)


def test_智能体调表单入口的工具_确认卡上说出来自哪张工作流(connected) -> None:
    """确认卡是给人读的一句话:表单入口的工具,卡上写「来自 portrait」—— 名字分两层,这句话里两层都说(ADR 0045)。"""
    from app.core.security import mint_service_session
    from app.domain.agent.tool_manifest import agent_tool_name

    client, _, instance_id = connected
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post("/api/agent/sessions", json={"workspace_id": ws, "home": {"kind": "studio"}}).json()["id"]
    login = client.headers.get("Authorization")
    with SessionLocal() as db:
        token = mint_service_session(db, user_id(), agent_session_id=session)
        db.commit()
    client.headers["Authorization"] = f"Bearer {token}"
    reply = client.post(f"/api/agent/tools/{agent_tool_name(instance_id, PORTRAIT_TOOL + '_app')}",
                        json={"arguments": {"prompt": "柴犬"}})
    assert reply.status_code == 200, reply.text
    card_id = reply.json()["result"]["confirmation_id"]
    client.headers["Authorization"] = login
    cards = client.get("/api/confirmations", params={"workspace_id": ws, "status": "pending"}).json()
    headline = next(card["headline"] for card in cards if card["id"] == card_id)
    assert headline.startswith("运行插件工具「工作流 · 快速出图」(来自 portrait,连接「"), headline
