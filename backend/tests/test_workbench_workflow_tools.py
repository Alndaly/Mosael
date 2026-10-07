"""工作台那一轮的工作流工具:只发用得上的那几张,别的经 comfy_workflow_inputs / comfy_run_workflow 够得着;发给智能体的入参
收紧(ADR 0044 修订 2026-10-08)。

维护者那台 ComfyUI 上 24 张工作流,每张一个插件工具(`wf_*`),入参连同每个下拉的整张选项表 —— 工作台那一轮发出去的工具定义
约 18 万 token,预算 3.84 万。接的是 tests/comfyui_big_catalog 那台「像真的」:十几张工作流、349 项的 LoRA 下拉、一张一百多个
可调项的图。这里钉住:

- 带 `workflow` 的工具只发画布上开着的那张、这段对话里调过的(连同经 comfy_run_workflow / comfy_workflow_inputs 点到的)、
  用户点过名的(名字或文件名出现在他的话里);别的不发;没有对话的调用方全给;
- 发给智能体的入参收紧:长下拉换成一句「N options」,大图按「必填 → 非高级 → 高级」挑到上限、说一句没列出几项;插件页、
  工作流节点拿到的那份照旧是整张下拉;
- comfy_workflow_inputs 列一张工作流的全部入参、查某个下拉的可选值(按字筛);comfy_run_workflow 开的卡说的、问人的那一档、
  批准之后的执行和那个工具自己的卡同一份,认不得的入参名不悄悄丢掉。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentMessage
from app.domain.agent.plugin_schema import ENUM_INLINE, SPEC_CAP, agent_parameters, compact_property
from app.domain.agent.tool_manifest import PLUGIN_TOOL_PREFIX, agent_tool_name
from app.domain.plugins.dynamic_tools import clean_workflow
from tests import comfyui_big_catalog
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client, user_id

PACKAGE = "dev.mosael.comfyui"
PLAIN = [f"人像/LoRA 组合 {index:02d}.json" for index in range(1, comfyui_big_catalog.PLAIN_WORKFLOWS + 1)]
BIG = comfyui_big_catalog.BIG_WORKFLOW
TINY = comfyui_big_catalog.TINY_WORKFLOW


@pytest.fixture(scope="module")
def comfy():
    with FakeComfyUI() as fake:
        comfyui_big_catalog.install(fake.state)
        yield fake


@pytest.fixture
def bench(comfy) -> dict[str, Any]:
    """接了那台的一个人、一个工作区,和每张工作流的工具在智能体那边叫什么。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    connection = created.json()["id"]
    client.patch(f"/api/plugins/instances/{connection}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{connection}", json={"enabled": True}).status_code == 200
    assert client.post(f"/api/plugins/instances/{connection}/refresh").status_code == 200
    names = {path: _inputs(client, workspace, workflow=path)["tool"] for path in [*PLAIN, BIG, TINY]}
    return {"client": client, "workspace": workspace, "connection": connection, "names": names}


def _call(client, workspace: str, tool: str, **arguments: Any) -> dict[str, Any]:
    answer = client.post(f"/api/agent/tools/{tool}?workspace_id={workspace}", json={"arguments": arguments})
    assert answer.status_code == 200, answer.text
    return answer.json()


def _inputs(client, workspace: str, **arguments: Any) -> dict[str, Any]:
    out = _call(client, workspace, "comfy_workflow_inputs", **arguments)
    assert "result" in out, out
    return out["result"]


def _session(bench: dict[str, Any], canvas: str) -> str:
    created = bench["client"].post("/api/agent/sessions", json={
        "workspace_id": bench["workspace"], "home": {"kind": "comfyui", "id": f"{bench['connection']}/{canvas}"}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _turn(bench: dict[str, Any], session_id: str) -> dict[str, dict[str, Any]]:
    """sidecar 这一轮拿到的工具(用这一轮的令牌取)。"""
    with SessionLocal() as db:
        token = mint_service_session(db, user_id(), agent_session_id=session_id)
        db.commit()
    listed = bench["client"].get("/api/agent/tools", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200, listed.text
    return {one["name"]: one for one in listed.json()}


def _workflow_tools(specs: dict[str, dict[str, Any]], bench: dict[str, Any]) -> set[str]:
    by_name = {name: path for path, name in bench["names"].items()}
    return {by_name[name] for name in specs if name in by_name}


def _message(session_id: str, role: str, content: str = "", payload: dict[str, Any] | None = None) -> None:
    with SessionLocal() as db:
        db.add(AgentMessage(session_id=session_id, role=role, content=content, payload=payload or {}))
        db.commit()


def test_工作流工具只发画布上那张_点过名的_调过的_别的不发(bench) -> None:
    session = _session(bench, PLAIN[0])
    assert _workflow_tools(_turn(bench, session), bench) == {PLAIN[0]}, "画布上开着的那张"

    _message(session, "user", "再用「LoRA 组合 05」出一张图,比较一下")
    assert _workflow_tools(_turn(bench, session), bench) == {PLAIN[0], PLAIN[4]}, (
        "用户点过名的(文件名);只有一个字的名字(「图」)不算 —— 一个字到处都是")

    _message(session, "assistant", "好", {"timeline": [{"type": "tool", "tool": {"name": bench["names"][PLAIN[8]], "args": {}}}]})
    _message(session, "assistant", "好", {"tools": [{"name": "comfy_run_workflow", "args": {"workflow": BIG}}]})
    assert _workflow_tools(_turn(bench, session), bench) == {PLAIN[0], PLAIN[4], PLAIN[8], BIG}, (
        "调过的(时间线里的工具)、经 comfy_run_workflow 点到的(老消息的 tools 也认)")

    _message(session, "user", "排着的这句提到 LoRA 组合 12")
    with SessionLocal() as db:
        queued = db.query(AgentMessage).filter(AgentMessage.session_id == session).order_by(AgentMessage.created_at.desc()).first()
        queued.payload = {"queued": True}
        db.commit()
    assert PLAIN[11] not in _workflow_tools(_turn(bench, session), bench), "排在队里还没轮到的那句不算"


def test_画布上那张只认这台连接的_其他连接上同一个路径的不发(bench, comfy) -> None:
    """两台 ComfyUI 上都有「人像/LoRA 组合 01.json」(这里两个连接接的是同一台):画布开在第一台上,第二台那张的工具不发 ——
    改它不会动到眼前这张。"""
    client = bench["client"]
    other = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}}).json()["id"]
    client.patch(f"/api/plugins/instances/{other}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{other}", json={"enabled": True}).status_code == 200
    assert client.post(f"/api/plugins/instances/{other}/refresh").status_code == 200
    names = _turn(bench, _session(bench, PLAIN[0]))
    workflow_tools = {name for name in names if "__wf_" in name}
    assert workflow_tools == {bench["names"][PLAIN[0]]}, workflow_tools


def test_没有对话的调用方全给_工作台以外一张都不发(bench) -> None:
    listed = bench["client"].get("/api/agent/tools")
    assert listed.status_code == 200, listed.text
    assert _workflow_tools({one["name"]: one for one in listed.json()}, bench) == {*PLAIN, BIG, TINY}, "MCP 直连、界面拉清单"
    studio = bench["client"].post("/api/agent/sessions", json={"workspace_id": bench["workspace"], "home": {"kind": "studio", "id": ""}})
    _message(studio.json()["id"], "user", "LoRA 组合 03 那张怎么样")
    assert _workflow_tools(_turn(bench, studio.json()["id"]), bench) == set(), "工作台以外不发(ADR 0044 §8),点名也不发"


def test_发给智能体的入参收紧_插件页和工作流节点那份照旧是整张下拉(bench) -> None:
    session = _session(bench, PLAIN[0])
    spec = _turn(bench, session)[bench["names"][PLAIN[0]]]
    lora = next(value for key, value in spec["parameters"]["properties"].items() if key.startswith("lora_name"))
    assert "enum" not in lora and "349 options — comfy_workflow_inputs lists them" in lora["description"]
    sampler = next(value for key, value in spec["parameters"]["properties"].items() if key.startswith("sampler_name"))
    assert "enum" not in sampler and "45 options" in sampler["description"], f"多于 {ENUM_INLINE} 项的都换成一句"
    scheduler = next(value for key, value in spec["parameters"]["properties"].items() if key.startswith("scheduler"))
    assert len(scheduler["enum"]) == 9, "短表留着"
    assert not any(key.startswith("x-") for value in spec["parameters"]["properties"].values() for key in value)

    full = next(one for one in bench["client"].get("/api/plugins/tools").json()
                if one["instance_id"] == bench["connection"] and agent_tool_name(one["instance_id"], one["name"]) == spec["name"])
    full_lora = next(value for key, value in full["input_schema"]["properties"].items() if key.startswith("lora_name"))
    assert full_lora["enum"] == comfyui_big_catalog.LORAS, "工作流节点、画板、插件页的表单照旧是整张下拉"

    big = _turn(bench, _session(bench, BIG))[bench["names"][BIG]]
    assert len(json.dumps(big["parameters"], ensure_ascii=False)) <= SPEC_CAP
    assert "more inputs (advanced) aren't listed here — comfy_workflow_inputs shows them all" in big["description"]
    assert "prompt" in big["parameters"]["properties"], "非高级的(提示词)排在前头,不会被挑掉"


def test_查一张工作流的全部入参_某个下拉的可选值(bench) -> None:
    client, workspace = bench["client"], bench["workspace"]
    listed = _inputs(client, workspace, workflow=BIG)
    assert listed["tool"] == bench["names"][BIG] and listed["workflow"] == BIG
    assert len(listed["inputs"]) > 100, "全部入参,不设上限"
    lora_key = next(key for key in listed["inputs"] if key.startswith("lora_name"))
    assert "enum" not in listed["inputs"][lora_key], "长下拉照旧是一句,值单独查"

    by_name = _inputs(client, workspace, workflow=bench["names"][BIG].split("__")[-1], query="seed")
    assert by_name["inputs"] and all("seed" in key or "seed" in str(value.get("title", "")).lower()
                                     for key, value in by_name["inputs"].items()), "按入参名、标题筛;也认 list_workflows 回的 tool"

    options = _inputs(client, workspace, workflow=bench["names"][BIG], input=lora_key, query="lora_01")
    assert options["total"] == 349 and options["matched"] == len(options["options"]) > 0
    assert all("lora_01" in one for one in options["options"])

    missing = _call(client, workspace, "comfy_workflow_inputs", workflow=BIG, input="no_such_input")
    assert "no_such_input" in missing["error"]
    gone = _call(client, workspace, "comfy_workflow_inputs", workflow="不存在的.json")
    assert "list_workflows" in gone["error"]


def test_按工作流跑_卡和那个工具自己的同一份_认不得的入参不悄悄丢(bench) -> None:
    client, workspace = bench["client"], bench["workspace"]
    tool = bench["names"][PLAIN[2]]
    steps = next(key for key in _inputs(client, workspace, workflow=PLAIN[2])["inputs"] if key.startswith("steps"))
    out = _call(client, workspace, "comfy_run_workflow", workflow=PLAIN[2].removesuffix(".json"), arguments={steps: 30})
    card = client.get(f"/api/confirmations/{out['result']['confirmation_id']}").json()
    assert card["tool"] == "comfy_run_workflow" and card["status"] == "pending"
    assert card["payload"]["tool"] == tool and card["payload"]["arguments"] == {steps: 30}, "认出的是那张工作流的工具"
    assert "LoRA 组合 03" in card["summary"] and card["permission"] == "ai-cost", "卡上说的、问人的那一档和它自己的卡同一份"

    done = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert done["status"] == "executed", done.get("error")
    assert done["result"].get("asset_ids"), "批准之后走的是那个工具自己的执行入口:在那台 ComfyUI 上跑完、交回产出"

    wrong = _call(client, workspace, "comfy_run_workflow", workflow=PLAIN[2], arguments={"stepz": 30})
    assert "stepz" in wrong["error"] and steps in wrong["error"], "说清楚它收哪些"
    assert len(client.get(f"/api/confirmations?workspace_id={workspace}").json()) == 1, "名字不对的没开卡(只有上面那一张)"


def test_工作流键_形状不对的整条不认_名字不像样的只丢名字() -> None:
    assert clean_workflow({"path": "人像/古风.json", "name": "古风"}) == {"path": "人像/古风.json", "name": "古风"}
    assert clean_workflow({"path": "builtin:txt2img", "name": {"zh": "内置文生图", "en": "", "x": 3}}) == {
        "path": "builtin:txt2img", "name": {"zh": "内置文生图"}}
    assert clean_workflow({"path": "a.json", "name": 3}) == {"path": "a.json"}
    for bad in (None, "a.json", {"path": ""}, {"path": "a\nb.json"}, {"path": "x" * 601}, {"name": "a"}):
        assert clean_workflow(bad) is None, bad


def test_收紧的规矩() -> None:
    spec = {"title": "Steps", "description": "KSampler · steps", "type": "integer", "minimum": 1,
            "maximum": 18446744073709551615, "multipleOf": 1, "x-advanced": True, "default": 20}
    assert compact_property(spec) == {"title": "Steps", "description": "KSampler · steps", "type": "integer", "minimum": 1,
                                      "default": 20}, "去掉 x-*、步长、没有意义的上限"
    assert "description" not in compact_property({"title": "Seed Value", "description": "seed value", "type": "integer"}), \
        "说明和标题说的是同一件事时只留标题"
    long = compact_property({"title": "LoRA", "type": "string", "enum": [f"l{index}" for index in range(ENUM_INLINE + 1)]})
    assert "enum" not in long and long["description"].startswith(f"{ENUM_INLINE + 1} options")
    short = compact_property({"type": "string", "enum": ["a", "b"]})
    assert short["enum"] == ["a", "b"]

    schema = {"type": "object", "required": ["image"], "properties": {
        **{f"adv_{index}": {"type": "number", "title": f"Advanced {index} " + "x" * 40, "x-advanced": True} for index in range(60)},
        "image": {"type": "string", "title": "Image", "x-advanced": True},
        "prompt": {"type": "string", "title": "Prompt"},
    }}
    listed, omitted = agent_parameters(schema, cap=1_000)
    assert "image" in listed["properties"] and "prompt" in listed["properties"], "必填的、非高级的先挑"
    assert omitted == 62 - len(listed["properties"]) > 0 and len(json.dumps(listed, ensure_ascii=False)) <= 1_000
    assert list(listed["properties"]) == [key for key in schema["properties"] if key in listed["properties"]], "照原来的先后"
    assert listed["required"] == ["image"]
    small, none = agent_parameters({"type": "object", "properties": {"prompt": {"type": "string"}}})
    assert none == 0 and small["properties"] == {"prompt": {"type": "string"}}


def test_工作流工具说得出跑的是哪张(bench) -> None:
    """插件报的 `workflow` 存进来、读得出(插件页那份列表不带它,智能体那一侧按它挑)。"""
    from app.domain.plugins.tools import exposed

    with SessionLocal() as db:
        reported = {one["workflow"]["path"] for one in exposed(db, user_id()) if one.get("workflow")}
    assert {*PLAIN, BIG, TINY, "builtin:txt2img"} <= reported
    assert not any(name.startswith(PLUGIN_TOOL_PREFIX) for name in reported)
