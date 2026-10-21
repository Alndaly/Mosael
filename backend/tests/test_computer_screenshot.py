"""Computer Use P0(ADR 0075):**只读地截 Mosael 自己的窗口**。

这一层要证明的是回路——工具 → 图 → 模型 → 下一步——而不是输入注入。所以这里钉四件事:

  · 它出现在工具清单里,是**只读**的,不在确认类里(截图不改任何东西,不该弹卡);
  · 它经**宿主桥**(Electron 主进程里的 `computer:screenshot`)拿回 PNG,并以图片内容块交给模型,
    而不是把几十万字符的 base64 塞进 JSON;
  · `scale` 真的把大图缩小(测试里不碰真屏幕:桥是替身,PNG 是当场画的);
  · 参数不对时回来的是**一句人话**,不是 traceback。

真屏幕不测(ADR 0075:P0 不引入系统依赖)。
"""

from __future__ import annotations

import base64
import io
import json
import socket
import threading

import pytest
from mcp.types import ImageContent, TextContent

import mcp_server
from app.domain.agent import computer_use
from tests.util import fresh_client


def _png(width: int, height: int) -> bytes:
    """当场画一张 PNG —— 不读磁盘、不碰屏幕。"""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (24, 30, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _shot(width: int, height: int, *, window: str = "main") -> dict:
    return {
        "window": window,
        "width": width,
        "height": height,
        "image": base64.b64encode(_png(width, height)).decode("ascii"),
    }


def _tool(client) -> dict:
    tools = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}
    assert "computer_screenshot" in tools, "computer_screenshot 不在工具清单里"
    return tools["computer_screenshot"]


def test_it_is_a_read_only_tool_with_window_and_scale() -> None:
    client = fresh_client()
    spec = _tool(client)

    # 只读:子智能体拿得到,而且调用不会立确认卡(截图不改任何东西)。
    assert spec["read_only"] is True
    assert spec["confirmation"] is False
    assert "computer_screenshot" in mcp_server.READ_ONLY_TOOLS
    assert "computer_screenshot" not in mcp_server.CONFIRMATION_TOOLS

    parameters = spec["parameters"]
    assert parameters["type"] == "object"
    assert set(parameters["properties"]) == {"window", "scale"}
    assert parameters["properties"]["window"]["default"] == "main"
    assert parameters["properties"]["scale"]["default"] == 1
    # 模型要能从 schema 里读出两个合法值,而不是自己猜一个窗口名。
    description = parameters["properties"]["window"]["description"]
    assert '"main"' in description and '"publish"' in description


def test_the_description_says_it_captures_mosael_and_not_the_desktop() -> None:
    """这段说明是模型的路由表:它得知道截的是 **Mosael 自己**,不是桌面 / 别的 App,
    也不需要屏幕录制权限;而且它不会点、不会打字。"""
    client = fresh_client()
    text = _tool(client)["description"].lower()
    assert "mosael" in text
    assert "desktop" in text  # "does NOT capture your desktop"
    assert "screen-recording" in text or "screen recording" in text
    assert "read-only" in text
    assert "click" in text and "type" in text  # 明确说不动输入
    assert "browser_screenshot" in text  # 和「截内嵌网页」那个工具分开


def test_it_goes_through_the_host_bridge_and_returns_an_image_block(monkeypatch) -> None:
    client = fresh_client()
    calls: list[tuple[str, dict]] = []

    def fake_host_call(channel: str, payload: dict) -> dict:
        calls.append((channel, payload))
        return _shot(640, 480)

    monkeypatch.setattr(computer_use, "_host_call", fake_host_call)

    response = client.post("/api/agent/tools/computer_screenshot", json={"arguments": {}})
    assert response.status_code == 200, response.text
    body = response.json()

    assert calls == [("computer:screenshot", {"window": "main"})]
    assert body["result"]["window"] == "main"
    assert (body["result"]["width"], body["result"]["height"]) == (640, 480)
    assert body["result"]["scale"] == 1

    images = body["images"]
    assert len(images) == 1
    assert images[0]["mime_type"] == "image/png"
    assert base64.b64decode(images[0]["data"]) == _png(640, 480)


def test_a_large_capture_is_shrunk_by_scale(monkeypatch) -> None:
    """scale 是给「窗口很大、我只想看布局」用的:图真的变小,回来的是缩小后的尺寸。"""
    client = fresh_client()
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: _shot(1600, 1200))

    response = client.post(
        "/api/agent/tools/computer_screenshot",
        json={"arguments": {"window": "main", "scale": 0.25}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["width"] == 400
    assert body["result"]["height"] == 300
    assert body["result"]["scale"] == 0.25

    from PIL import Image

    small = Image.open(io.BytesIO(base64.b64decode(body["images"][0]["data"])))
    assert small.size == (400, 300)


def test_an_unknown_window_gets_a_human_sentence(monkeypatch) -> None:
    client = fresh_client()

    def should_not_be_called(*_args, **_kwargs) -> dict:
        raise AssertionError("参数就不对,不该去敲 Electron 的门")

    monkeypatch.setattr(computer_use, "_host_call", should_not_be_called)

    response = client.post(
        "/api/agent/tools/computer_screenshot", json={"arguments": {"window": "desktop"}}
    )
    assert response.status_code == 200, response.text
    error = response.json()["error"]
    assert "Traceback" not in error
    assert "desktop" in error
    assert '"main"' in error and '"publish"' in error


@pytest.mark.parametrize("scale", [0, 0.1, 1.5, 4, "half", None, True])
def test_a_scale_outside_the_range_gets_a_human_sentence(monkeypatch, scale) -> None:
    client = fresh_client()
    monkeypatch.setattr(
        computer_use, "_host_call", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不该走桥"))
    )
    response = client.post(
        "/api/agent/tools/computer_screenshot", json={"arguments": {"scale": scale}}
    )
    assert response.status_code == 200, response.text
    error = response.json()["error"]
    assert "Traceback" not in error
    assert "0.25" in error and "1" in error


def test_without_the_desktop_bridge_the_error_says_where_it_works(monkeypatch) -> None:
    client = fresh_client()
    monkeypatch.delenv("MOSAEL_HOST_BRIDGE_PORT", raising=False)
    monkeypatch.delenv("MOSAEL_HOST_BRIDGE_TOKEN", raising=False)

    response = client.post("/api/agent/tools/computer_screenshot", json={"arguments": {}})
    assert response.status_code == 200, response.text
    error = response.json()["error"]
    assert "Traceback" not in error
    assert "desktop app" in error


def test_the_tool_function_returns_text_and_image_blocks() -> None:
    """进程内 MCP 客户端(Claude CLI 那一路)拿到的是标准内容块:文字里是尺寸,图单独一块。"""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(computer_use, "_host_call", lambda channel, payload: _shot(320, 200))
        blocks = mcp_server.computer_screenshot(window="main", scale=1)

    assert isinstance(blocks, list) and len(blocks) == 2
    assert isinstance(blocks[0], TextContent)
    text = json.loads(blocks[0].text)
    assert (text["width"], text["height"], text["scale"], text["window"]) == (320, 200, 1, "main")
    assert "asset_ids" not in text, "没有调用方上下文(直接函数调用):跳过入库,截图照常返回"
    assert isinstance(blocks[1], ImageContent)
    assert blocks[1].mime_type == "image/png"
    assert base64.b64decode(blocks[1].data) == _png(320, 200)


def test_the_same_png_is_saved_as_an_asset_so_the_conversation_shows_it(monkeypatch) -> None:
    """「模型看得到」和「用户看得到」是两回事:images 只给模型,轮末还会被裁掉;
    对话界面渲染的是 result.asset_ids(生成图片、飞书图片都走这条通道,见 ToolCalls)。
    所以同一份 PNG 要落一份进素材库、把 id 交回来。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: _shot(320, 200))
    monkeypatch.setattr(mcp_server, "_default_workspace_id", lambda: ws["id"])

    response = client.post("/api/agent/tools/computer_screenshot", json={"arguments": {}})
    assert response.status_code == 200, response.text
    body = response.json()

    # 给模型看的原样还在……
    assert len(body["images"]) == 1
    # ……给界面看的素材 id 也给了:库里那一份内容就是桥回来的同一张 PNG。
    asset_ids = body["result"]["asset_ids"]
    assert len(asset_ids) == 1
    asset = client.get(f"/api/assets/{asset_ids[0]}").json()
    assert asset["workspace_id"] == ws["id"]
    assert asset["source"] == "captured"
    assert "main" in asset["name"]
    file = client.get(f"/api/assets/{asset_ids[0]}/file")
    assert file.status_code == 200
    assert file.content == _png(320, 200)


def test_a_failing_asset_import_does_not_fail_the_screenshot(monkeypatch) -> None:
    """入库只是「让用户也看得见」的副本:它失败了,截图本身(模型看 images)照常返回,
    只是结果里没有 asset_ids。"""
    import app.domain.assets.importer as importer

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    monkeypatch.setattr(computer_use, "_host_call", lambda channel, payload: _shot(320, 200))
    monkeypatch.setattr(mcp_server, "_default_workspace_id", lambda: ws["id"])
    monkeypatch.setattr(
        importer,
        "import_binary_asset",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("素材库拒收")),
    )

    response = client.post("/api/agent/tools/computer_screenshot", json={"arguments": {}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["window"] == "main"
    assert "asset_ids" not in body["result"]
    assert len(body["images"]) == 1


def test_the_bridge_client_speaks_one_line_of_json(monkeypatch) -> None:
    """不靠 Electron 也把桥这一侧跑通:一行 JSON 进、一行 JSON 出,令牌和通道都在里面。
    这是「后端 → 主进程」那条线上唯一能在这里测的一半(另一半见 electron/computerScreenshot.test.ts)。"""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    seen: dict = {}

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            buffered = b""
            while not buffered.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    break
                buffered += chunk
            seen.update(json.loads(buffered.decode("utf-8")))
            connection.sendall(json.dumps({"ok": True, "result": _shot(320, 200)}).encode("utf-8") + b"\n")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setenv("MOSAEL_HOST_BRIDGE_PORT", str(server.getsockname()[1]))
    monkeypatch.setenv("MOSAEL_HOST_BRIDGE_TOKEN", "app-token")
    try:
        shot = computer_use.screenshot(window="publish", scale=1)
    finally:
        thread.join(5)
        server.close()

    assert seen == {"token": "app-token", "channel": "computer:screenshot", "payload": {"window": "publish"}}
    assert shot["window"] == "publish"
    assert (shot["width"], shot["height"]) == (320, 200)
    assert base64.b64decode(shot["image"]) == _png(320, 200)


def test_a_bridge_refusal_is_a_sentence(monkeypatch) -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            connection.recv(65536)
            connection.sendall(
                json.dumps({"ok": False, "error": "The main window is minimized; restore it and try again."}).encode("utf-8")
                + b"\n"
            )

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setenv("MOSAEL_HOST_BRIDGE_PORT", str(server.getsockname()[1]))
    monkeypatch.setenv("MOSAEL_HOST_BRIDGE_TOKEN", "app-token")
    try:
        with pytest.raises(computer_use.ComputerUseError, match="minimized"):
            computer_use.screenshot()
    finally:
        thread.join(5)
        server.close()
