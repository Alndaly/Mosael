"""ADR 0081 P2:桌面动作的确认卡、目标形状与桥调用。"""

from __future__ import annotations

import types

import pytest

from app import agent_tools
from app.domain.agent import computer_use
from app.domain.agent.confirmable.registry import tool_spec
from app.domain.agent.errors import ConfirmationError
from tests.util import fresh_client

CAPTURE = "11111111-1111-1111-1111-111111111111"


def _specs(client) -> dict[str, dict]:
    return {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}


def test_desktop_actions_are_confirmation_tools_with_both_targets() -> None:
    specs = _specs(fresh_client())
    for name in ("computer_desktop_click", "computer_desktop_input", "computer_desktop_scroll", "computer_desktop_drag"):
        assert specs[name]["confirmation"] is True, name
        assert specs[name]["read_only"] is False, name
        assert name in agent_tools.CONFIRMATION_TOOLS
        assert name not in agent_tools.READ_ONLY_TOOLS
        assert tool_spec(name).permission == "external"
    assert set(specs["computer_desktop_click"]["parameters"]["properties"]) == {
        "token", "capture_id", "x", "y", "button", "click_count", "scale", "modifiers",
    }
    assert set(specs["computer_desktop_drag"]["parameters"]["properties"]) == {
        "capture_id", "from_x", "from_y", "to_x", "to_y", "button", "duration_ms", "scale",
    }
    assert "click_target" in specs["computer_desktop_input"]["parameters"]["properties"]
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
            {"token": "snap-1:0", "button": "back"},
            {"token": "snap-1:0", "click_count": 4},
        ):
            with pytest.raises(ConfirmationError):
                click.validate(db, "w1", bad, None)

        assert tool_spec("computer_desktop_input").summarize(
            db, {"action": "type", "token": "snap-1:0", "text": "hello"},
        ) == ("confirm_computerDesktopTypeToken", {"token": "snap-1:0", "text": "hello"})
        assert tool_spec("computer_desktop_scroll").summarize(
            db, {"capture_id": CAPTURE, "x": 10, "y": 20, "dy": -2},
        ) == ("confirm_computerDesktopScrollUpPixel", {"x": 10, "y": 20, "steps": 2})


def test_capture_coordinates_are_scaled_back_before_the_bridge(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {
            "point": {"x": 100, "y": 200},
            "windowNumber": 7,
            "pid": 42,
            "replay": {
                "action": {"kind": "click", "button": "left", "clickCount": 1},
                "before": {"image": png, "width": 1, "height": 1},
                "after": {"image": png, "width": 1, "height": 1},
            },
        }

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        card = types.SimpleNamespace(
            id="card-1",
            session_id="session-1",
            payload={"capture_id": CAPTURE, "x": 50, "y": 100, "button": "left", "click_count": 1, "scale": 0.5},
            workspace_id="w1",
        )
        result = tool_spec("computer_desktop_click").execute(db, card, "user-1")
    assert result["point"] == {"x": 100, "y": 200}
    assert result["replay"]["session_id"] == "session-1"
    assert result["replay"]["before"]["url"].endswith("/before.png")
    assert "image" not in result["replay"]["before"]
    assert calls == [("computer:desktop-click", {
        "captureId": CAPTURE,
        "x": 100,
        "y": 200,
        "button": "left",
        "clickCount": 1,
        "modifiers": [],
    })]


def test_desktop_key_uses_the_same_target_and_replay(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"point": {"x": 10, "y": 20}, "windowNumber": 7, "pid": 42}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        result = tool_spec("computer_desktop_input").execute(
            db, types.SimpleNamespace(payload={"action": "press", "token": "snap-1:0", "key": "Enter", "modifiers": []}, workspace_id="w1"), "user-1",
        )
    assert result["key"] == "enter"
    assert calls == [("computer:desktop-key", {
        "token": "snap-1:0", "key": "enter", "modifiers": [], "clickTarget": True, "holdMs": 0,
    })]


def test_token_type_and_scroll_use_the_element_token(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"point": {"x": 10, "y": 20}, "windowNumber": 7, "pid": 42}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        typed = tool_spec("computer_desktop_input").execute(
            db,
            types.SimpleNamespace(payload={"action": "type", "token": "snap-1:0", "text": "hello", "scale": 1}, workspace_id="w1"),
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
        ("computer:desktop-type", {"token": "snap-1:0", "text": "hello", "clickTarget": True}),
        ("computer:desktop-scroll", {"token": "snap-1:0", "dy": 3, "dx": 0}),
    ]


def test_press_can_use_the_current_focus_without_clicking(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"point": {"x": 10, "y": 20}, "windowNumber": 7, "pid": 42}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        summary = tool_spec("computer_desktop_input").summarize(
            db, {"action": "press", "token": "snap-1:0", "key": "Enter", "click_target": False},
        )
        result = tool_spec("computer_desktop_input").execute(
            db,
            types.SimpleNamespace(
                payload={"action": "press", "token": "snap-1:0", "key": "Enter", "click_target": False},
                workspace_id="w1",
            ),
            "user-1",
        )
    assert summary == ("confirm_computerDesktopKeyTokenFocused", {"token": "snap-1:0", "keys": "enter"})
    assert result["key"] == "enter"
    assert calls == [("computer:desktop-key", {
        "token": "snap-1:0", "key": "enter", "modifiers": [], "clickTarget": False, "holdMs": 0,
    })]


def test_drag_maps_both_points_from_one_capture(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {
            "point": {"x": 100, "y": 200},
            "toPoint": {"x": 300, "y": 400},
            "windowNumber": 7,
            "pid": 42,
        }

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        result = tool_spec("computer_desktop_drag").execute(
            db,
            types.SimpleNamespace(
                payload={
                    "capture_id": CAPTURE,
                    "from_x": 20, "from_y": 40, "to_x": 60, "to_y": 80,
                    "button": "left", "duration_ms": 400, "scale": 0.5,
                },
                workspace_id="w1",
            ),
            "user-1",
        )
    assert result["from"] == {"x": 40, "y": 80}
    assert result["to"] == {"x": 120, "y": 160}
    assert calls == [("computer:desktop-drag", {
        "captureId": CAPTURE,
        "fromX": 40,
        "fromY": 80,
        "toX": 120,
        "toY": 160,
        "button": "left",
        "durationMs": 400,
    })]


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


def test_desktop_pointer_and_hold_and_horizontal_scroll(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        if channel == "computer:desktop-pointer":
            return {"action": payload["action"], "point": {"x": 10, "y": 20}}
        return {"point": {"x": 10, "y": 20}}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        pointer = tool_spec("computer_desktop_pointer")
        assert pointer.summarize(
            db, {"action": "hover", "token": "snap-1:0", "button": "left"},
        ) == ("confirm_computerDesktopPointerToken", {
            "action": "hover", "button": "left", "token": "snap-1:0",
        })
        pointer.execute(db, types.SimpleNamespace(
            payload={"action": "hover", "token": "snap-1:0", "button": "left", "modifiers": [], "scale": 1},
            workspace_id="w1",
        ), "user-1")

        hold = tool_spec("computer_desktop_input")
        assert hold.summarize(
            db, {"action": "press", "token": "snap-1:0", "key": "Space", "hold_ms": 700},
        ) == ("confirm_computerDesktopKeyHoldToken", {
            "token": "snap-1:0", "keys": "space", "ms": 700,
        })
        hold.execute(db, types.SimpleNamespace(
            payload={"action": "press", "token": "snap-1:0", "key": "Space", "hold_ms": 700, "modifiers": []},
            workspace_id="w1",
        ), "user-1")

        scroll = tool_spec("computer_desktop_scroll")
        assert scroll.summarize(db, {"dx": -3, "dy": 0}) == (
            "confirm_computerScrollLeft", {"steps": 3},
        )

    assert calls == [
        ("computer:desktop-pointer", {
            "action": "hover", "token": "snap-1:0", "button": "left", "modifiers": [],
        }),
        ("computer:desktop-key", {
            "token": "snap-1:0", "key": "space", "modifiers": [],
            "clickTarget": True, "holdMs": 700,
        }),
    ]


def test_desktop_batch_is_one_always_ask_card(monkeypatch) -> None:
    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        if channel == "computer:desktop-click":
            return {"point": {"x": 10, "y": 20}}
        if channel == "computer:desktop-pointer":
            return {"action": payload.get("action"), "point": {"x": 10, "y": 20}}
        if channel == "computer:desktop-scroll":
            return {"point": {"x": 10, "y": 20}}
        return {"point": {"x": 10, "y": 20}}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        spec = tool_spec("computer_desktop_batch")
        assert spec.always_asks is True
        assert spec.permission == "external"
        for bad in (
            {"actions": []},
            {"actions": [{"kind": "unknown"}]},
            {"actions": [{"kind": "click", "token": "snap-1:0"}], "window_id": 0},
        ):
            with pytest.raises(ConfirmationError):
                spec.validate(db, "w1", bad, None)
        summary = spec.summarize(db, {"actions": [
            {"kind": "click", "token": "snap-1:0"},
            {"kind": "pointer", "action": "hover", "token": "snap-1:0"},
        ]})
        assert summary[0] == "confirm_computerBatch"
        assert summary[1]["count"] == 2
        card = types.SimpleNamespace(
            payload={"actions": [
                {"kind": "click", "token": "snap-1:0"},
                {"kind": "pointer", "action": "hover", "token": "snap-1:0"},
            ], "finish_screenshot": False},
            workspace_id="w1",
        )
        result = spec.execute(db, card, "user-1")
    assert result["ok"] is True
    assert [one["kind"] for one in result["results"]] == ["click", "pointer"]
    assert [channel for channel, _ in calls] == [
        "computer:desktop-click", "computer:desktop-pointer",
    ]


def test_desktop_batch_infers_the_window_for_its_final_screenshot(monkeypatch) -> None:
    import base64
    import io

    from PIL import Image

    from tests.util import fresh_client

    png = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(png, format="PNG")
    encoded = base64.b64encode(png.getvalue()).decode("ascii")

    def fake_host_call(channel: str, payload: dict) -> dict:
        if channel == "computer:desktop-click":
            return {"point": {"x": 10, "y": 20}, "windowNumber": 7, "pid": 42}
        if channel == "computer:desktop-screenshot":
            return {
                "width": 8, "height": 8, "image": encoded,
                "meta": {"owner": "Finder", "capture_id": CAPTURE},
            }
        return {"point": {"x": 10, "y": 20}}

    from app.domain import host_files
    monkeypatch.setattr(host_files, "ensure_whole_machine", lambda *_a, **_k: None)
    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    from app.core.db import SessionLocal
    from app.db.models import Asset

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        card = types.SimpleNamespace(
            payload={"actions": [{"kind": "click", "token": "snap-1:0"}], "finish_screenshot": True},
            workspace_id=workspace["id"],
        )
        result = tool_spec("computer_desktop_batch").execute(db, card, "user-1")
        assert result["ok"] is True
        asset = db.get(Asset, result["screenshot_asset_id"])
        assert asset is not None and asset.kind == "image"
