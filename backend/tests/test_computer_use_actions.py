"""Computer Use P1(ADR 0075):**动手** —— 点一下、输入一段,只对 Mosael 自己的窗口。

与 P0 的截图不同,这两样会真的改变界面,所以:

  · 它们是**确认卡工具**(每一张都要人点头,没有「本会话始终允许」);
  · 走**宿主桥**(`computer:click` / `computer:type`)交给 Electron 主进程,后端不做输入注入;
  · 坐标是模型看着的那张图上的像素,后端按 `scale` 换回窗口 CSS 像素;
  · 参数不对时回来的是**一句人话**,不是 traceback。

真屏幕与真输入不测:桥是替身(ADR 0075:P0/P1 不引入系统依赖)。
"""

from __future__ import annotations

import types

import pytest

import mcp_server
from app.domain.agent import computer_use
from app.domain.agent.confirmable import tool_spec
from tests.util import fresh_client


def _click_payload(**overrides) -> dict:
    payload = {"window": "main", "x": 120, "y": 80, "button": "left", "click_count": 1, "scale": 1}
    payload.update(overrides)
    return payload


# ── 工具清单 ────────────────────────────────────────────────


def test_the_actions_are_confirmation_tools_not_read_only() -> None:
    client = fresh_client()
    tools = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}

    for name in ("computer_click", "computer_type"):
        spec = tools[name]
        # 会改界面:进确认类,不进只读那一份(子智能体拿不到)。
        assert spec["confirmation"] is True, name
        assert spec["read_only"] is False, name
        assert name in mcp_server.CONFIRMATION_TOOLS
        assert name not in mcp_server.READ_ONLY_TOOLS

    click_properties = tools["computer_click"]["parameters"]["properties"]
    assert set(click_properties) == {"x", "y", "window", "button", "click_count", "scale"}
    assert click_properties["window"]["default"] == "main"
    assert click_properties["button"]["default"] == "left"
    assert click_properties["click_count"]["default"] == 1
    assert set(tools["computer_type"]["parameters"]["properties"]) == {"text", "window"}
    assert set(tools["computer_scroll"]["parameters"]["properties"]) == {"dy", "x", "y", "window", "scale"}


def test_the_actions_are_ordinary_edit_tier_tools() -> None:
    """edit 档:本会话始终允许、auto 档的 edit 直放、bypass 都对它们生效(维护者 2026-10-22)。

    它们不声明「每次都问」—— 那只留给会长期改变智能体做法的操作(改技能,ADR 0043);
    点一下 / 输入一段的后果在这一屏里,和改时间线同级。
    """
    for name in ("computer_click", "computer_type", "computer_scroll"):
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
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: {"window": payload["window"]})
    client = fresh_client()
    workspace, session = _session_client(client, mode="bypass")

    response = client.post("/api/agent/tools/computer_click", json={"arguments": {"x": 10, "y": 20}})
    assert response.status_code == 200, response.text
    card = _card_after(client, workspace, session, response.json()["result"]["confirmation_id"])

    assert card["status"] == "executed", card
    assert card["decision_mode"] == "bypass"


def test_auto_mode_approves_edit_tier_actions(monkeypatch) -> None:
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: {"window": payload["window"]})
    client = fresh_client()
    workspace, session = _session_client(client, mode="auto")

    response = client.post("/api/agent/tools/computer_type", json={"arguments": {"text": "你好"}})
    assert response.status_code == 200, response.text
    card = _card_after(client, workspace, session, response.json()["result"]["confirmation_id"])

    assert card["status"] == "executed", card
    assert card["decision_mode"] == "auto"


def test_session_allowance_approves_later_clicks(monkeypatch) -> None:
    """在卡上点过「本会话始终允许」之后,同一段对话里的下一次点击不再问人。"""
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: {"window": payload["window"]})
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
        return {"window": payload["window"], "x": payload["x"], "y": payload["y"]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)

    result = computer_use.click(window="publish", x=200, y=100, scale=0.5)

    # 图片是按 0.5 缩小的:图上的 (200, 100) 在窗口里是 (400, 200) 的 CSS 像素。
    assert calls == [
        ("computer:click", {"window": "publish", "x": 400, "y": 200, "button": "left", "clickCount": 1})
    ]
    assert result == {"window": "publish", "x": 400, "y": 200, "scale": 0.5, "button": "left", "clickCount": 1}


def test_click_rejects_bad_coordinates_buttons_and_counts_without_calling_the_bridge(monkeypatch) -> None:
    def should_not_be_called(*_args, **_kwargs) -> dict:
        raise AssertionError("参数就不对,不该去敲 Electron 的门")

    monkeypatch.setattr(computer_use, "_host_call", should_not_be_called)

    with pytest.raises(computer_use.ComputerUseError, match="x must be"):
        computer_use.click(x=-1)
    with pytest.raises(computer_use.ComputerUseError, match="x must be"):
        computer_use.click(x=True)  # bool 不是 1
    with pytest.raises(computer_use.ComputerUseError, match="button"):
        computer_use.click(button="middle")
    with pytest.raises(computer_use.ComputerUseError, match="click_count"):
        computer_use.click(click_count=3)
    with pytest.raises(computer_use.ComputerUseError, match="window"):
        computer_use.click(window="desktop")


def test_type_text_goes_through_the_bridge_and_caps_length(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"window": payload["window"]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)

    assert computer_use.type_text(text="你好") == {"window": "main", "typed": 2}
    assert calls == [("computer:type", {"window": "main", "text": "你好"})]

    with pytest.raises(computer_use.ComputerUseError, match="non-empty"):
        computer_use.type_text(text="")
    with pytest.raises(computer_use.ComputerUseError, match="at most"):
        computer_use.type_text(text="x" * (computer_use.MAX_TYPE_CHARS + 1))


# ── 领域:滚动 ────────────────────────────────────────────


def test_scroll_goes_through_the_bridge_with_the_pointer_position(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"window": payload["window"]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)

    result = computer_use.scroll(dy=3, x=100, y=40, scale=0.5)

    # 图上的 (100, 40) 在窗口里是 (200, 80) 的 CSS 像素;dy 不给位置就不带 x/y。
    assert calls == [("computer:scroll", {"window": "main", "dy": 3, "x": 200, "y": 80})]
    assert result == {"window": "main", "dy": 3, "scale": 0.5, "x": 200, "y": 80}

    calls.clear()
    computer_use.scroll(dy=-2)
    assert calls == [("computer:scroll", {"window": "main", "dy": -2})]


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
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: calls.append((channel, payload)) or {})
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
            {"button": "middle"},
            {"click_count": 3},
        ):
            with pytest.raises(Exception):
                spec.validate(db, "w1", _click_payload(**bad), None)

        type_spec = tool_spec("computer_type")
        type_spec.validate(db, "w1", {"window": "main", "text": "hi"}, None)
        with pytest.raises(Exception):
            type_spec.validate(db, "w1", {"window": "main", "text": ""}, None)

        scroll_spec = tool_spec("computer_scroll")
        scroll_spec.validate(db, "w1", {"window": "main", "dy": 3}, None)
        with pytest.raises(Exception):
            scroll_spec.validate(db, "w1", {"window": "main", "dy": 0}, None)


def test_the_card_says_what_will_happen() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        assert tool_spec("computer_click").summarize(db, _click_payload()) == (
            "confirm_computerClick",
            {"window": "main", "x": 120, "y": 80, "button": "left", "count": 1},
        )
        key, params = tool_spec("computer_type").summarize(db, {"window": "main", "text": "你好"})
        assert key == "confirm_computerType"
        assert params["text"] == "你好"
        assert tool_spec("computer_scroll").summarize(db, {"window": "main", "dy": 3}) == (
            "confirm_computerScrollDown",
            {"steps": 3},
        )
        assert tool_spec("computer_scroll").summarize(db, {"window": "main", "dy": -2}) == (
            "confirm_computerScrollUp",
            {"steps": 2},
        )


def test_approved_card_executes_through_the_bridge(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"window": payload["window"]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        card = types.SimpleNamespace(payload=_click_payload(x=10, y=20), workspace_id="w1")
        result = tool_spec("computer_click").execute(db, card, "user-1")
        assert result["x"] == 10 and result["y"] == 20
        assert calls[0][0] == "computer:click"


# ── 工具端点:真的开一张卡 ─────────────────────────────────


def test_the_tool_endpoint_opens_a_card_and_does_not_act_immediately() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 工具默认取第一个工作区
    response = client.post("/api/agent/tools/computer_click", json={"arguments": {"x": 10, "y": 20}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["status"] == "pending"
    assert body["result"]["confirmation_id"]

    response = client.post("/api/agent/tools/computer_type", json={"arguments": {"text": "你好"}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "pending"

    response = client.post("/api/agent/tools/computer_scroll", json={"arguments": {"dy": -3}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "pending"
