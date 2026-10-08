"""后端发出去的每一个请求、每一跳,都过同一道出站检查(core/outbound_guard)。

检查装在发请求的那一层,而不是靠每个调用点记得先问一句:httpx 的请求经 `RetryingClient` 缺省带着的传输层,不经 httpx 的
(yt-dlp、websocket、远程 MCP)经本进程里的守卫代理(core/outbound_proxy)。规则按地址的出处分:

- 别人给的地址(用户、模板、智能体给的链接,和一路跟过去的每一跳):哪种部署都只许去公网,除非部署管理员放行;
- 部署配的地址(内置服务、连接里填的地址,和这些服务回给我们去取的地址):桌面版照连;多人共用的部署里和别人给的一样。

每条都看**过程**:被拒时那台服务一个连接都没收到(真的起一个监听的 socket 数连接);放行时请求确实到了。
"""

from __future__ import annotations

import ast
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.ai import media_transfer, model_catalog
from app.ai.sidecar import pi_client
from app.core import outbound_guard, outbound_proxy
from app.core.config import settings
from app.core.http_retry import RetryingClient
from app.core.outbound_guard import Origin, OutboundBlocked
from app.media import ytdlp
from tests.util import fresh_client

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture(autouse=True)
def _team_deployment(monkeypatch):
    """缺省是多人共用的部署(测试套本来就是);要看桌面版的用例自己改。代理变量摘掉,看直连那条路。"""
    monkeypatch.setattr(settings, "local_desktop", False)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    #: 进程里没有代理变量时会去读操作系统的代理设置:开发机上常开着一个,CI 上没有 —— 这里看的是直连那条路。
    import urllib.request

    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)


class _Server:
    """本机一个真的 HTTP 服务,**按连接数**记账。`redirect_to` 给了就一律 302 过去;否则回 `body`。"""

    def __init__(self, *, redirect_to: str = "", body: bytes = b'{"data": []}', content_type: str = "application/json",
                 says_length: bool = True):
        self.connections = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _answer(self, with_body: bool) -> None:
                if outer.redirect_to:
                    self.send_response(302)
                    self.send_header("Location", outer.redirect_to)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                if says_length:
                    self.send_header("Content-Length", str(len(body)))
                else:
                    #: 不说多长,发完就关 —— 上限得边收边数,不能只看对面说的长度。
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                if with_body:
                    self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                self._answer(True)

            def do_HEAD(self) -> None:  # noqa: N802
                self._answer(False)

            def log_message(self, *_args) -> None:
                return None

        class Counting(ThreadingHTTPServer):
            daemon_threads = True

            def get_request(self):
                pair = super().get_request()
                outer.connections += 1
                return pair

        self.redirect_to = redirect_to
        self.server = Counting(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=30)


@pytest.fixture
def servers():
    made: list[_Server] = []

    def make(**kwargs) -> _Server:
        one = _Server(**kwargs)
        made.append(one)
        return one

    yield make
    for one in made:
        one.stop()


# ---- 棘轮:发请求只有那几个口子 ----

#: 允许直接碰 httpx / httpx2 的地方,和为什么。
_RAW_HTTP_ALLOWED = {
    "core/outbound_guard.py": "那道闸本身:它的传输层里套着真正发请求的 httpx 传输",
    "domain/plugins/mcp_bridge.py": "远程 MCP 用的是 SDK 要的 httpx2,经守卫代理出去(proxy= 那张票)",
}
#: 允许用 urllib 发请求的地方:只有看护自己起的子进程(本机服务的健康检查,地址是代码按它自己分的端口拼的)。
_URLLIB_ALLOWED = {"domain/local_services/supervisor.py"}
_HTTP_CALLS = {"Client", "AsyncClient", "get", "post", "put", "patch", "delete", "head", "options", "request", "stream",
               "HTTPTransport", "AsyncHTTPTransport"}


def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def test_发请求只有那几个口子() -> None:
    """后端往外发 HTTP 一律经 RetryingClient(带着闸)、outbound_guard.send 或守卫代理。直接 new 一个 httpx 客户端、
    给 RetryingClient 换传输层(transport= / mounts=)都是绕开那道闸;websocket 要经守卫代理(proxy=)。"""
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree):
            func = call.func
            keywords = {keyword.arg for keyword in call.keywords}
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in ("httpx", "httpx2")
                and func.attr in _HTTP_CALLS
            ):
                if rel not in _RAW_HTTP_ALLOWED:
                    offenders.append(f"{rel}:{call.lineno} {func.value.id}.{func.attr}(…)")
                elif rel == "domain/plugins/mcp_bridge.py" and "proxy" not in keywords:
                    offenders.append(f"{rel}:{call.lineno} httpx2 客户端没经守卫代理")
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "RetryingClient" and rel != "core/outbound_guard.py" and keywords & {"transport", "mounts"}:
                offenders.append(f"{rel}:{call.lineno} RetryingClient(transport= / mounts=)")
            if name == "connect" and isinstance(func, ast.Attribute) and getattr(func.value, "id", "") == "websockets":
                if "proxy" not in keywords:
                    offenders.append(f"{rel}:{call.lineno} websockets.connect 没经守卫代理")
            if name in ("urlopen", "build_opener") and rel not in _URLLIB_ALLOWED:
                offenders.append(f"{rel}:{call.lineno} urllib.{name}")
    assert offenders == [], "这些请求绕开了出站检查:\n  " + "\n  ".join(offenders)


# ---- 部署配的地址:桌面版照连,多人共用的部署里要放行 ----


def _connection(client, base_url: str) -> str:
    created = client.post("/api/settings/providers", json={
        "name": "本机端点", "vendor": "openai-compatible",
        "config": {"base_url": base_url, "default_model": "m", "api_key": "k"},
    })
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_多人部署里_连接填的内网地址探活被拦_那台服务一个连接都没收到_说清怎么放行(servers) -> None:
    local = servers()
    client = fresh_client()
    connection = _connection(client, f"{local.url}/v1")

    health = client.get(f"/api/settings/providers/{connection}/health").json()

    assert health["online"] is False
    assert f"127.0.0.1:{local.port}" in health["detail"], "要说清把哪一项加进允许名单"
    assert local.connections == 0


def test_多人部署里_放行之后照常连(servers) -> None:
    local = servers()
    client = fresh_client()
    connection = _connection(client, f"{local.url}/v1")
    outbound_guard.set_allowlist([f"127.0.0.1:{local.port}"])

    health = client.get(f"/api/settings/providers/{connection}/health").json()

    assert health["online"] is True, health
    assert local.connections >= 1


def test_桌面版_连接填的本机地址照连(servers, monkeypatch) -> None:
    """本机的 Ollama、LM Studio 就在回环上:配它的就是这台电脑的主人。"""
    monkeypatch.setattr(settings, "local_desktop", True)
    local = servers()
    client = fresh_client()
    connection = _connection(client, f"{local.url}/v1")

    assert client.get(f"/api/settings/providers/{connection}/health").json()["online"] is True
    assert local.connections >= 1


def test_多人部署里_列模型也过检查(servers) -> None:
    local = servers(body=b'{"data": [{"id": "m"}]}')
    model_catalog.clear_cache()

    assert model_catalog.fetch_models(f"{local.url}/v1", "k", use_cache=False) == []
    assert local.connections == 0
    outbound_guard.set_allowlist([f"127.0.0.1:{local.port}"])
    assert [one.id for one in model_catalog.fetch_models(f"{local.url}/v1", "k", use_cache=False)] == ["m"]


def test_对话调用被拦时_说的是被拦的那一句_不是回的结构不认识(servers) -> None:
    from app.domain.ai_chat import AiChatError, ChatTarget, chat

    local = servers()
    with pytest.raises(AiChatError) as caught:
        chat(ChatTarget(base_url=f"{local.url}/v1", api_key="k", model="m"), [{"role": "user", "content": "hi"}],
             max_retries=0)

    assert caught.value.key == "outboundErr_privateConfigured"
    assert local.connections == 0


def test_成片下载_每一跳都查_放行的那一跳跳去没放行的地方_那边一个连接都没收到(servers, tmp_path) -> None:
    inner = servers(body=b"secret", content_type="video/mp4")
    first = servers(redirect_to=f"{inner.url}/x.mp4")
    outbound_guard.set_allowlist([f"127.0.0.1:{first.port}"])

    with pytest.raises(OutboundBlocked):
        media_transfer.download_to_path(f"{first.url}/out.mp4", tmp_path / "out.mp4", timeout=10)

    assert first.connections >= 1 and inner.connections == 0
    assert not (tmp_path / "out.mp4").exists() and not (tmp_path / "out.mp4.part").exists()


@pytest.mark.parametrize("says_length", [True, False], ids=["说了长度", "不说长度"])
def test_成片下载有上限_超了就停_半截不留(servers, tmp_path, says_length) -> None:
    big = servers(body=b"x" * 4096, content_type="video/mp4", says_length=says_length)
    outbound_guard.set_allowlist([f"127.0.0.1:{big.port}"])

    with pytest.raises(media_transfer.MediaDownloadError):
        media_transfer.download_to_path(f"{big.url}/out.mp4", tmp_path / "out.mp4", timeout=10, max_bytes=1024)

    assert not (tmp_path / "out.mp4").exists() and not (tmp_path / "out.mp4.part").exists()


def test_桌面版_服务商回给我们的下载地址照取(servers, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    local = servers(body=b"frames", content_type="video/mp4")

    media_transfer.download_to_path(f"{local.url}/out.mp4", tmp_path / "out.mp4", timeout=10)

    assert (tmp_path / "out.mp4").read_bytes() == b"frames"


# ---- 别人给的地址:哪种部署都查 ----


def test_参考图链接是别人给的_桌面版也只许公网(servers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    local = servers(body=b"\x89PNG", content_type="image/png")

    with pytest.raises(OutboundBlocked) as caught:
        media_transfer.fetch_bytes(f"{local.url}/ref.png", timeout=10)

    assert caught.value.key == "outboundErr_private"
    assert local.connections == 0


def test_参考图链接_放行的地址跳去没放行的地方也拦(servers) -> None:
    inner = servers(body=b"\x89PNG", content_type="image/png")
    first = servers(redirect_to=f"{inner.url}/ref.png")
    outbound_guard.set_allowlist([f"127.0.0.1:{first.port}"])

    with pytest.raises(OutboundBlocked):
        media_transfer.fetch_bytes(f"{first.url}/ref.png", timeout=10)

    assert inner.connections == 0


# ---- 网络层:连的是查过的那个 IP ----


def test_传输层连查过的那个IP_名字留在Host和SNI里_每个名字一个连接池(monkeypatch) -> None:
    seen: list[tuple[str, str, str]] = []
    made: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        #: 发出去那一刻的样子(发完传输层把地址换回原来的名字)。
        seen.append((request.url.host, request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(200)

    def transport(**options):
        made.append(options)
        return httpx.MockTransport(handler)

    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(outbound_guard.httpx, "HTTPTransport", transport)
    with RetryingClient(timeout=5, max_retries=0) as client:
        client.get("https://api.example.com/v1/models")
        client.get("https://other.example.com/v1/models")

    assert seen == [
        ("93.184.216.34", "api.example.com", "api.example.com"),
        ("93.184.216.34", "other.example.com", "other.example.com"),
    ]
    assert len(made) == 2, "两个名字解析到同一个 IP 时不能共用一个连接池"


def test_跟随重定向时_上一跳的SNI不带到下一跳(monkeypatch) -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.extensions.get("sni_hostname")))
        if request.headers["host"] == "a.example":
            return httpx.Response(302, headers={"location": "https://93.184.216.35/next"})
        return httpx.Response(200)

    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(outbound_guard.httpx, "HTTPTransport", lambda **options: httpx.MockTransport(handler))
    with RetryingClient(timeout=5, max_retries=0, follow_redirects=True) as client:
        assert client.get("https://a.example/start").status_code == 200

    assert seen == [("93.184.216.34", "a.example"), ("93.184.216.35", None)]


def test_走代理时_本机解析出来的地址只拿来挡明摆着的内网(monkeypatch) -> None:
    """连接由代理发起:本机解析出的不是全局地址、又不是内网的那几类,不当成要连的地方。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp:3128")
    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["2001::1"])
    assert outbound_guard.check("https://video.example/").proxy == "http://proxy.corp:3128"
    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["10.1.2.3"])
    with pytest.raises(OutboundBlocked):
        outbound_guard.check("https://video.example/")

    monkeypatch.delenv("HTTPS_PROXY")
    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["2001::1"])
    with pytest.raises(OutboundBlocked):
        outbound_guard.check("https://video.example/")


# ---- 不经 httpx 的:守卫代理 ----


def _raw(port: int, payload: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(payload)
        chunks = b""
        while True:
            data = sock.recv(65536)
            if not data:
                return chunks
            chunks += data


def test_守卫代理只认发出去的票_收回之后就不认(servers) -> None:
    local = servers()
    outbound_guard.set_allowlist([f"127.0.0.1:{local.port}"])
    with outbound_proxy.ticket(Origin.GIVEN) as issued:
        port = httpx.URL(issued.url).port
        with httpx.Client(proxy=issued.url, trust_env=False, timeout=10) as client:
            assert client.get(f"{local.url}/v1").status_code == 200
        no_ticket = _raw(port, f"GET {local.url}/v1 HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert no_ticket.startswith(b"HTTP/1.1 407")
    with httpx.Client(proxy=issued.url, trust_env=False, timeout=10) as client:
        assert client.get(f"{local.url}/v1").status_code == 407, "票收回之后还能用"


def test_守卫代理_被拒的那一句记在票上_那边一个连接都没收到(servers) -> None:
    local = servers()
    with outbound_proxy.ticket(Origin.GIVEN) as issued:
        with httpx.Client(proxy=issued.url, trust_env=False, timeout=10) as client:
            assert client.get(f"{local.url}/v1").status_code == 403
    assert isinstance(issued.refused, OutboundBlocked) and issued.refused.key == "outboundErr_private"
    assert local.connections == 0


def _mp4(tmp_path: Path) -> bytes:
    clip = tmp_path / "clip.mp4"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=60)
    return clip.read_bytes()


def test_从链接导入_yt_dlp_跟过去的那一跳也查_那边一个连接都没收到(servers, tmp_path) -> None:
    inner = servers(body=_mp4(tmp_path), content_type="video/mp4")
    first = servers(redirect_to=f"{inner.url}/clip.mp4")
    outbound_guard.set_allowlist([f"127.0.0.1:{first.port}"])

    with pytest.raises(ytdlp.YtdlpError) as caught:
        ytdlp.probe(f"{first.url}/clip.mp4")

    assert caught.value.key == "outboundErr_private", "说的要是被拦的那一句,不是「代理拒绝了隧道」"
    assert first.connections >= 1 and inner.connections == 0


def test_从链接导入_每一跳都放行时照常探到(servers, tmp_path) -> None:
    inner = servers(body=_mp4(tmp_path), content_type="video/mp4")
    first = servers(redirect_to=f"{inner.url}/clip.mp4")
    outbound_guard.set_allowlist([f"127.0.0.1:{first.port}", f"127.0.0.1:{inner.port}"])

    listing = ytdlp.probe(f"{first.url}/clip.mp4")

    assert len(listing.entries) == 1 and inner.connections >= 1


def test_websocket_也过检查(monkeypatch) -> None:
    from app.ai.providers.adapters.bytedance.volcano import podcast

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.5)
    port = listener.getsockname()[1]
    try:
        with pytest.raises(OutboundBlocked):
            podcast.synthesize_volcano_podcast("app", "token", input_text="x", speakers=["a", "b"],
                                               endpoint=f"ws://127.0.0.1:{port}/api")
        with pytest.raises(TimeoutError):
            listener.accept()
    finally:
        listener.close()


def test_智能体对话进程自己连供应商_交接时先查(monkeypatch) -> None:
    with pytest.raises(OutboundBlocked):
        pi_client._provider_frame({"base_url": "http://127.0.0.1:11434/v1", "vendor": "openai-compatible"})
    monkeypatch.setattr(settings, "local_desktop", True)
    assert pi_client._provider_frame({"base_url": "http://127.0.0.1:11434/v1"})["baseUrl"] == "http://127.0.0.1:11434/v1"
