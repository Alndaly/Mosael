"""工具定义加系统提示,不超过本机回退窗口的六成 —— 每轮都重发、又压不掉的那一块,得有个明说的上限。**按每一处量**。

## 现场

这道预算此前**没有写出来**,是碰巧被 test_context_is_broken_down 兜住的:那里的测试供应商挂在 localhost,
窗口落到本机回退值 32K;水位分项先给工具、再给系统提示,于是「系统提示那一项 > 0」实际断言的是
「工具定义 < 32K」—— 一条没人知道自己在守什么的线。顶到它的时候工具定义估出来 31,954,系统提示只分到
46,空闲是 0:一个字没说,窗口已经满了。

而那不只是显示问题。按 Qwen3 的分词器实数,工具定义 ≈29.1K、系统提示 ≈3.5K,合计 ≈32.5K —— 真只有
32K 的本机模型根本装不下这套工具;窗口查不到、按 32K 回退的本机模型,第一次工具调用之后 pi 按
「窗口 − 已用 − 4096」把 max_tokens 夹到 1(用户看到「我」这种碎片),轮前压缩每轮触发又压不下去。
所以回退窗口调到了 64K(理由全文在 app/domain/providers/model_limits.LOCAL_FALLBACK_CONTEXT_WINDOW),
预算在这里明说。

## 为什么是六成

- 轮前压缩在窗口的 80% 触发(agent-sidecar/src/compaction.ts 的 COMPACT_RATIO)。固定开销压不掉:它越靠近
  80%,压缩越频繁,到了 80% 就每轮都压、每轮都压不下去。
- 六成到八成之间那两成,是对话在第一次压缩之前能用的地方(64K 下约 12.8K);再往上那两成留给本轮回复与工具
  结果。
- 顶到了怎么办:先把说明写紧(op_args 的 note、工具 docstring —— 工具定义每轮重发,一个字一个字地算);写不紧
  再谈按需裁剪工具集。**不要再把回退窗口往上调**:它是对「查不到窗口的本机模型」的猜测,调大它不会让那台
  机器上的窗口变大,只会让请求在服务端超窗。

## 为什么按每一处量(ADR 0044 §8)

工具清单按**这一轮在哪说的**裁:ComfyUI 工作台里有 `comfy_*`、没有改 Mosael 画布的那一份(`canvas`),别处反过来。
此前这里只量了「挂在本机模型上、没接 ComfyUI 的一段对话」—— 接了 ComfyUI、用本机模型的人固定开销约 39.4K,超了,
而这条是绿的。现在**接了 ComfyUI + 本机模型**,七种地方各建一段家在那里的对话,每一段都量。之后加的 `comfy_*`
(ADR 0042 第二、三步)一律进 `kit="comfyui"`,由这里替它们看着。

量的是界面那条水位用的同一个函数(session_context → tool_definition_tokens + 系统提示),不另估一遍;水位和
/api/agent/tools 发出去的是同一份(下面也量)。

## 接的 ComfyUI 得像真的(ADR 0044 修订 2026-10-08)

此前这里接的假 ComfyUI 上一张能报成工具的工作流都没有 —— 每张存着的工作流是一个插件工具(`wf_*`),入参连同每个下拉的
整张选项表,维护者那台(24 张、一个 LoRA 下拉 349 项)工作台那一轮实际约 18 万 token,这条却一直是绿的。现在接的是
tests/comfyui_big_catalog 那台:十几张工作流、几百项的下拉、一张一百多个可调项的图,工作台那一处画布上开着最大那张。
工作台那一轮只发用得上的工作流工具(画布上那张、对话里调过的、点过名的),发出去的插件工具入参收紧(agent/plugin_schema),
单个插件工具的定义有上限(`PLUGIN_TOOL_CAP`)。

## 通用插件也进来(ADR 0044 修订 2026-10-08 之二)

维护者还开着一个 3D 软件的 MCP 连接(27 个工具,约 3.1 万字符)、一个出讲解视频的、一个代码动画的 —— 它们每一处都全发,工作台
以外六处每轮约 4.99 万 token,工作台约 4.61 万。这里接的是 tests/general_plugins 那三个(形状照真的造,名字和内容是编的)。
通用插件工具跟着地方走(工作台以外),而且只发这段对话调过的;别的经 `plugin_tools` / `run_plugin_tool` 够得着,这两个只在
这一轮真有没发的插件工具时才发。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentMessage
from app.domain.agent.tool_manifest import PLUGIN_TOOL_PREFIX, agent_tool_name
from app.domain.providers.model_limits import LOCAL_FALLBACK_CONTEXT_WINDOW
from tests import comfyui_big_catalog, general_plugins
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import add_provider, fresh_client, second_client, user_id

#: 固定开销(工具定义 + 系统提示)最多占本机回退窗口的这么多。理由见模块说明。
FIXED_OVERHEAD_SHARE = 0.6
#: 发给智能体的一个插件工具(名字 + 说明 + 入参的 JSON)最多这么多字符:入参收紧到 4,000(plugin_schema.SPEC_CAP),
#: 加上说明和确认协议那一段。维护者那台上最大的一个此前 84,737。
PLUGIN_TOOL_CAP = 6_000

PACKAGE = "dev.mosael.comfyui"
COMFY_TOOLS = {"comfy_canvas_read", "comfy_locate", "comfy_check", "comfy_templates", "comfy_template", "comfy_node_types",
               "comfy_node_packs", "comfy_node_pack_search", "comfy_node_pack_info", "comfy_canvas_edit", "comfy_canvas_new"}
#: 这一轮没发的插件工具经它们够得着;一个没发的都没有就不发。
ON_DEMAND = {"plugin_tools", "run_plugin_tool"}
#: 改 Mosael 自家画布的那一份里的几样(不必列全:在且只在工作台以外)。
CANVAS_TOOLS = {"edit_board", "edit_timeline", "edit_scene", "edit_workflow", "blender_execute"}
PLACES = ("studio", "project", "note", "board", "workflow", "scene", "comfyui")


@pytest.fixture(scope="module")
def comfy():
    with FakeComfyUI() as fake:
        comfyui_big_catalog.install(fake.state)
        yield fake


def _local_model() -> None:
    """一段挂在本机端点上的对话 —— 窗口查不到,落到本机回退值,正是预算要守的那个窗口。"""
    with SessionLocal() as db:
        add_provider(
            db, name="Local", vendor="openai-compatible", base_url="http://127.0.0.1:11434/v1",
            api_key="k", model="some-local-gguf", capability_ids=["chat"], owner_username="tester",
        )
        db.commit()


def _connect(client, comfy: FakeComfyUI) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    assert client.post(f"/api/plugins/instances/{instance_id}/refresh").status_code == 200
    reported = [one for one in client.get("/api/plugins/tools").json() if one["instance_id"] == instance_id]
    assert len(reported) >= comfyui_big_catalog.PLAIN_WORKFLOWS + 1, "每张工作流一个工具都报上来了 —— 否则这条预算什么都没量"
    return instance_id


def _homes(client, workspace: str, connection: str) -> dict[str, dict[str, str]]:
    """七种地方,各一样东西。"""
    project = client.post("/api/projects", json={"workspace_id": workspace, "name": "宣传片"}).json()["id"]
    note = client.post("/api/notes", json={"workspace_id": workspace, "title": "周报", "markdown": "正文"}).json()["id"]
    board = client.post("/api/boards", json={"workspace_id": workspace, "name": "分镜"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": workspace, "name": "出海流程"}).json()["id"]
    scene = client.post("/api/scenes", json={"workspace_id": workspace, "name": "客厅"}).json()["id"]
    return {
        "studio": {"kind": "studio", "id": ""},
        "project": {"kind": "project", "id": project},
        "note": {"kind": "note", "id": note},
        "board": {"kind": "board", "id": board},
        "workflow": {"kind": "workflow", "id": workflow},
        "scene": {"kind": "scene", "id": scene},
        "comfyui": {"kind": "comfyui", "id": f"{connection}/{comfyui_big_catalog.BIG_WORKFLOW}"},
    }


@pytest.fixture
def everywhere(comfy) -> dict[str, Any]:
    """接了 ComfyUI 和三个通用插件、用本机模型的人,七种地方各一段家在那里的对话。"""
    client = fresh_client()
    _local_model()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    connection = _connect(client, comfy)
    general = general_plugins.install(client)
    _fill_memory(client, workspace)
    sessions = {}
    for kind, home in _homes(client, workspace, connection).items():
        created = client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": home})
        assert created.status_code == 200, created.text
        sessions[kind] = created.json()["id"]
    return {"client": client, "workspace": workspace, "connection": connection, "sessions": sessions,
            "general": {agent_tool_name(general[plugin["id"]], tool["name"])
                        for plugin in general_plugins.ALL for tool in plugin["tools"]["declare"]}}


def _fill_memory(client, workspace: str) -> None:
    """记忆记满(ADR 0044 修订之四):系统提示里的记忆有上限(memory.MAX_PROMPT_CHARS,4000 字),这是产品允许的、每轮都要付的
    固定开销。此前这里量的是空记忆的新工作区 —— 记了八条约定的人已经超出预算 751 token,而这条是绿的。量上限,不量「典型值」:
    典型值会变,上限是承诺。"""
    from app.domain.agent.memory import MAX_CONTENT_CHARS, MAX_PROMPT_CHARS

    line = "视频统一用 1080x1920 竖屏,片头三秒内出现品牌标识,字幕用思源黑体,配色避开纯红,结尾留两秒黑场。"
    for index in range(MAX_PROMPT_CHARS // MAX_CONTENT_CHARS + 2):
        content = (f"约定{index}:" + line * 20)[:MAX_CONTENT_CHARS]
        created = client.post("/api/agent/memories", json={"workspace_id": workspace, "content": content})
        assert created.status_code == 201, created.text


def _context(client, session_id: str) -> dict[str, int]:
    context = client.get(f"/api/agent/sessions/{session_id}").json()["context"]
    assert context is not None, "没配上供应商:水位不显示,这条预算就什么都没量"
    assert context["window"] == LOCAL_FALLBACK_CONTEXT_WINDOW, "这次对话没落到本机回退窗口上"
    return {part["kind"]: part["tokens"] for part in context["parts"]}


def _turn_specs(client, session_id: str) -> list[dict[str, Any]]:
    """sidecar 这一轮拿到的工具定义:用这一轮的令牌(铸的时候记着是哪段对话)取。"""
    with SessionLocal() as db:
        token = mint_service_session(db, user_id(), agent_session_id=session_id)
        db.commit()
    listed = client.get("/api/agent/tools", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200, listed.text
    return listed.json()


def _turn_tools(client, session_id: str) -> set[str]:
    return {one["name"] for one in _turn_specs(client, session_id)}


def _size(spec: dict[str, Any]) -> int:
    """和水位同一种量法(host.tool_definition_tokens):名字 + 说明 + 入参的 JSON。"""
    return len(json.dumps({"name": spec["name"], "description": spec["description"], "parameters": spec["parameters"]},
                          ensure_ascii=False))


def _said(session_id: str, place: dict[str, str] | None, queued: bool = False) -> None:
    """这段对话里多一条用户消息(在哪说的记在 payload 里)—— 不跑一轮,只看下一轮会发哪些工具。"""
    payload: dict[str, Any] = {"place": place} if place else {}
    if queued:
        payload["queued"] = True
    with SessionLocal() as db:
        db.add(AgentMessage(session_id=session_id, role="user", content="说一句", payload=payload))
        db.commit()


@pytest.mark.parametrize("kind", PLACES)
def test_接了_ComfyUI_的本机模型_每一处的工具定义加系统提示_不超过回退窗口的六成(everywhere, kind: str) -> None:
    parts = _context(everywhere["client"], everywhere["sessions"][kind])
    fixed = parts["tools"] + parts["system"]
    budget = int(LOCAL_FALLBACK_CONTEXT_WINDOW * FIXED_OVERHEAD_SHARE)
    assert fixed <= budget, (
        f"在「{kind}」那一处,每轮重发的固定开销 {fixed}(工具定义 {parts['tools']} + 系统提示 {parts['system']})"
        f"超过了本机回退窗口 {LOCAL_FALLBACK_CONTEXT_WINDOW} 的六成({budget})。"
        "先把新加的说明写紧,别去调回退窗口 —— 见本模块说明;新的 comfy_* 记得进 kit=\"comfyui\"。"
    )


@pytest.mark.parametrize("kind", PLACES)
def test_量到的是真东西(everywhere, kind: str) -> None:
    """假阴性比红更危险:哪天工具清单或系统提示量出来是 0,上面那条会真空通过。"""
    parts = _context(everywhere["client"], everywhere["sessions"][kind])
    assert parts["tools"] > 10_000, "工具定义量出来这么小?注册表里有上百个工具"
    assert parts["system"] > 500, "系统提示量出来这么小?"
    from app.domain.agent.memory import MAX_PROMPT_CHARS

    assert parts["system"] > (MAX_PROMPT_CHARS * 0.9) / 3.5, "记忆没记满 —— 这条预算量的就不是带满记忆的那一种"


@pytest.mark.parametrize("kind", PLACES)
def test_comfy_工具在且只在工作台_画布那一份在且只在工作台以外(everywhere, kind: str) -> None:
    tools = _turn_tools(everywhere["client"], everywhere["sessions"][kind])
    if kind == "comfyui":
        assert COMFY_TOOLS <= tools and not tools & CANVAS_TOOLS
    else:
        assert CANVAS_TOOLS <= tools and not tools & COMFY_TOOLS
    assert {"list_assets", "open_view", "remember"} <= tools, "通用的哪儿都发"
    assert ON_DEMAND <= tools, "工作台里有没发的工作流工具、别处有没发的通用插件工具:够得着它们的路要在"


@pytest.mark.parametrize("kind", PLACES)
def test_通用插件工具_一段新对话里哪一处都不发完整定义_工作台里也够不着(everywhere, kind: str) -> None:
    client, session = everywhere["client"], everywhere["sessions"][kind]
    specs = _turn_specs(client, session)
    assert not {one["name"] for one in specs} & everywhere["general"]
    note = next(one for one in specs if one["name"] == "plugin_tools")["description"]
    if kind == "comfyui":
        assert "3D 软件(测试)" not in note, "工作台里不是它们的地方"
    else:
        assert all(f"{plugin['name']} ({len(plugin['tools']['declare'])})" in note for plugin in general_plugins.ALL), note


def test_工作台那一轮_工作流工具只发画布上开着的那张(everywhere) -> None:
    """十五张工作流的工具都报上来了;画布上开着的是最大那张(一百多个可调项、十几个 349 项的 LoRA 下拉),这一轮只发它一张。"""
    specs = _turn_specs(everywhere["client"], everywhere["sessions"]["comfyui"])
    workflow_tools = [one for one in specs if one["name"].startswith(PLUGIN_TOOL_PREFIX) and "__wf_" in one["name"]]
    assert len(workflow_tools) == 1, [one["name"] for one in workflow_tools]
    assert comfyui_big_catalog.BIG_WORKFLOW in workflow_tools[0]["description"] or "多段精修" in workflow_tools[0]["description"]
    assert "list_workflows" in {one["name"].split("__")[-1] for one in specs}, "找别的那几张的路还在"


@pytest.mark.parametrize("kind", ["comfyui", "no-conversation"])
def test_单个插件工具的定义有上限(everywhere, kind: str) -> None:
    """工作台那一轮发的、和没有对话的调用方(MCP 直连、界面拉清单 —— 全部工作流工具都给)拿到的,每一个插件工具的定义都在
    `PLUGIN_TOOL_CAP` 以内;长下拉不在定义里。"""
    client = everywhere["client"]
    if kind == "comfyui":
        specs = _turn_specs(client, everywhere["sessions"]["comfyui"])
    else:
        listed = client.get("/api/agent/tools")
        assert listed.status_code == 200, listed.text
        specs = listed.json()
    plugin = [one for one in specs if one["name"].startswith(PLUGIN_TOOL_PREFIX)]
    workflow_tools = [one for one in plugin if "__wf_" in one["name"]]
    assert workflow_tools, "一个工作流工具都没量到"
    if kind == "no-conversation":
        assert len(workflow_tools) >= comfyui_big_catalog.PLAIN_WORKFLOWS + 1
        assert len(plugin) >= len(workflow_tools) + sum(len(one["tools"]["declare"]) for one in general_plugins.ALL), \
            "通用插件工具也在量的里头"
    too_big = {one["name"]: _size(one) for one in plugin if _size(one) > PLUGIN_TOOL_CAP}
    assert not too_big, f"这几个插件工具的定义超过了 {PLUGIN_TOOL_CAP} 字符:{too_big}"
    assert not any(comfyui_big_catalog.LORAS[100] in json.dumps(one["parameters"], ensure_ascii=False) for one in plugin), \
        "几百项的下拉不进定义"


def test_这一轮在哪说的说了算_不是家在哪(everywhere) -> None:
    """家在 AI Studio 的一段,在工作台里接着聊:那一轮有 comfy_*、没有画布那一份;回到 AI Studio 说一句,反过来。
    排在队里还没轮到的那条不算 —— 它说的是下一轮。"""
    client, session = everywhere["client"], everywhere["sessions"]["studio"]
    workbench = {"kind": "comfyui", "id": f"{everywhere['connection']}/{comfyui_big_catalog.BIG_WORKFLOW}"}
    _said(session, workbench)
    tools = _turn_tools(client, session)
    assert COMFY_TOOLS <= tools and not tools & CANVAS_TOOLS
    with_comfy = _context(client, session)["tools"]

    _said(session, {"kind": "studio", "id": ""}, queued=True)
    assert COMFY_TOOLS <= _turn_tools(client, session), "排队的那条还没轮到"

    _said(session, {"kind": "studio", "id": ""})
    tools = _turn_tools(client, session)
    assert CANVAS_TOOLS <= tools and not tools & COMFY_TOOLS
    assert _context(client, session)["tools"] != with_comfy, "水位跟着这一轮真发出去的那份走"


def test_消息没记在哪说的_飞书_通知_老消息_按家发(everywhere) -> None:
    client, session = everywhere["client"], everywhere["sessions"]["comfyui"]
    _said(session, None)
    assert COMFY_TOOLS <= _turn_tools(client, session)


def test_没有对话的调用方全给(everywhere) -> None:
    names = {one["name"] for one in everywhere["client"].get("/api/agent/tools").json()}
    assert COMFY_TOOLS <= names and CANVAS_TOOLS <= names


def test_没接_ComfyUI_的人_在工作台那一处也没有_comfy_工具(everywhere) -> None:
    """这一轮说是在工作台里(地方只校验形状),可他没接 ComfyUI:needs 照旧叠在上面。"""
    other = second_client("other")
    workspace = other.post("/api/workspaces", json={"name": "O"}).json()["id"]
    session = other.post("/api/agent/sessions", json={"workspace_id": workspace, "home": {"kind": "studio"}}).json()["id"]
    _said(session, {"kind": "comfyui", "id": "somebody-elses"})
    with SessionLocal() as db:
        token = mint_service_session(db, user_id("other"), agent_session_id=session)
        db.commit()
    names = {one["name"] for one in other.get("/api/agent/tools", headers={"Authorization": f"Bearer {token}"}).json()}
    assert not names & COMFY_TOOLS
    assert not names & CANVAS_TOOLS, "在工作台里说的,画布那一份照样不发"
    assert "list_assets" in names
