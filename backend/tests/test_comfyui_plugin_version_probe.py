"""ComfyUI 的版本从哪儿读(维护者:「我为什么看不到 ComfyUI 的版本号」)。

非托管的那一份(「用我自己装的」/「连一台服务器」)没有 Mosael 的安装记录,但**它在跑**:
ComfyUI 自己在 `GET /system_stats` 的 `system.comfyui_version` 里报版本。老版本可能没有这个键,再退回安装目录里的
`comfyui_version.py`。两样都拿不到、而且宿主说它没在跑,说「没在运行」;在跑、问了没应答,说「连不上」。

这里用本机的假 ComfyUI(不是维护者那台)走一遍:
- 在跑 + 报了版本 → 用它(哪怕目录里还写着另一个版本);
- 没在跑 → 不去问,读 `comfyui_version.py`;
- 在跑但老版本不报 → 退回文件;文件也没有 → 说清「没版本可读」;
- 探测超时 / 报错 → 不抛、不卡,降级成 `unreachable`;
- 托管的一份:**先读安装记录**,记录里有就不去问在跑的那台。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
_PLUGIN_MODULES = ("service", "layouts", "shared_models", "model_files", "comfy_http", "lines", "pinned", "managed", "versions")


@pytest.fixture
def versions():
    saved = {name: sys.modules.pop(name) for name in _PLUGIN_MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import versions as module

        yield module
    finally:
        sys.path.remove(str(TOOLS))
        for name in _PLUGIN_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


class _Stats(BaseHTTPRequestHandler):
    body: bytes = b"{}"
    gate: threading.Event | None = None
    entered: threading.Event | None = None

    def do_GET(self) -> None:  # noqa: N802
        if self.entered is not None:
            self.entered.set()
        #: 卡在事件上(不是睡一段固定时间):测试先看它确实被问到了、插件已经按超时降级,再放行。
        if self.gate is not None:
            self.gate.wait(30)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args: object) -> None:
        return


def _serve(body: dict[str, Any], *, gate: threading.Event | None = None,
           entered: threading.Event | None = None) -> ThreadingHTTPServer:
    handler = type("Handler", (_Stats,), {"body": json.dumps(body).encode(), "gate": gate, "entered": entered})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.serving = threading.Thread(target=server.serve_forever, daemon=True)
    server.serving.start()
    return server


def _stop(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()
    server.serving.join(timeout=30)


def _comfy(root: Path, version: str | None) -> Path:
    """一份装好的 ComfyUI 的样子(没有版本文件时给 None)。"""
    (root / "comfy").mkdir(parents=True)
    (root / "main.py").write_text("print('ComfyUI')\n", encoding="utf-8")
    if version is not None:
        (root / "comfyui_version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    return root


def _url(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_非托管在跑_用_system_stats_报的版本_不拿目录里的旧文件(versions, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "mine", "0.39.0")
    server = _serve({"system": {"comfyui_version": "0.41.0"}, "devices": []})
    try:
        told = versions.version({"directory": str(root), "url": _url(server), "running": True}, "zh")
    finally:
        _stop(server)
    assert told == {"version": "0.41.0", "source": "running", "running": True, "reason": ""}, \
        "在跑的那一份自己报的版本优先于安装目录里那份文件"


def test_没在跑_不去问_退回_comfyui_version_py(versions, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "mine", "0.39.0")
    server = _serve({"system": {"comfyui_version": "0.41.0"}})
    try:
        told = versions.version({"directory": str(root), "url": _url(server), "running": False}, "zh")
    finally:
        _stop(server)
    assert told == {"version": "0.39.0", "source": "file", "running": False, "reason": ""}


def test_没在跑_也没有版本文件_说没在运行(versions, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "mine", None)
    told = versions.version({"directory": str(root), "url": "http://127.0.0.1:9", "running": False}, "zh")
    assert told == {"version": "", "source": "", "running": False, "reason": "not_running"}


def test_在跑但老版本不报_退回文件(versions, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "mine", "0.38.0")
    server = _serve({"system": {}, "devices": []})
    try:
        told = versions.version({"directory": str(root), "url": _url(server), "running": True}, "zh")
    finally:
        _stop(server)
    assert told == {"version": "0.38.0", "source": "file", "running": True, "reason": ""}


def test_在跑但老版本不报_文件也没有_说清没版本可读(versions, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "mine", None)
    server = _serve({"system": {}, "devices": []})
    try:
        told = versions.version({"directory": str(root), "url": _url(server), "running": True}, "zh")
    finally:
        _stop(server)
    assert told == {"version": "", "source": "", "running": True, "reason": "no_version"}


def test_探测超时_不抛_降级成连不上(versions, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "mine", None)
    gate, entered = threading.Event(), threading.Event()
    server = _serve({"system": {"comfyui_version": "0.41.0"}}, gate=gate, entered=entered)
    try:
        told = versions.version({"directory": str(root), "url": _url(server), "running": True}, "zh", timeout=0.1)
        assert entered.is_set(), "插件确实去问那台了"
        assert not gate.is_set(), "那台一直卡着没答:插件按超时降级,没有等它慢慢答"
    finally:
        gate.set()
        _stop(server)
    assert told == {"version": "", "source": "", "running": False, "reason": "unreachable"}


def test_托管先读安装记录_记录里有就不问在跑的那台(versions, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "managed", "0.39.0")
    (root / "mosael-install.json").write_text(json.dumps({"comfyui": "0.38.0"}), encoding="utf-8")
    server = _serve({"system": {"comfyui_version": "0.41.0"}})
    try:
        told = versions.version({"directory": str(root), "url": _url(server), "running": True}, "zh")
    finally:
        _stop(server)
    assert told == {"version": "0.38.0", "source": "install", "running": True, "reason": ""}, "托管路径先用记录"


def test_主入口_版本操作不用服务器地址也能读目录里的文件(tmp_path: Path) -> None:
    root = _comfy(tmp_path / "mine", "0.39.0")
    request = {"tool": "comfyui_generation", "locale": "zh",
               "input": {"op": "service_version", "directory": str(root), "running": False}}
    env = {key: value for key, value in os.environ.items() if key not in ("SERVER_URL", "ACCESS_TOKEN")}
    result = subprocess.run([sys.executable, str(TOOLS / "main.py")], input=json.dumps(request), capture_output=True,
                            text=True, env=env, timeout=60)
    response = json.loads(result.stdout.strip().splitlines()[-1])
    assert response["ok"] is True, response
    assert response["output"] == {"version": "0.39.0", "source": "file", "running": False, "reason": ""}
