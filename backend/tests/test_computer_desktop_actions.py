"""ADR 0081 P2:桌面动作的确认卡、目标形状与桥调用。"""

from __future__ import annotations

import types

import pytest

import mcp_server
from app.domain.agent import computer_use
from app.domain.agent.confirmable import tool_spec
from app.domain.agent.errors import ConfirmationError
from tests.util import fresh_client

CAPTURE = "11111111-1111-1111-1111-111111111111"


def _specs(client) -> dict[str, dict]:
    return {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}


def test_desktop_actions_are_confirmation_tools_with_both_targets() -> None:
    specs = _specs(fresh_client())
    for name in ("computer_desktop_click", "computer_desktop_type", "computer_desktop_scroll"):
        assert specs[name]["confirmation"] is True, name
        assert specs[name]["read_only"] is False, name
        assert name in mcp_server.CONFIRMATION_TOOLS
        assert name not in mcp_server.READ_ONLY_TOOLS
        assert tool_spec(name).permission == "edit"
    assert set(specs["computer_desktop_click"]["parameters"]["properties"]) == {
        "token", "capture_id", "x", "y", "button", "click_count", "scale",
    }
    assert "protected apps" in specs["computer_desktop_click"]["description"].lower()


def test_the_card_rejects_ambiguous_targets_and_bad_actions() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        click = tool_spec("computer_desktop_click")
        click.validate(db, "w1", {"token": "snap-1:0", "button": "left", "click_count": 1, "scale": 1}, None)
        click.validate(db, "w1", {"capture_id": CAPTURE, "x": 10, "y": 20, "scale": 1}, None)
        for bad in (
            {},
            {"token": "snap-1:0", "capture_id": CAPTURE, "x": 1, "y": 2},
            {"capture_id": CAPTURE, "x": -1, "y": 2},
            {"token": "snap-1:0", "button": "middle"},
            {"token": "snap-1:0", "click_count": 3},
        ):
            with pytest.raises(ConfirmationError):
                click.validate(db, "w1", bad, None)

        assert tool_spec("computer_desktop_type").summarize(
            db, {"token": "snap-1:0", "text": "hello"},
        ) == ("confirm_computerDesktopTypeToken", {"token": "snap-1:0", "text": "hello"})
        assert tool_spec("computer_desktop_scroll").summarize(
            db, {"capture_id": CAPTURE, "x": 10, "y": 20, "dy": -2},
        ) == ("confirm_computerDesktopScrollUpPixel", {"x": 10, "y": 20, "steps": 2})


def test_capture_coordinates_are_scaled_back_before_the_bridge(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"point": {"x": 100, "y": 200}, "windowNumber": 7, "pid": 42}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        card = types.SimpleNamespace(
            payload={"capture_id": CAPTURE, "x": 50, "y": 100, "button": "left", "click_count": 1, "scale": 0.5},
            workspace_id="w1",
        )
        result = tool_spec("computer_desktop_click").execute(db, card, "user-1")
    assert result["point"] == {"x": 100, "y": 200}
    assert calls == [("computer:desktop-click", {
        "captureId": CAPTURE,
        "x": 100,
        "y": 200,
        "button": "left",
        "clickCount": 1,
    })]


def test_token_type_and_scroll_use_the_element_token(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"point": {"x": 10, "y": 20}, "windowNumber": 7, "pid": 42}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        typed = tool_spec("computer_desktop_type").execute(
            db,
            types.SimpleNamespace(payload={"token": "snap-1:0", "text": "hello", "scale": 1}, workspace_id="w1"),
            "user-1",
        )
        scrolled = tool_spec("computer_desktop_scroll").execute(
            db,
            types.SimpleNamespace(payload={"token": "snap-1:0", "dy": 3, "scale": 1}, workspace_id="w1"),
            "user-1",
        )
    assert typed["typed"] == 5
    assert scrolled["dy"] == 3
    assert calls == [
        ("computer:desktop-type", {"token": "snap-1:0", "text": "hello"}),
        ("computer:desktop-scroll", {"token": "snap-1:0", "dy": 3}),
    ]


def test_the_tool_endpoint_opens_a_card_instead_of_acting_now() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    response = client.post(
        "/api/agent/tools/computer_desktop_click",
        json={"arguments": {"token": "snap-1:0", "button": "left", "click_count": 1, "scale": 1}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "pending"
    assert response.json()["result"]["confirmation_id"]
