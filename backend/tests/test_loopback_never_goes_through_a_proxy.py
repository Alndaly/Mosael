"""本机地址永远直连,不被送进代理(SEC-10)。

应用里的出站代理留空时,后端把代理环境变量删掉;httpx 接着去读**系统代理设置**(macOS、Windows),而那条路带不来
「绕过」名单 —— 开着 Clash 的 Mac 上连 127.0.0.1 都进了代理:本机的 Ollama、LM Studio 一关代理就全挂,报的还是代理替它
回的「HTTP 502」。这里用「环境里只有代理、没有 NO_PROXY」模拟系统代理那条路(两者在 httpx 眼里是同一个形状),起两个
真的本机服务:一个装作代理(一律回 502),一个是本机的模型服务。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.ai import model_catalog
from app.core.http_retry import RetryingClient


@pytest.fixture(autouse=True)
def _desktop(monkeypatch):
    """这里的服务起在本机回环上,是桌面版的情形:连接里填的(部署配的)地址照连(core/outbound_guard)。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "local_desktop", True)


def _serve(status: int, body: bytes) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server 的名字
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.serving = threading.Thread(target=server.serve_forever, daemon=True)
    server.serving.start()
    return server


def _stop(server: ThreadingHTTPServer) -> None:
    """停掉一个 `_serve` 起的服务:shutdown() 停掉 serve_forever 的循环,server_close() 关掉监听的套接字
    (不关的话 fd 留到进程退出),再等服务线程走完 —— 测试结束时还活着的线程会让这条测试红(tests/conftest.py)。"""
    server.shutdown()
    server.server_close()
    server.serving.join(timeout=30)


@pytest.fixture
def system_proxy(monkeypatch) -> Iterator[int]:
    """一个「系统代理」:谁来都回 502。返回本机模型服务的端口。"""
    proxy = _serve(502, b'{"error": "from the proxy"}')
    local = _serve(200, json.dumps({"data": [{"id": "qwen3:32b"}]}).encode())
    for key in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    for key in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(key, f"http://127.0.0.1:{proxy.server_address[1]}")
    try:
        yield local.server_address[1]
    finally:
        _stop(proxy)
        _stop(local)


def test_模拟成立_不处理的话本机请求进了代理(system_proxy: int) -> None:
    with httpx.Client(timeout=5) as client:
        assert client.get(f"http://127.0.0.1:{system_proxy}/v1/models").status_code == 502


def test_供应商调用_本机地址直连(system_proxy: int) -> None:
    with RetryingClient(timeout=5, max_retries=0) as client:
        response = client.get(f"http://127.0.0.1:{system_proxy}/v1/models")
    assert response.status_code == 200, "本机的模型服务被送进了代理"


def test_列模型_本机地址直连(system_proxy: int) -> None:
    model_catalog.clear_cache()
    models = model_catalog.fetch_models(f"http://127.0.0.1:{system_proxy}/v1", "", use_cache=False)
    assert [model.id for model in models] == ["qwen3:32b"]


def test_调用方自己给的_mounts_照样生效(system_proxy: int) -> None:
    hit: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hit.append(str(request.url))
        return httpx.Response(204)

    with RetryingClient(timeout=5, max_retries=0, mounts={"all://example.test": httpx.MockTransport(handler)}) as client:
        assert client.get("http://example.test/x").status_code == 204
    assert hit == ["http://example.test/x"]
