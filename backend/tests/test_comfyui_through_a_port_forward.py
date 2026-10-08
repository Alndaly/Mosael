"""经端口转发连 ComfyUI(UU 远程、frp、SSH 转发)时不再时好时坏。

现场:维护者的连接是 `http://localhost:8120`,8120 上听着的是 UU 远程,它把端口转发到另一台机器上的 ComfyUI。浏览器打开正常,
插件一半的请求报「连不上这台 ComfyUI」(`Remote end closed connection without response`),6 MB 的 `/object_info` 有时
读到一半就断(`IncompleteRead`)。原因:插件用 urllib,它给每个请求都强行带上 `Connection: close`,UU 的转发碰上这种请求大约
一半会把连接提前断掉;不带这个头的 curl、http.client 各 15 次全成。

这里的替身学 UU:请求里带着 `Connection: close` 就一个字不回、把连接断掉;不带的照常回答、连接留着接着用。另外可以排几次
「发出去就断」「读到一半断」,钉住:GET、HEAD 换一条新连接重来一次,POST 不重来(交出去的任务不能交两遍)。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from collections import deque
from pathlib import Path

import pytest

from app.domain.local_services import supervisor

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
_MODULES = ("comfy_http", "labels", "lines")

#: 大到要分好几次读的一份 `/object_info`(真的那份 6 MB 上下)。
BIG = json.dumps({f"Node{i}": {"input": {"required": {"x": [["a" * 40] * 20]}}} for i in range(3000)}).encode()
ROUTES = {
    "/system_stats": json.dumps({"system": {"comfyui_version": "0.3.99"}, "devices": []}).encode(),
    "/models": json.dumps(["checkpoints", "loras"]).encode(),
    "/object_info": BIG,
    "/i18n": b"{}",
    "/view": bytes(range(256)) * 4096,  # 1 MB 的一份「成片」
    "/prompt": json.dumps({"prompt_id": "p1", "number": 1}).encode(),
}
#: 跳转(反向代理换了路径):照 urllib 的规矩跟。
REDIRECTS = {"/moved_stats": "/system_stats"}


class PortForward:
    """一个学 UU 远程转发的 HTTP/1.1 替身。

    - 请求带着 `Connection: close` → 一个字不回,断开连接(UU 碰上这种请求大约一半如此;这里每次都如此,不靠运气);
    - 不带 → 照常回答,连接留着接着用;
    - `faults` 里排着的,依次用在接下来的请求上:`"drop"` 发出去就断(一个字不回),`"truncate"` 头和一半正文发出去就断。
    记下每个请求:哪条连接(第几条)、方法、路径、头。
    """

    def __init__(self) -> None:
        self.faults: deque[str] = deque()
        self.seen: list[tuple[int, str, str, dict[str, str]]] = []
        self._lock = threading.Lock()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._clients: list[socket.socket] = []
        self._threads: list[threading.Thread] = []
        accept = threading.Thread(target=self._accept, daemon=True)
        self._threads.append(accept)
        accept.start()

    def _accept(self) -> None:
        number = 0
        while True:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            number += 1
            with self._lock:
                self._clients.append(conn)
            handler = threading.Thread(target=self._serve, args=(conn, number), daemon=True)
            with self._lock:
                self._threads.append(handler)
            handler.start()

    def _serve(self, conn: socket.socket, number: int) -> None:
        buffer = b""
        try:
            while True:
                while b"\r\n\r\n" not in buffer:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buffer += chunk
                head, _, buffer = buffer.partition(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                method, target, _version = lines[0].split(" ", 2)
                headers = {name.strip().lower(): value.strip() for name, _, value in (line.partition(":") for line in lines[1:])}
                length = int(headers.get("content-length") or 0)
                while len(buffer) < length:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buffer += chunk
                buffer = buffer[length:]
                path = target.split("?", 1)[0]
                with self._lock:
                    self.seen.append((number, method, path, headers))
                    fault = self.faults.popleft() if self.faults else ""
                if headers.get("connection", "").lower() == "close" or fault == "drop":
                    return  # UU 的样子:一个字不回,断开
                if path in REDIRECTS:
                    location = REDIRECTS[path].encode()
                    conn.sendall(b"HTTP/1.1 302 Found\r\nLocation: " + location + b"\r\nContent-Length: 0\r\n\r\n")
                    continue
                body = ROUTES.get(path)
                if body is None:
                    conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\nContent-Type: text/plain\r\n\r\nnot found")
                    continue
                kind = b"application/octet-stream" if path == "/view" else b"application/json"
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: " + kind + b"\r\nContent-Length: "
                             + str(len(body)).encode() + b"\r\n\r\n")
                if method == "HEAD":
                    continue
                if fault == "truncate":
                    conn.sendall(body[: len(body) // 2])
                    return  # 读到一半断了
                conn.sendall(body)
        except OSError:
            return
        finally:
            conn.close()

    def requests(self, method: str, path: str) -> list[int]:
        """这个请求一共到过几次,各在哪条连接上。"""
        with self._lock:
            return [number for number, seen_method, seen_path, _ in self.seen if (seen_method, seen_path) == (method, path)]

    def close(self) -> None:
        # 先 shutdown 再 close:Linux 上只 close 叫不醒阻塞在 accept() 里的线程
        try:
            self._listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._listener.close()
        with self._lock:
            clients, threads = list(self._clients), list(self._threads)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for thread in threads:
            thread.join(timeout=30)


@pytest.fixture
def forward():
    one = PortForward()
    yield one
    one.close()


@pytest.fixture
def comfy_http():
    """插件的模块名很普通,用完就从 sys.modules 摘掉,不串到别的测试里。"""
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import comfy_http

        yield comfy_http
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def test_经转发连_每样连读二十次都成功_不发_Connection_close_一条连接接着用(forward: PortForward, comfy_http) -> None:
    with comfy_http.Comfy(forward.url) as comfy:
        for _ in range(20):
            assert comfy.system_stats()["system"]["comfyui_version"] == "0.3.99"
            assert comfy.model_folders() == ["checkpoints", "loras"]
            assert len(comfy.object_info()) == 3000
            assert comfy.head_length("/object_info") == len(BIG)
    assert not [headers for *_, headers in forward.seen if "connection" in headers], "请求里不该带 Connection 头"
    used = {number for number, *_ in forward.seen}
    assert used == {1}, f"一个 Comfy 里应该一直用同一条连接,实际开了 {len(used)} 条"


def test_GET_发出去就被断开_换一条新连接重来一次(forward: PortForward, comfy_http) -> None:
    forward.faults.append("drop")
    with comfy_http.Comfy(forward.url) as comfy:
        assert comfy.system_stats()["system"]["comfyui_version"] == "0.3.99"
    tried = forward.requests("GET", "/system_stats")
    assert len(tried) == 2 and tried[0] != tried[1], f"该在一条新连接上重来一次:{tried}"


def test_GET_读到一半断了_换一条新连接重来一次(forward: PortForward, comfy_http) -> None:
    forward.faults.append("truncate")
    with comfy_http.Comfy(forward.url) as comfy:
        assert len(comfy.object_info()) == 3000
    tried = forward.requests("GET", "/object_info")
    assert len(tried) == 2 and tried[0] != tried[1], f"读到一半断了该重来一次:{tried}"


def test_下载成片读到一半断了_重来一次_文件是完整的(forward: PortForward, comfy_http, tmp_path: Path) -> None:
    forward.faults.append("truncate")
    with comfy_http.Comfy(forward.url) as comfy:
        saved = comfy.download({"filename": "a.png"}, tmp_path / "a.png")
    assert saved.read_bytes() == ROUTES["/view"]
    assert len(forward.requests("GET", "/view")) == 2


def test_POST_被断开_不重来_报连不上(forward: PortForward, comfy_http) -> None:
    forward.faults.append("drop")
    with comfy_http.Comfy(forward.url) as comfy, pytest.raises(comfy_http.ComfyError) as caught:
        comfy.post("/prompt", {"prompt": {}})
    assert len(forward.requests("POST", "/prompt")) == 1, "交出去的任务不能交两遍"
    first, _, detail = caught.value.said["zh"].partition("\n")
    assert first == "连不上这台 ComfyUI,确认它在运行、地址填对", "第一行是给人看的那句"
    assert forward.url in detail, "地址和原文在下一行"


def test_重来也只重来一次(forward: PortForward, comfy_http) -> None:
    forward.faults.extend(["drop", "drop"])
    with comfy_http.Comfy(forward.url) as comfy, pytest.raises(comfy_http.ComfyError):
        comfy.system_stats()
    assert len(forward.requests("GET", "/system_stats")) == 2


def test_宿主的健康检查经转发也问得到(forward: PortForward) -> None:
    """本机服务的健康检查(宿主自己问)也不带 `Connection: close`。"""
    assert supervisor.healthy(f"{forward.url}/system_stats")
    assert not supervisor.healthy(f"{forward.url}/nothing-here")
    assert not [headers for *_, headers in forward.seen if "connection" in headers]


def test_GET_跟着跳转走_POST_不跟_307(forward: PortForward, comfy_http) -> None:
    """换成 http.client 之后跳转要自己跟:GET 跟到底;POST 碰上 302 照 urllib 改成不带正文的 GET。"""
    with comfy_http.Comfy(forward.url) as comfy:
        assert comfy.get("/moved_stats")["system"]["comfyui_version"] == "0.3.99"
        assert comfy.post("/moved_stats", {"x": 1})["system"]["comfyui_version"] == "0.3.99"
    assert forward.requests("GET", "/system_stats"), "跳转后的地址没被问到"
