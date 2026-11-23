"""Computer Use P1(ADR 0075):**动手** —— 点一下、输入一段,只对 Mosael 自己的窗口。

与 P0 的截图不同,这两样会真的改变界面,所以:

  · 它们是**确认卡工具**(每一张都要人点头,没有「本会话始终允许」);
  · 走**宿主桥**(`computer:click` / `computer:type`)交给 Electron 主进程,后端不做输入注入;
  · 坐标是模型看着的那张图上的像素,后端按 `scale` 换回窗口 CSS 像素;
  · 参数不对时回来的是**一句人话**,不是 traceback。

真屏幕与真输入不测:桥是替身(ADR 0075:P0/P1 不引入系统依赖)。
"""

from __future__ import annotations

import base64
import io
import types

import pytest

import mcp_server
from app.domain.agent import computer_use
from app.domain.agent.confirmable.registry import tool_spec
from app.domain.agent.errors import ConfirmationError
from tests.util import fresh_client


def _click_payload(**overrides) -> dict:
    payload = {"x": 120, "y": 80, "button": "left", "click_count": 1, "scale": 1}
    payload.update(overrides)
    return payload


# ── 工具清单 ────────────────────────────────────────────────


def test_the_actions_are_confirmation_tools_not_read_only() -> None:
    client = fresh_client()
    tools = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}

    for name in ("computer_click", "computer_input", "computer_drag"):
        spec = tools[name]
        # 会改界面:进确认类,不进只读那一份(子智能体拿不到)。
        assert spec["confirmation"] is True, name
        assert spec["read_only"] is False, name
        assert name in mcp_server.CONFIRMATION_TOOLS
        assert name not in mcp_server.READ_ONLY_TOOLS

    click_properties = tools["computer_click"]["parameters"]["properties"]
    #: 只有一个窗口可操作 —— 没有 window 这一维(publish 分支随窗口一起删了)。
    assert set(click_properties) == {"x", "y", "button", "click_count", "scale", "token", "name", "modifiers"}
    assert click_properties["button"]["default"] == "left"
    assert click_properties["click_count"]["default"] == 1
    assert set(tools["computer_input"]["parameters"]["properties"]) == {"action", "text", "key", "modifiers", "hold_ms", "token", "name"}
    assert set(tools["computer_drag"]["parameters"]["properties"]) == {
        "from_x", "from_y", "to_x", "to_y", "button", "duration_ms", "scale",
        "from_token", "to_token", "from_name", "to_name",
    }
    assert set(tools["computer_scroll"]["parameters"]["properties"]) == {"dy", "dx", "x", "y", "scale"}


def test_the_actions_are_ordinary_edit_tier_tools() -> None:
    """edit 档:本会话始终允许、auto 档的 edit 直放、bypass 都对它们生效(维护者 2026-10-22)。

    它们不声明「每次都问」—— 那只留给会长期改变智能体做法的操作(改技能,ADR 0043);
    点一下 / 输入一段的后果在这一屏里,和改时间线同级。
    """
    for name in ("computer_click", "computer_input", "computer_scroll", "computer_drag"):
        spec = tool_spec(name)
        assert spec is not None, name
        assert spec.permission == "edit", name
        assert spec.cost == "none", name
        assert spec.always_asks is False, name
        # 没有可配置的放行判据(那是 external 那一档才有的),edit 在 auto 下本来就直放。
        assert spec.gate == "", name


def _session_client(client, mode: str | None = None, allowances: list[dict] | None = None):
    """一次真的对话:工作区 + 会话 + 带会话归属的令牌(卡挂在哪次对话由令牌说了算)。"""
    from app.core.db import SessionLocal
    from app.core.security import mint_service_session
    from app.db.models import User

    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post(
        "/api/agent/sessions",
        json={"home": {"kind": "studio"}, "workspace_id": workspace, "title": "T"},
    ).json()["id"]
    patch: dict = {}
    if mode is not None:
        patch["permission_mode"] = mode
    if allowances is not None:
        patch["auto_allow_tools"] = allowances
    if patch:
        assert client.patch(f"/api/agent/sessions/{session}", json=patch).status_code == 200
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, user.id, agent_session_id=session)
    client.headers["Authorization"] = f"Bearer {token}"
    return workspace, session


def _card_after(client, workspace: str, session: str, card_id: str) -> dict:
    """等自动放行的执行线程跑完,再读卡(接口与库都看:模式留在 decision_detail 里)。"""
    from app.core.db import SessionLocal
    from app.db.models import ToolConfirmation
    from app.domain.agent.autopilot import wait_for_idle_autopilot

    wait_for_idle_autopilot()
    listed = client.get(f"/api/confirmations?workspace_id={workspace}&session_id={session}").json()
    out = next(one for one in listed if one["id"] == card_id)
    with SessionLocal() as db:
        card = db.get(ToolConfirmation, card_id)
        out["decision_detail"] = card.decision_detail
        out["decision_mode"] = card.decision_mode
    return out


def test_bypass_approves_the_click(monkeypatch) -> None:
    #: 桥是替身:这条测的是「卡有没有被自动放行、执行了没有」,不是真的点在窗口上。
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: {"x": payload.get("x"), "y": payload.get("y"), "typed": len(payload.get("text", "")), "dy": payload.get("dy")})
    client = fresh_client()
    workspace, session = _session_client(client, mode="bypass")

    response = client.post("/api/agent/tools/computer_click", json={"arguments": {"x": 10, "y": 20}})
    assert response.status_code == 200, response.text
    card = _card_after(client, workspace, session, response.json()["result"]["confirmation_id"])

    assert card["status"] == "executed", card
    assert card["decision_mode"] == "bypass"


def test_auto_mode_approves_edit_tier_actions(monkeypatch) -> None:
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: {"x": payload.get("x"), "y": payload.get("y"), "typed": len(payload.get("text", "")), "dy": payload.get("dy")})
    client = fresh_client()
    workspace, session = _session_client(client, mode="auto")

    response = client.post("/api/agent/tools/computer_input", json={"arguments": {"action": "type", "text": "你好"}})
    assert response.status_code == 200, response.text
    card = _card_after(client, workspace, session, response.json()["result"]["confirmation_id"])

    assert card["status"] == "executed", card
    assert card["decision_mode"] == "auto"


def test_session_allowance_approves_later_clicks(monkeypatch) -> None:
    """在卡上点过「本会话始终允许」之后,同一段对话里的下一次点击不再问人。"""
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: {"x": payload.get("x"), "y": payload.get("y"), "typed": len(payload.get("text", "")), "dy": payload.get("dy")})
    client = fresh_client()
    workspace, session = _session_client(
        client, mode="manual", allowances=[{"tool": "computer_click", "permission": "edit"}]
    )

    response = client.post("/api/agent/tools/computer_click", json={"arguments": {"x": 1, "y": 2}})
    assert response.status_code == 200, response.text
    card = _card_after(client, workspace, session, response.json()["result"]["confirmation_id"])

    assert card["status"] == "executed", card
    assert card["decision_mode"] == "session-allow"


# ── 领域:坐标换算与桥调用 ──────────────────────────────────


def test_click_converts_screenshot_pixels_by_scale(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"x": payload["x"], "y": payload["y"]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)

    result = computer_use.click(x=200, y=100, scale=0.5)

    # 图片是按 0.5 缩小的:图上的 (200, 100) 在窗口里是 (400, 200) 的 CSS 像素。
    assert calls == [("computer:click", {
        "x": 400, "y": 200, "button": "left", "clickCount": 1, "modifiers": [],
    })]
    assert result == {
        "x": 400, "y": 200, "scale": 0.5, "button": "left", "clickCount": 1, "modifiers": [],
    }


def test_click_rejects_bad_coordinates_buttons_and_counts_without_calling_the_bridge(monkeypatch) -> None:
    def should_not_be_called(*_args, **_kwargs) -> dict:
        raise AssertionError("参数就不对,不该去敲 Electron 的门")

    monkeypatch.setattr(computer_use, "_host_call", should_not_be_called)

    with pytest.raises(computer_use.ComputerUseError, match="x must be"):
        computer_use.click(x=-1)
    with pytest.raises(computer_use.ComputerUseError, match="x must be"):
        computer_use.click(x=True)  # bool 不是 1
    with pytest.raises(computer_use.ComputerUseError, match="button"):
        computer_use.click(button="back")
    with pytest.raises(computer_use.ComputerUseError, match="click_count"):
        computer_use.click(click_count=4)
    #: 没有 window 这一维了:传一个不存在的窗口参数就是 TypeError(函数不接受该关键字)。
    with pytest.raises(TypeError):
        computer_use.click(window="desktop")


def test_press_goes_through_the_bridge_and_rejects_unknown_keys(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"key": payload["key"], "modifiers": payload["modifiers"]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    assert computer_use.press("z", ["cmd", "shift"]) == {
        "key": "z", "modifiers": ["cmd", "shift"], "holdMs": 0,
    }
    assert calls == [("computer:key", {"key": "z", "modifiers": ["cmd", "shift"], "holdMs": 0})]

    with pytest.raises(computer_use.ComputerUseError, match="key must be"):
        computer_use.press("a very long key")
    with pytest.raises(computer_use.ComputerUseError, match="unsupported modifier"):
        computer_use.press("Enter", ["hyper"])


def test_type_text_goes_through_the_bridge_and_caps_length(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"typed": len(payload.get("text", ""))}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)

    assert computer_use.type_text(text="你好") == {"typed": 2}
    assert calls == [("computer:type", {"text": "你好"})]

    with pytest.raises(computer_use.ComputerUseError, match="non-empty"):
        computer_use.type_text(text="")
    with pytest.raises(computer_use.ComputerUseError, match="at most"):
        computer_use.type_text(text="x" * (computer_use.MAX_TYPE_CHARS + 1))


# ── 领域:滚动 ────────────────────────────────────────────


def test_scroll_goes_through_the_bridge_with_the_pointer_position(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"dy": payload.get("dy"), "dx": payload.get("dx")}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)

    result = computer_use.scroll(dy=3, x=100, y=40, scale=0.5)

    # 图上的 (100, 40) 在窗口里是 (200, 80) 的 CSS 像素;dy 不给位置就不带 x/y。
    assert calls == [("computer:scroll", {"dy": 3, "dx": 0, "x": 200, "y": 80})]
    assert result == {"dy": 3, "dx": 0, "scale": 0.5, "x": 200, "y": 80}

    calls.clear()
    computer_use.scroll(dy=-2)
    assert calls == [("computer:scroll", {"dy": -2, "dx": 0})]


def test_scroll_rejects_zero_and_runaway_notches(monkeypatch) -> None:
    def should_not_be_called(*_args, **_kwargs) -> dict:
        raise AssertionError("参数就不对,不该去敲 Electron 的门")

    monkeypatch.setattr(computer_use, "_host_call", should_not_be_called)

    with pytest.raises(computer_use.ComputerUseError, match="non-zero"):
        computer_use.scroll(dy=0)
    with pytest.raises(computer_use.ComputerUseError, match="between"):
        computer_use.scroll(dy=computer_use.MAX_SCROLL_NOTCHES + 1)
    with pytest.raises(computer_use.ComputerUseError, match="dy must be"):
        computer_use.scroll(dy=True)


def test_end_turn_tells_the_host_and_survives_a_missing_bridge(monkeypatch) -> None:
    """回合结束:告诉桌面壳熄灭「被控制中」;桥不在(独立后端)时静默跳过,绝不让收尾失败。"""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: calls.append((channel, payload)) or {"x": 0, "y": 0})
    #: 收尾只在「这一轮真的动过手」时通知壳(否则每一轮都白发一条)。所以先点一下。
    computer_use.click(x=1, y=2)
    calls.clear()
    computer_use.end_turn()
    assert calls == [("computer:end", {})]

    def no_bridge(*_args, **_kwargs):
        raise computer_use.ComputerUseError("only works in the Mosael desktop app")

    monkeypatch.setattr(computer_use, "_host_call", no_bridge)
    computer_use.end_turn()  # 不抛


# ── 确认卡:校验 / 摘要 / 执行 ──────────────────────────────


def test_the_card_checks_shape_before_opening() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        spec = tool_spec("computer_click")
        spec.validate(db, "w1", _click_payload(), None)  # 合法:不抛
        for bad in (
            {"x": -5},
            {"y": "10"},
            {"scale": 2},
            {"button": "back"},
            {"click_count": 4},
        ):
            with pytest.raises(ConfirmationError):
                spec.validate(db, "w1", _click_payload(**bad), None)

        click_spec = tool_spec("computer_click")
        click_spec.validate(db, "w1", {"token": "snap-1:0", "button": "left", "click_count": 1}, None)
        with pytest.raises(ConfirmationError):
            click_spec.validate(db, "w1", {"token": "not-a-token", "button": "left"}, None)

        input_spec = tool_spec("computer_input")
        input_spec.validate(db, "w1", {"action": "type", "text": "hi"}, None)
        with pytest.raises(ConfirmationError):
            input_spec.validate(db, "w1", {"action": "type", "text": ""}, None)

        scroll_spec = tool_spec("computer_scroll")
        scroll_spec.validate(db, "w1", {"dy": 3}, None)
        with pytest.raises(ConfirmationError):
            scroll_spec.validate(db, "w1", {"dy": 0}, None)

        drag_spec = tool_spec("computer_drag")
        drag_spec.validate(db, "w1", {
            "from_x": 10, "from_y": 20, "to_x": 30, "to_y": 40, "button": "left", "duration_ms": 300, "scale": 1,
        }, None)
        for bad in (
            {"from_x": -1},
            {"to_y": "40"},
            {"duration_ms": 50},
            {"button": "back"},
        ):
            with pytest.raises(ConfirmationError):
                drag_spec.validate(db, "w1", {
                    "from_x": 10, "from_y": 20, "to_x": 30, "to_y": 40, **bad,
                }, None)


def test_the_card_says_what_will_happen() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        assert tool_spec("computer_click").summarize(db, _click_payload()) == (
            "confirm_computerClick",
            {"x": 120, "y": 80, "button": "left", "count": 1},
        )
        assert tool_spec("computer_click").summarize(
            db, {"token": "snap-1:0", "name": "保存"},
        ) == ("confirm_computerElementClick", {"name": "保存"})
        key, params = tool_spec("computer_input").summarize(db, {"action": "type", "text": "你好"})
        assert key == "confirm_computerType"
        assert params["text"] == "你好"
        key, params = tool_spec("computer_input").summarize(db, {"action": "press", "key": "z", "modifiers": ["cmd"]})
        assert key == "confirm_computerKey"
        assert params["keys"] == "cmd+z"
        assert tool_spec("computer_scroll").summarize(db, {"dy": 3}) == (
            "confirm_computerScrollDown",
            {"steps": 3},
        )
        assert tool_spec("computer_scroll").summarize(db, {"dy": -2}) == (
            "confirm_computerScrollUp",
            {"steps": 2},
        )
        assert tool_spec("computer_drag").summarize(db, {
            "from_x": 10, "from_y": 20, "to_x": 30, "to_y": 40, "button": "left",
        }) == (
            "confirm_computerDrag",
            {"from_x": 10, "from_y": 20, "to_x": 30, "to_y": 40, "button": "left"},
        )


def test_approved_card_executes_through_the_bridge(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"x": payload.get("x"), "y": payload.get("y")}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        card = types.SimpleNamespace(payload=_click_payload(x=10, y=20), workspace_id="w1")
        result = tool_spec("computer_click").execute(db, card, "user-1")
        assert result["x"] == 10 and result["y"] == 20
        assert calls[0][0] == "computer:click"


def test_approved_drag_executes_through_the_bridge(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {**payload, "toX": payload["toX"]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        card = types.SimpleNamespace(
            payload={
                "from_x": 20, "from_y": 40, "to_x": 60, "to_y": 80,
                "button": "left", "duration_ms": 400, "scale": 0.5,
            },
            workspace_id="w1",
        )
        result = tool_spec("computer_drag").execute(db, card, "user-1")
    assert result["from"] == {"x": 40, "y": 80}
    assert result["to"] == {"x": 120, "y": 160}
    assert calls == [("computer:drag", {
        "fromX": 40, "fromY": 80, "toX": 120, "toY": 160, "button": "left", "durationMs": 400,
    })]


def test_approved_element_token_click_uses_the_token(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"x": 140, "y": 220, "button": "left", "clickCount": 1}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        card = types.SimpleNamespace(
            payload={"token": "snap-1:0", "name": "保存", "button": "left", "click_count": 1},
            workspace_id="w1",
        )
        result = tool_spec("computer_click").execute(db, card, "user-1")
    assert result["token"] == "snap-1:0"
    assert calls == [("computer:click", {
        "token": "snap-1:0", "button": "left", "clickCount": 1, "modifiers": [],
    })]


# ── 工具端点:真的开一张卡 ─────────────────────────────────


def test_the_tool_endpoint_opens_a_card_and_does_not_act_immediately() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 工具默认取第一个工作区
    response = client.post("/api/agent/tools/computer_click", json={"arguments": {"x": 10, "y": 20}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["status"] == "pending"
    assert body["result"]["confirmation_id"]

    response = client.post("/api/agent/tools/computer_input", json={"arguments": {"action": "type", "text": "你好"}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "pending"

    response = client.post("/api/agent/tools/computer_scroll", json={"arguments": {"dy": -3}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "pending"


def test_the_input_tool_opens_a_key_card_and_escalates_shortcuts() -> None:
    from app.core.db import SessionLocal

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    response = client.post("/api/agent/tools/computer_input", json={"arguments": {"action": "press", "key": "z", "modifiers": ["cmd"]}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "pending"
    with SessionLocal() as db:
        assert tool_spec("computer_input").escalate(db, "w1", {"action": "press", "key": "z", "modifiers": ["cmd"]}) == "external"
        assert tool_spec("computer_input").escalate(db, "w1", {"action": "press", "key": "Enter", "modifiers": []}) is None


def test_batch_is_a_one_card_always_ask_tool() -> None:
    client = fresh_client()
    tools = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}
    assert tools["computer_batch"]["confirmation"] is True
    assert tools["computer_batch"]["read_only"] is False
    assert tool_spec("computer_batch").always_asks is True


def test_batch_checks_each_action_before_opening() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        batch = tool_spec("computer_batch")
        batch.validate(db, "w1", {"actions": [
            {"kind": "click", "x": 10, "y": 20},
            {"kind": "input", "action": "type", "text": "hello"},
            {"kind": "wait", "text": "Saved", "timeout_ms": 1000},
        ]}, None)
        for bad in (
            {"actions": []},
            {"actions": [{"kind": "evaluate"}]},
            {"actions": [{"kind": "click", "token": "snap-1:0"}]},
            {"actions": [{"kind": "wait", "text": ""}]},
            {"actions": [{"kind": "click", "x": -1, "y": 0}]},
        ):
            with pytest.raises(ConfirmationError):
                batch.validate(db, "w1", bad, None)


def test_batch_card_lists_steps_and_executes_in_order(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"x": payload.get("x", 0), "y": payload.get("y", 0), "typed": len(payload.get("text", "")), "dy": payload.get("dy", 0), "toX": payload.get("toX", 0)}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        summary = tool_spec("computer_batch").summarize(db, {"actions": [
            {"kind": "click", "x": 1, "y": 2},
            {"kind": "input", "action": "type", "text": "hi"},
        ]})
        assert summary[0] == "confirm_computerBatch"
        assert summary[1]["count"] == 2
        card = types.SimpleNamespace(
            payload={"actions": [
                {"kind": "click", "x": 1, "y": 2},
                {"kind": "input", "action": "type", "text": "hi"},
            ], "finish_screenshot": False},
            workspace_id="w1",
        )
        result = tool_spec("computer_batch").execute(db, card, "user-1")
    assert result["ok"] is True
    assert [one["kind"] for one in result["results"]] == ["click", "input"]
    assert [channel for channel, _ in calls] == ["computer:click", "computer:type"]


def test_batch_saves_a_final_screenshot(monkeypatch) -> None:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), (20, 30, 40)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    def fake_host_call(channel: str, payload: dict) -> dict:
        if channel == "computer:screenshot":
            return {"width": 10, "height": 10, "image": encoded}
        return {"x": payload.get("x", 0), "y": payload.get("y", 0)}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal
    from app.db.models import Asset
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()

    with SessionLocal() as db:
        card = types.SimpleNamespace(
            payload={"actions": [{"kind": "click", "x": 1, "y": 2}], "finish_screenshot": True},
            workspace_id=workspace["id"],
        )
        result = tool_spec("computer_batch").execute(db, card, "user-1")
        assert result["ok"] is True
        asset = db.get(Asset, result["screenshot_asset_id"])
        assert asset is not None
        assert asset.kind == "image"


def test_pointer_action_validates_and_executes(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {**payload}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        spec = tool_spec("computer_pointer")
        spec.validate(db, "w1", {"action": "hover", "x": 10, "y": 20}, None)
        assert spec.summarize(db, {"action": "down", "x": 10, "y": 20, "button": "middle"}) == (
            "confirm_computerPointer",
            {"action": "down", "x": 10, "y": 20, "button": "middle"},
        )
        card = types.SimpleNamespace(
            payload={"action": "up", "x": 10, "y": 20, "button": "left", "modifiers": ["shift"], "scale": 1},
            workspace_id="w1",
        )
        result = spec.execute(db, card, "user-1")
    assert result["action"] == "up"
    assert result["modifiers"] == ["shift"]
    assert calls == [("computer:pointer", {
        "action": "up", "x": 10, "y": 20, "button": "left", "modifiers": ["shift"],
    })]


def test_hold_and_horizontal_scroll_are_explicit_on_the_card(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {**payload}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        hold = tool_spec("computer_input")
        assert hold.summarize(db, {"action": "press", "key": "Space", "hold_ms": 800}) == (
            "confirm_computerKeyHold",
            {"keys": "space", "ms": 800},
        )
        card = types.SimpleNamespace(
            payload={"action": "press", "key": "Space", "hold_ms": 800, "modifiers": []},
            workspace_id="w1",
        )
        hold.execute(db, card, "user-1")
        scroll = tool_spec("computer_scroll")
        assert scroll.summarize(db, {"dx": 4, "dy": 0}) == (
            "confirm_computerScrollRight", {"steps": 4},
        )
    assert calls == [
        ("computer:key", {"key": "space", "modifiers": [], "holdMs": 800}),
    ]


def test_special_click_has_a_truthful_card() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        click = tool_spec("computer_click")
        assert click.summarize(db, {
            "x": 5, "y": 6, "button": "middle", "click_count": 3, "modifiers": ["shift"],
        }) == (
            "confirm_computerSpecialClick",
            {"x": 5, "y": 6, "button": "middle", "keys": "shift+triple-click"},
        )


def test_get_confirmation_attaches_a_batch_screenshot(monkeypatch) -> None:
    import json

    from mcp.types import ImageContent, TextContent

    import mcp_server

    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    monkeypatch.setattr(mcp_server, "_use_case", lambda *a, **k: {
        "id": "card-1", "status": "executed", "result": {"screenshot_asset_id": "asset-1"}, "error": None,
    })
    monkeypatch.setattr(mcp_server, "_screenshot_asset_image", lambda asset_id: png)
    blocks = mcp_server.get_confirmation("card-1")
    assert isinstance(blocks, list) and len(blocks) == 2
    assert isinstance(blocks[0], TextContent)
    assert json.loads(blocks[0].text)["confirmation_id"] == "card-1"
    assert isinstance(blocks[1], ImageContent)
    assert blocks[1].mime_type == "image/png"


def test_input_and_drag_accept_element_tokens(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"typed": len(payload.get("text", "")), "toX": payload.get("toX", 0)}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        input_spec = tool_spec("computer_input")
        input_spec.validate(db, "w1", {"action": "type", "text": "hi", "token": "snap-1:0"}, None)
        assert input_spec.summarize(
            db, {"action": "type", "text": "hi", "token": "snap-1:0", "name": "搜索"},
        ) == ("confirm_computerElementType", {"name": "搜索", "text": "hi"})
        input_spec.execute(db, types.SimpleNamespace(
            payload={"action": "type", "text": "hi", "token": "snap-1:0"},
            workspace_id="w1",
        ), "user-1")

        drag_spec = tool_spec("computer_drag")
        drag_spec.validate(db, "w1", {
            "from_token": "snap-1:0", "to_token": "snap-1:1", "button": "left", "duration_ms": 300,
        }, None)
        assert drag_spec.summarize(db, {
            "from_token": "snap-1:0", "to_token": "snap-1:1", "from_name": "文件", "to_name": "文件夹",
        }) == ("confirm_computerElementDrag", {"from_name": "文件", "to_name": "文件夹"})
        drag_spec.execute(db, types.SimpleNamespace(
            payload={
                "from_token": "snap-1:0", "to_token": "snap-1:1",
                "button": "left", "duration_ms": 300,
            },
            workspace_id="w1",
        ), "user-1")

    assert calls == [
        ("computer:type", {"text": "hi", "token": "snap-1:0"}),
        ("computer:drag", {"fromToken": "snap-1:0", "toToken": "snap-1:1", "button": "left", "durationMs": 300}),
    ]


def test_clipboard_is_always_asked_and_goes_through_the_bridge(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        if channel == "computer:clipboard-read":
            return {"text": "hello", "length": 5}
        return {"written": len(payload["text"])}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        read_spec = tool_spec("computer_clipboard_read")
        write_spec = tool_spec("computer_clipboard_write")
        assert read_spec.always_asks is True
        assert write_spec.always_asks is True
        read_spec.validate(db, "w1", {}, None)
        write_spec.validate(db, "w1", {"text": "hi"}, None)
        read = read_spec.execute(db, types.SimpleNamespace(payload={}), "user-1")
        write = write_spec.execute(db, types.SimpleNamespace(payload={"text": "hi"}), "user-1")
    assert read["text"] == "hello"
    assert write["written"] == 2
    assert calls == [
        ("computer:clipboard-read", {}),
        ("computer:clipboard-write", {"text": "hi"}),
    ]
