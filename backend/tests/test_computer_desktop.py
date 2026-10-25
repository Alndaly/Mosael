"""ADR 0081 P1:智能体经宿主桥只读观察其他桌面应用。"""

from __future__ import annotations

import base64
import io

import pytest

import mcp_server
from app.domain.agent import computer_use
from tests.util import fresh_client


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (24, 30, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _shot(width: int, height: int) -> dict:
    return {
        "width": width,
        "height": height,
        "image": base64.b64encode(_png(width, height)).decode("ascii"),
        "elements": [],
        "meta": {"windowNumber": 7},
    }


def _specs(client) -> dict[str, dict]:
    return {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}


def test_desktop_observation_is_exposed_as_read_only_and_routes_the_old_tool() -> None:
    specs = _specs(fresh_client())
    names = {"computer_desktop_windows", "computer_desktop_screenshot", "computer_desktop_accessibility"}
    assert names <= specs.keys()
    for name in names:
        assert specs[name]["read_only"] is True
        assert specs[name]["confirmation"] is False
        assert name in mcp_server.READ_ONLY_TOOLS
        assert name not in mcp_server.CONFIRMATION_TOOLS
    assert "no desktop click" in specs["computer_desktop_windows"]["description"].lower()
    assert "do not claim you can click" in specs["computer_desktop_accessibility"]["description"].lower()
    assert "computer_desktop_windows" in specs["computer_screenshot"]["description"]


def test_window_list_returns_ids_for_screenshots_and_pids_for_ax(monkeypatch) -> None:
    client = fresh_client()
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"windows": [{"id": 7, "pid": 42, "owner": "Finder", "title": "Documents"}]}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    response = client.post("/api/agent/tools/computer_desktop_windows", json={"arguments": {}})
    assert response.status_code == 200, response.text
    assert calls == [("computer:desktop-windows", {})]
    assert response.json()["result"] == {"windows": [{"id": 7, "pid": 42, "owner": "Finder", "title": "Documents"}]}


def test_desktop_screenshot_uses_window_id_and_returns_a_scaled_image_block(monkeypatch) -> None:
    client = fresh_client()
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return _shot(1600, 1200)

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    response = client.post(
        "/api/agent/tools/computer_desktop_screenshot",
        json={"arguments": {"window_id": 7, "scale": 0.25}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert calls == [("computer:desktop-screenshot", {"windowNumber": 7})]
    assert body["result"]["window_id"] == 7
    assert (body["result"]["width"], body["result"]["height"], body["result"]["scale"]) == (400, 300, 0.25)
    assert len(body["images"]) == 1
    from PIL import Image

    image = Image.open(io.BytesIO(base64.b64decode(body["images"][0]["data"])))
    assert image.size == (400, 300)


def test_accessibility_returns_the_snapshot_without_promising_input(monkeypatch) -> None:
    client = fresh_client()
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return {"elements": [{"id": "snap:0", "role": "AXButton", "title": "Save"}], "meta": {"snapshot_id": "snap"}}

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)
    response = client.post("/api/agent/tools/computer_desktop_accessibility", json={"arguments": {"pid": 42}})
    assert response.status_code == 200, response.text
    assert calls == [("computer:desktop-accessibility", {"pid": 42})]
    assert response.json()["result"] == {
        "pid": 42,
        "snapshot_id": "snap",
        "elements": [{"id": "snap:0", "role": "AXButton", "title": "Save"}],
    }


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("computer_desktop_screenshot", {"window_id": 0}),
        ("computer_desktop_accessibility", {"pid": -1}),
    ],
)
def test_invalid_desktop_ids_fail_before_the_bridge(monkeypatch, tool: str, arguments: dict) -> None:
    client = fresh_client()
    monkeypatch.setattr(
        computer_use,
        "_host_call",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不该走桥")),
    )
    response = client.post(f"/api/agent/tools/{tool}", json={"arguments": arguments})
    assert response.status_code == 200, response.text
    assert "positive integer" in response.json()["error"]
