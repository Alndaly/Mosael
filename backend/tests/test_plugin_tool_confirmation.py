"""智能体调插件工具:有后果的先开确认卡(domain/effects,ADR 0022)。

钉住的几条:
1. 清单里 `effects` 写错、和 `read_only` 打架,装的那一刻就报;没写的按 external(保守那边);
2. 智能体工具表给有后果的插件工具打确认标;调用只开卡不跑,批准才走同一个 invoke,拒了什么都不跑;
3. 只读的、none 的照旧直接跑,不开卡;
4. 三档权限模式对它们和对内置工具一样:bypass 放行、auto 下 paid 放行而 external/local-code 回到人、
   「本会话始终允许」按工具名记;
5. 卡上的后果由开卡这一刻的工具说了算,调用方在 payload 里自称的不算;
6. 运行时报出的工具也带后果;画板工具格和对话里是同一条规矩;MCP 直连同一条路。
"""

from __future__ import annotations

import json
import time

import pytest

import mcp_server
from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import PluginInvocation, ToolConfirmation, User
from app.domain.agent.autopilot import wait_for_idle_autopilot
from app.domain.agent.tool_manifest import agent_tool_name
from tests.test_plugins import install, packages

ENTRY = """
import json, sys
req = json.loads(sys.stdin.read())
json.dump({"ok": True, "output": {"tool": req["tool"], "echo": req["input"]}}, sys.stdout)
"""

TEXT = {"type": "object", "properties": {"text": {"type": "string"}}}

MANIFEST = {
    "id": "dev.effects",
    "name": "后果演示",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {
        "expose": "all",
        "declare": [
            {"name": "peek", "description": "只读。", "read_only": True, "input_schema": TEXT},
            {"name": "render", "description": "跑一段代码。", "effects": "local-code", "input_schema": {
                "type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
            {"name": "upload", "description": "没声明后果。", "input_schema": TEXT},
            {"name": "bill", "description": "按次计费。", "effects": "paid", "input_schema": TEXT},
            {"name": "file_it", "description": "只往素材库里写。", "effects": "none", "input_schema": TEXT},
        ],
    },
}


class Setup:
    def __init__(self, *manifests: dict) -> None:
        self.client = install(*(manifests or (MANIFEST,)), entry=ENTRY)
        self.login = self.client.headers["Authorization"]
        self.workspace_id = self.client.get("/api/workspaces").json()[0]["id"]
        for package in packages(self.client).values():
            for instance in package["instances"]:
                self.client.patch(f"/api/plugins/instances/{instance['id']}", json={"enabled": True})
        self.instance_id = packages(self.client)["dev.effects"]["instances"][0]["id"] if "dev.effects" in packages(
            self.client) else ""
        self.session_id = self.client.post(
            "/api/agent/sessions", json={"workspace_id": self.workspace_id, "title": "T"}
        ).json()["id"]

    def name(self, tool: str) -> str:
        return agent_tool_name(self.instance_id, tool)

    def as_turn(self) -> None:
        """以这次对话的 turn 身份发请求 —— 卡的归属(以及它挂哪个模式)由令牌决定。"""
        with SessionLocal() as db:
            me = db.query(User).order_by(User.created_at).first()
            token = mint_service_session(db, me.id, agent_session_id=self.session_id)
        self.client.headers["Authorization"] = f"Bearer {token}"

    def as_person(self) -> None:
        self.client.headers["Authorization"] = self.login

    def set_mode(self, mode: str) -> None:
        self.as_person()
        response = self.client.patch(f"/api/agent/sessions/{self.session_id}", json={"permission_mode": mode})
        assert response.status_code == 200, response.text

    def call(self, tool: str, arguments: dict, **params) -> dict:
        response = self.client.post(f"/api/agent/tools/{self.name(tool)}", json={"arguments": arguments}, params=params)
        assert response.status_code == 200, response.text
        return response.json()


def _card(card_id: str, timeout: float = 10.0) -> ToolConfirmation:
    """等自动放行判完、执行走到终态(approved 是中间态),再读这张卡。"""
    assert wait_for_idle_autopilot(timeout)
    deadline = time.monotonic() + timeout
    while True:
        with SessionLocal() as db:
            row = db.get(ToolConfirmation, card_id)
            db.expunge(row)
        if row.status != "approved" or time.monotonic() > deadline:
            return row
        time.sleep(0.02)


def _runs(tool: str) -> int:
    with SessionLocal() as db:
        return db.query(PluginInvocation).filter(PluginInvocation.tool_name == tool).count()


def _cards() -> int:
    with SessionLocal() as db:
        return db.query(ToolConfirmation).count()


# ── 清单 ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("tools", "says"), [
    ({"declare": [{"name": "a", "effects": "readonly"}]}, "readonly"),
    ({"declare": [{"name": "a", "read_only": True, "effects": "paid"}]}, "read_only"),
    ({"overrides": {"a": {"read_only": True, "effects": "external"}}}, "read_only"),
    ({"overrides": {"a": {"effects": "free"}}}, "free"),
    ({"default_effects": "sometimes"}, "tools.default_effects"),
])
def test_清单里的后果写错或和只读打架_装的那一刻就报(tools: dict, says: str) -> None:
    from app.core.i18n import render_message
    from app.domain.plugins.manifest import ManifestError, parse

    with pytest.raises(ManifestError) as caught:
        parse({"id": "x", "name": "X", "version": "1", "tools": tools}, "/p")
    assert says in render_message(caught.value.key, "zh", caught.value.params)


def test_工具的后果_覆盖优先_再声明_再包缺省_都没有就是external() -> None:
    from app.domain.plugins.tools import all_tools

    mcp_like = {
        "id": "dev.effects2", "name": "包缺省", "version": "1.0.0",
        "runtime": {"kind": "process", "entry": "main.py"},
        "tools": {
            "expose": "all",
            "default_effects": "paid",
            "declare": [
                {"name": "fetch", "input_schema": TEXT},
                {"name": "post", "input_schema": TEXT},
                {"name": "look", "read_only": True, "input_schema": TEXT},
            ],
            "overrides": {"post": {"effects": "external"}},
        },
    }
    setup = Setup(MANIFEST, mcp_like)
    from app.db.models import PluginInstance

    with SessionLocal() as db:
        effects = {
            tool["name"]: tool["effects"]
            for instance in db.query(PluginInstance)
            for tool in all_tools(db, instance)
        }
    assert effects == {
        "peek": "none", "render": "local-code", "upload": "external", "bill": "paid", "file_it": "none",
        "fetch": "paid", "post": "external", "look": "none",
    }
    #: 插件页和 MCP 的 list_plugin_tools 读到的是同一个值。
    listed = {tool["name"]: tool["effects"] for tool in setup.client.get("/api/plugins/tools").json()}
    assert listed["render"] == "local-code" and listed["upload"] == "external" and listed["fetch"] == "paid"


# ── 智能体那条路 ─────────────────────────────────────────────────────────────


def test_智能体工具表给有后果的插件工具打确认标_只读和none的不打() -> None:
    setup = Setup()
    specs = {tool["name"]: tool for tool in setup.client.get("/api/agent/tools").json()}
    render, peek, file_it = (specs[setup.name(one)] for one in ("render", "peek", "file_it"))
    assert render["confirmation"] is True and render["read_only"] is False
    #: 等法写在工具说明里(和内置确认类工具同一段协议),sidecar 按 confirmation 标阻塞轮询。
    assert "BLOCKS until the user approves" in render["description"]
    assert peek["confirmation"] is False and peek["read_only"] is True
    #: none 不等于只读:不问人,但子智能体照样拿不到。
    assert file_it["confirmation"] is False and file_it["read_only"] is False
    assert all(specs[setup.name(one)]["confirmation"] for one in ("upload", "bill"))


def test_调要确认的插件工具只开卡不跑_批准才跑_跑的是同一个invoke() -> None:
    setup = Setup()
    setup.as_turn()
    reply = setup.call("render", {"code": "class Scene: pass\nprint(1)"})["result"]
    assert reply["status"] == "pending" and reply["confirmation_id"]
    assert _runs("render") == 0, "卡还没批就跑了"

    card = _card(reply["confirmation_id"])
    assert card.status == "pending", "manual 档下自动放行了"
    #: 卡以**具体的工具名**开:「本会话始终允许」于是按工具记。
    assert card.tool == setup.name("render")
    assert card.permission == "external"
    assert card.session_id == setup.session_id and card.workspace_id == setup.workspace_id
    assert "会在你的电脑上运行代码" in card.summary
    assert "后果演示" in card.summary and "code=class Scene: pass…" in card.summary
    assert card.payload["instance_id"] == setup.instance_id and card.payload["tool_name"] == "render"

    setup.as_person()
    done = setup.client.post(f"/api/confirmations/{card.id}/approve").json()
    assert done["status"] == "executed", done.get("error")
    assert done["result"]["tool"] == "render" and done["result"]["echo"] == {"code": "class Scene: pass\nprint(1)"}
    assert _runs("render") == 1


def test_拒了就什么都不跑() -> None:
    setup = Setup()
    setup.as_turn()
    reply = setup.call("upload", {"text": "x"})["result"]
    setup.as_person()
    rejected = setup.client.post(f"/api/confirmations/{reply['confirmation_id']}/reject").json()
    assert rejected["status"] == "rejected"
    assert _runs("upload") == 0


def test_只读的和none的直接跑_不开卡() -> None:
    setup = Setup()
    setup.as_turn()
    assert setup.call("peek", {"text": "a"})["result"]["echo"] == {"text": "a"}
    assert setup.call("file_it", {"text": "b"})["result"]["echo"] == {"text": "b"}
    assert _cards() == 0
    assert _runs("peek") == 1 and _runs("file_it") == 1


def test_参数缺必填_开卡时就拒() -> None:
    setup = Setup()
    setup.as_turn()
    response = setup.client.post(f"/api/agent/tools/{setup.name('render')}", json={"arguments": {}})
    assert response.status_code == 422 and "code" in response.json()["detail"]
    assert _cards() == 0


def test_payload里自称的后果不算数() -> None:
    """后果决定要不要问人、按哪一档问,只能由开卡这一刻的工具说。"""
    setup = Setup()
    response = setup.client.post("/api/confirmations", json={
        "workspace_id": setup.workspace_id, "tool": setup.name("render"),
        "payload": {"arguments": {"code": "x"}, "effects": "none", "instance_id": "someone-else"},
    })
    assert response.status_code == 200, response.text
    card = _card(response.json()["id"])
    assert card.status == "pending" and card.permission == "external"
    assert card.payload["effects"] == "local-code" and card.payload["instance_id"] == setup.instance_id


def test_不是自己接的工具开不了卡() -> None:
    from tests.util import second_client

    setup = Setup()
    mate = second_client("mate")
    workspace = mate.post("/api/workspaces", json={"name": "M"}).json()["id"]
    response = mate.post("/api/confirmations", json={
        "workspace_id": workspace, "tool": setup.name("render"), "payload": {"arguments": {"code": "x"}},
    })
    assert response.status_code == 422, response.text


# ── 权限档 ──────────────────────────────────────────────────────────────────


def test_bypass_档替人批了_跑的还是同一条路() -> None:
    setup = Setup()
    setup.set_mode("bypass")
    setup.as_turn()
    reply = setup.call("render", {"code": "x"})["result"]
    card = _card(reply["confirmation_id"])
    assert card.status == "executed", card.error
    assert card.decision_mode == "bypass"
    assert _runs("render") == 1


def test_auto_档_花钱的放行_对外的和跑代码的回到人() -> None:
    setup = Setup()
    setup.set_mode("auto")
    setup.as_turn()
    paid = _card(setup.call("bill", {"text": "x"})["result"]["confirmation_id"])
    assert paid.status == "executed" and paid.decision_mode == "auto" and paid.permission == "ai-cost"
    code = _card(setup.call("render", {"code": "x"})["result"]["confirmation_id"])
    assert code.status == "pending" and code.permission == "external"
    outward = _card(setup.call("upload", {"text": "x"})["result"]["confirmation_id"])
    assert outward.status == "pending"
    assert _runs("render") == 0 and _runs("upload") == 0


def test_本会话始终允许按工具名记_不连带别的插件工具() -> None:
    setup = Setup()
    setup.as_person()
    setup.client.patch(f"/api/agent/sessions/{setup.session_id}", json={"auto_allow_tools": [setup.name("render")]})
    setup.as_turn()
    allowed = _card(setup.call("render", {"code": "x"})["result"]["confirmation_id"])
    assert allowed.status == "executed" and allowed.decision_mode == "session-allow"
    other = _card(setup.call("upload", {"text": "x"})["result"]["confirmation_id"])
    assert other.status == "pending", "允许了 Manim 渲染,却连带放开了上传"


# ── 运行时报出的工具、画板、MCP ─────────────────────────────────────────────


def test_运行时报出的工具带着后果_写错或打架时按保守那边收() -> None:
    from app.domain.plugins.dynamic_tools import _clean

    assert _clean({"name": "wf_a", "effects": "paid"}, set())["effects"] == "paid"
    assert "effects" not in _clean({"name": "wf_b", "effects": "whenever"}, set())
    clashing = _clean({"name": "wf_c", "read_only": True, "effects": "external"}, set())
    assert clashing["read_only"] is False and clashing["effects"] == "external"
    assert _clean({"name": "wf_d", "read_only": True}, set())["read_only"] is True


def test_画板工具格和对话里是同一条规矩() -> None:
    setup = Setup()
    producers = {
        one["id"]: one for one in
        setup.client.get("/api/boards/producers", params={"workspace_id": setup.workspace_id}).json()
    }
    for tool, effects in {"render": "local-code", "upload": "external", "bill": "paid", "file_it": "none",
                          "peek": "none"}.items():
        assert producers[f"node:plugin.dev.effects.{tool}"]["effects"] == effects, tool

    board = setup.client.post("/api/boards", json={"workspace_id": setup.workspace_id, "name": "B", "canvas": {
        "items": [{"id": "a1", "kind": "action", "x": 0, "y": 0, "form": {
            "config": {"code": "print(1)"}, "bindings": {}, "producer": "node:plugin.dev.effects.render"}}],
        "edges": []}}).json()
    response = setup.client.post("/api/confirmations", json={
        "workspace_id": setup.workspace_id, "tool": "run_board_item",
        "payload": {"board_id": board["id"], "item_id": "a1"}})
    assert response.status_code == 200, response.text
    card = _card(response.json()["id"])
    assert card.status == "pending" and card.permission == "external"
    assert "会在你的电脑上运行代码" in card.summary


def test_MCP直连走同一条路_有后果的回一张待确认卡(monkeypatch) -> None:
    setup = Setup()
    client = setup.client

    def call(method: str, path: str, **kwargs):
        response = client.request(method, path, **kwargs)
        mcp_server._raise_with_detail(response)
        return response.json()

    monkeypatch.setattr(mcp_server, "_get", lambda path, params=None, **_: call("GET", path, params=params))
    monkeypatch.setattr(mcp_server, "_post", lambda path, payload, **_: call("POST", path, json=payload))

    listed = {tool["name"]: tool for tool in mcp_server.list_plugin_tools()}
    assert listed["render"]["effects"] == "local-code" and listed["peek"]["effects"] == "none"

    direct = mcp_server.invoke_plugin_tool(setup.instance_id, "peek", {"text": "hi"})
    assert direct["status"] == "succeeded" and direct["output"]["echo"] == {"text": "hi"}

    pending = mcp_server.invoke_plugin_tool(setup.instance_id, "render", {"code": "x"})
    assert pending["status"] == "pending" and pending["confirmation_id"]
    assert "get_confirmation" in pending["message"]
    card = _card(pending["confirmation_id"])
    #: MCP 直连没有会话:卡无主,永远等人(不继承任何模式)。
    assert card.session_id is None and card.status == "pending" and card.requested_by == "mcp-agent"
    assert _runs("render") == 0


def test_市场索引和清单同一个算法() -> None:
    """市场详情里的「需确认」徽标读索引里的 effects;它由生成脚本按后端同一个函数算出。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    registry = json.loads((root / "website" / "public" / "plugins" / "registry.json").read_text(encoding="utf-8"))
    manim = next(one for one in registry["plugins"] if one["id"].endswith(".manim"))
    effects = {tool["name"]: tool["effects"] for tool in manim["tools"]}
    assert effects["manim_animation"] == "local-code" and effects["manim_still"] == "local-code"
    assert effects["manim_explainer"] == "none"
