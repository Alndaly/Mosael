"""通用插件工具跟着地方走、只发用得上的;没发的经 plugin_tools / run_plugin_tool 够得着(ADR 0044 修订 2026-10-08 之二)。

维护者开着的 3D 软件 MCP(27 个工具)、讲解视频、代码动画三样每一处每轮全发,工作台以外六处约 4.99 万 token、预算 3.84 万;
去掉它们只剩约 0.5K token 的余量,按页面细分哪一处也装不下其中任何一个。所以钉住:

- 一段新对话里,通用插件工具哪一处都不发完整定义;工作台里连够都够不着(那里是 ComfyUI 的世界);
- 这段对话调过的(直接调过,或经 plugin_tools / run_plugin_tool 点到过)下一轮起发;用户提到它的名字不算(只有工作流认名字);
- plugin_tools、run_plugin_tool 只在这一轮真有没发的插件工具时发,`plugin_tools` 的说明里点出是哪几个连接、各几个;
- plugin_tools 按字找、看完整说明(发出去的那份说明有上限)、看全部入参和某个下拉的可选值;run_plugin_tool 开的卡和那个工具
  自己的同一份:不花钱不出门的直接跑,花钱的问人、按它的档。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentMessage
from app.domain.agent.plugin_schema import DESCRIPTION_CAP
from app.domain.agent.tool_manifest import ON_DEMAND_TOOLS, agent_tool_name
from tests import general_plugins
from tests.util import fresh_client, second_client, settled_card, user_id


@pytest.fixture
def setup() -> dict[str, Any]:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    connections = general_plugins.install(client)
    names = {tool["name"]: agent_tool_name(connections[plugin["id"]], tool["name"])
             for plugin in general_plugins.ALL for tool in plugin["tools"]["declare"]}
    return {"client": client, "workspace": workspace, "names": names}


def _session(setup: dict[str, Any], home: dict[str, str]) -> str:
    created = setup["client"].post("/api/agent/sessions", json={"workspace_id": setup["workspace"], "home": home})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _token(session_id: str, username: str = "tester") -> dict[str, str]:
    with SessionLocal() as db:
        token = mint_service_session(db, user_id(username), agent_session_id=session_id)
        db.commit()
    return {"Authorization": f"Bearer {token}"}


def _turn(client, session_id: str, username: str = "tester") -> dict[str, dict[str, Any]]:
    listed = client.get("/api/agent/tools", headers=_token(session_id, username))
    assert listed.status_code == 200, listed.text
    return {one["name"]: one for one in listed.json()}


def _call(setup: dict[str, Any], session_id: str, agent_tool: str, **arguments: Any) -> dict[str, Any]:
    """以这段对话这一轮的身份调一个工具(卡的归属、这一处够得着哪些,都由令牌认)。"""
    answer = setup["client"].post(f"/api/agent/tools/{agent_tool}?workspace_id={setup['workspace']}",
                                  json={"arguments": arguments}, headers=_token(session_id))
    assert answer.status_code == 200, answer.text
    return answer.json()


def _said(session_id: str, role: str, content: str = "", payload: dict[str, Any] | None = None) -> None:
    with SessionLocal() as db:
        db.add(AgentMessage(session_id=session_id, role=role, content=content, payload=payload or {}))
        db.commit()


def test_一段新对话里不发_调过的下一轮起发_提名字不算(setup) -> None:
    client, names = setup["client"], setup["names"]
    session = _session(setup, {"kind": "studio", "id": ""})
    tools = _turn(client, session)
    assert not set(tools) & set(names.values()), "一个都不发完整定义"
    assert ON_DEMAND_TOOLS <= set(tools)
    note = tools["plugin_tools"]["description"]
    assert all(f"{plugin['name']} ({len(plugin['tools']['declare'])})" in note for plugin in general_plugins.ALL), note

    _said(session, "user", "用讲解视频(测试)和 explainer_voice 做一段")
    assert not set(_turn(client, session)) & set(names.values()), "提到名字不算 —— 只有工作流认名字"

    _said(session, "assistant", "好", {"timeline": [{"type": "tool", "tool": {"name": names["scene_step_03"], "args": {}}}]})
    _said(session, "assistant", "好", {"timeline": [{"type": "tool", "tool": {
        "name": "run_plugin_tool", "args": {"tool": "explainer_voice", "arguments": {"text": "x"}}}}]})
    _said(session, "assistant", "好", {"tools": [{"name": "plugin_tools", "args": {"tool": names["motion_animation"]}}]})
    sent = set(_turn(client, session)) & set(names.values())
    assert sent == {names["scene_step_03"], names["explainer_voice"], names["motion_animation"]}, (
        "直接调过的、经 run_plugin_tool / plugin_tools 点到的(插件里的名字、完整名字都认;老消息的 tools 也认)")
    assert ON_DEMAND_TOOLS <= set(_turn(client, session)), "还有没发的,路还在"


def test_工作台里通用插件工具不发_也够不着(setup) -> None:
    session = _session(setup, {"kind": "studio", "id": ""})
    _said(session, "user", "在工作台里说的", {"place": {"kind": "comfyui", "id": "a-connection/x.json"}})
    tools = _turn(setup["client"], session)
    assert not set(tools) & set(setup["names"].values())
    assert not set(tools) & ON_DEMAND_TOOLS, "工作台里一个没发的插件工具都没有(没接 ComfyUI):那两个也不背"
    found = _call(setup, session, "plugin_tools", query="配音")
    assert found["result"]["total"] == 0, found
    refused = _call(setup, session, "run_plugin_tool", tool="explainer_voice", arguments={"text": "x"})
    assert "plugin_tools" in refused["error"], refused


def test_没有没发的插件工具_那两个不背() -> None:
    fresh_client()  # 一个干净的库:此前直接用前一条测试留下的那份,「有没有没发的插件工具」看排在谁后面
    other = second_client("bare")
    workspace = other.post("/api/workspaces", json={"name": "B"}).json()["id"]
    session = other.post("/api/agent/sessions", json={"workspace_id": workspace, "home": {"kind": "studio"}}).json()["id"]
    assert not set(_turn(other, session, "bare")) & ON_DEMAND_TOOLS


def test_找_看全文和入参_查可选值(setup) -> None:
    session = _session(setup, {"kind": "studio", "id": ""})
    names = setup["names"]
    found = _call(setup, session, "plugin_tools", query="配音")["result"]
    assert [one["tool"] for one in found["tools"]] == [names["explainer_voice"]] and found["tools"][0]["asks"] is True
    everything = _call(setup, session, "plugin_tools")["result"]
    assert everything["total"] == everything["matched"] == sum(len(one["tools"]["declare"]) for one in general_plugins.ALL)

    full = _call(setup, session, "plugin_tools", tool="explainer_scene_code")["result"]
    assert full["tool"] == names["explainer_scene_code"] and len(full["description"]) > DESCRIPTION_CAP, "全文"
    voice = _call(setup, session, "plugin_tools", tool=names["explainer_voice"])["result"]
    assert "enum" not in voice["inputs"]["voice"] and "200 options" in voice["inputs"]["voice"]["description"]
    options = _call(setup, session, "plugin_tools", tool="explainer_voice", input="voice", query="19")["result"]
    assert options["total"] == 200 and options["options"] and all("19" in one for one in options["options"])

    _said(session, "assistant", "好", {"timeline": [
        {"type": "tool", "tool": {"name": names["explainer_scene_code"], "args": {}}},
        {"type": "tool", "tool": {"name": names["explainer_voice"], "args": {}}}]})
    turn = _turn(setup["client"], session)
    sent = turn[names["explainer_scene_code"]]["description"]
    assert len(sent.split("\n\nThis call BLOCKS")[0]) <= DESCRIPTION_CAP and "plugin_tools shows the full description" in sent, \
        "发出去的那份说明有上限,说清全文在哪"
    sent_voice = turn[names["explainer_voice"]]["parameters"]["properties"]["voice"]
    assert "enum" not in sent_voice and "200 options — plugin_tools lists them" in sent_voice["description"], \
        "通用插件工具和工作流工具同一套收紧"


def test_调一次_不花钱的直接跑_花钱的问人按它的档(setup) -> None:
    session = _session(setup, {"kind": "studio", "id": ""})
    names = setup["names"]
    free = _call(setup, session, "run_plugin_tool", tool="scene_step_02", arguments={"object_name": "Cube"})
    ran = settled_card(free["result"]["confirmation_id"])
    assert ran.status == "executed" and ran.decision_mode == "no-card", "只读的不问人(和直接调它一样)"
    assert ran.result["echo"] == {"object_name": "Cube"}

    paid = _call(setup, session, "run_plugin_tool", tool="explainer_voice", arguments={"text": "你好"})
    card = setup["client"].get(f"/api/confirmations/{paid['result']['confirmation_id']}").json()
    assert card["status"] == "pending" and card["permission"] == "ai-cost" and card["tool"] == "run_plugin_tool"
    assert card["allow_tool"] == names["explainer_voice"] and card["payload"]["tool"] == names["explainer_voice"]

    wrong = _call(setup, session, "run_plugin_tool", tool="explainer_voice", arguments={"txt": "你好"})
    assert "txt" in wrong["error"] and "text" in wrong["error"], "认不得的入参名不悄悄丢掉,说清它收哪些"
