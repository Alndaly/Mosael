"""本进程里的守卫代理:给不经 httpx 的出网用 —— yt-dlp(和它调起的 ffmpeg)、websocket、远程 MCP —— 让它们的每一条
连接也过同一道出站检查(core/outbound_guard.check),直连时连查过的那个 IP。

它们都认「HTTP 代理」:把代理地址设成这里,每一条连接(含跟随重定向之后新开的那一条)就都先到这儿。

- **只听本机回环,只认票**:每一批请求用一张票(`ticket()`,代理地址里的用户名和密码),票上写着这批请求的出处
  (见 outbound_guard.Origin)和往外走哪条路(照环境、直连、某个代理)。没带票、票不对的一律拒;用完把票收回。
- **两种请求**:CONNECT(https、wss —— 隧道,里面的 TLS 由客户端自己和对面握,证书照常按名字校验)和明文 http 的
  绝对地址。明文的那种一条连接只转一个请求(`Connection: close`):同一条连接上的下一个请求可能去别处,得重新判。
- **被拒的那一句留在票上**(`Ticket.refused`):yt-dlp 这类客户端只会报「代理拒绝了隧道」,用它的地方拿这句原话告诉用户
  为什么、怎么放行。

住在 core:它只是 socket 加 outbound_guard,没有数据库。
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import logging
import secrets
import select
import socket
import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx

from app.core import outbound_guard
from app.core.outbound_guard import FOLLOW_ENVIRONMENT, Origin, OutboundBlocked, Route

logger = logging.getLogger(__name__)

#: 请求头最多读多少、等多久:代理这一头只需要请求行和头,正文原样往下转。
_HEAD_LIMIT = 64 * 1024
_HEAD_TIMEOUT = 30.0
_CONNECT_TIMEOUT = 30.0
#: 隧道里多久一个字节都没走就收掉。长下载一直有数据在走,不受影响。
_IDLE_TIMEOUT = 300.0
_USER = "mosael"


@dataclass
class Ticket:
    """一批请求的票:出处、往外走哪条路,和代理地址(交给客户端)。被拒过的那一句记在 `refused` 上(只记第一句)。"""

    origin: Origin
    route: Route
    url: str = ""
    refused: OutboundBlocked | None = None
    _token: str = field(default="", repr=False)


_tickets: dict[str, Ticket] = {}
_server: _Server | None = None
_lock = threading.Lock()


@contextmanager
def ticket(origin: Origin, *, route: Route = FOLLOW_ENVIRONMENT) -> Iterator[Ticket]:
    """开一张票,用完收回。`with ticket(Origin.GIVEN) as one: ...(proxy=one.url)`。"""
    token = secrets.token_urlsafe(24)
    with _lock:
        port = _running().server_address[1]
        issued = Ticket(origin=origin, route=route, url=f"http://{_USER}:{token}@127.0.0.1:{port}", _token=token)
        _tickets[token] = issued
    try:
        yield issued
    finally:
        with _lock:
            _tickets.pop(token, None)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    block_on_close = False


def _serve_outbound_proxy(server: _Server) -> None:
    server.serve_forever()


def _running() -> _Server:
    """要用时才起;起来之后跟进程同生同死(调用方持着 `_lock`)。"""
    global _server
    if _server is None:
        server = _Server(("127.0.0.1", 0), _Handler)
        threading.Thread(target=_serve_outbound_proxy, args=(server,), daemon=True).start()
        _server = server
    return _server


def _ticket_of(headers: list[tuple[str, str]]) -> Ticket | None:
    for name, value in headers:
        if name.lower() != "proxy-authorization":
            continue
        scheme, _, encoded = value.strip().partition(" ")
        if scheme.lower() != "basic":
            return None
        try:
            user, _, token = base64.b64decode(encoded.strip()).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return None
        with _lock:
            found = _tickets.get(token)
        return found if found is not None and secrets.compare_digest(user, _USER) else None
    return None


def _read_head(client: socket.socket) -> tuple[str, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        if len(data) > _HEAD_LIMIT:
            raise ValueError("request head too large")
        chunk = client.recv(8192)
        if not chunk:
            raise ValueError("connection closed before the request head")
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return head.decode("latin-1"), rest


def _answer(client: socket.socket, status: int, reason: str, text: str = "", extra: str = "") -> None:
    body = text.encode("utf-8")
    try:
        client.sendall(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\n"
            f"Connection: close\r\n{extra}\r\n".encode("latin-1") + body
        )
    except OSError:
        pass


def _authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _split_authority(target: str) -> tuple[str, int]:
    """CONNECT 的目标 `host:port` / `[v6]:port`。"""
    if target.startswith("["):
        host, _, rest = target[1:].partition("]")
        port = rest.removeprefix(":")
    else:
        host, _, port = target.rpartition(":")
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"bad CONNECT target: {target[:200]}")
    return host, int(port)


class _UpstreamRefused(OSError):
    """下一跳的代理不肯转(回了非 200,或者 socks 握手没过)。"""


def _via_http_proxy(proxy: httpx.URL, authority: str) -> socket.socket:
    upstream = socket.create_connection((proxy.host, proxy.port or 80), timeout=_CONNECT_TIMEOUT)
    head = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
    if proxy.username or proxy.password:
        pair = f"{proxy.username}:{proxy.password}".encode()
        head += f"Proxy-Authorization: Basic {base64.b64encode(pair).decode('ascii')}\r\n"
    upstream.sendall((head + "\r\n").encode("latin-1"))
    reply, _rest = _read_head(upstream)
    status = reply.split(" ", 2)[1:2]
    if status != ["200"]:
        upstream.close()
        raise _UpstreamRefused(f"upstream proxy answered: {reply.splitlines()[0][:200] if reply else ''}")
    return upstream


def _recv_exactly(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise _UpstreamRefused("socks proxy closed the connection")
        data += chunk
    return data


def _via_socks_proxy(proxy: httpx.URL, host: str, port: int) -> socket.socket:
    """SOCKS5 的 CONNECT(可带用户名密码)。名字交给代理去解析,和 socks5h 一样 —— 走代理时连接本来就由它发起。"""
    upstream = socket.create_connection((proxy.host, proxy.port or 1080), timeout=_CONNECT_TIMEOUT)
    user, password = proxy.username, proxy.password
    upstream.sendall(b"\x05\x02\x00\x02" if user or password else b"\x05\x01\x00")
    version, method = _recv_exactly(upstream, 2)
    if version != 5 or method not in (0, 2):
        upstream.close()
        raise _UpstreamRefused("socks proxy refused the handshake")
    if method == 2:
        name, secret = user.encode(), password.encode()
        upstream.sendall(bytes([1, len(name)]) + name + bytes([len(secret)]) + secret)
        if _recv_exactly(upstream, 2)[1] != 0:
            upstream.close()
            raise _UpstreamRefused("socks proxy refused the credentials")
    try:
        address = ipaddress.ip_address(host)
        target = (b"\x01" if address.version == 4 else b"\x04") + address.packed
    except ValueError:
        encoded = host.encode("idna")
        target = b"\x03" + bytes([len(encoded)]) + encoded
    upstream.sendall(b"\x05\x01\x00" + target + port.to_bytes(2, "big"))
    reply = _recv_exactly(upstream, 4)
    if reply[1] != 0:
        upstream.close()
        raise _UpstreamRefused(f"socks proxy could not connect (code {reply[1]})")
    bound = {1: 4, 4: 16}.get(reply[3])
    _recv_exactly(upstream, (bound if bound is not None else _recv_exactly(upstream, 1)[0]) + 2)
    return upstream


def _open(destination: outbound_guard.Destination) -> socket.socket:
    """连过去:直连时连查过的那个 IP(没查的连名字),走代理时让那个代理去连。"""
    if destination.proxy:
        proxy = httpx.URL(destination.proxy)
        if proxy.scheme.startswith("socks"):
            return _via_socks_proxy(proxy, destination.host, destination.port)
        return _via_http_proxy(proxy, _authority(destination.host, destination.port))
    return socket.create_connection((destination.address or destination.host, destination.port), timeout=_CONNECT_TIMEOUT)


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """两头对拷,直到一头关了或者闲太久。"""
    for one in (a, b):
        one.settimeout(None)
    try:
        while True:
            readable, _, _ = select.select([a, b], [], [], _IDLE_TIMEOUT)
            if not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (b if source is a else a).sendall(data)
    except OSError:
        return
    finally:
        for one in (a, b):
            try:
                one.close()
            except OSError:
                pass


#: 转明文请求时不往下带的头:给我们这一跳的(代理认证)、管连接去留的(一条连接只转一个请求)。
_HOP_HEADERS = frozenset({"proxy-authorization", "proxy-connection", "connection", "keep-alive"})


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client: socket.socket = self.request
        client.settimeout(_HEAD_TIMEOUT)
        try:
            head, rest = _read_head(client)
        except (OSError, ValueError):
            client.close()
            return
        lines = head.split("\r\n")
        parts = lines[0].split(" ")
        headers = [(name.strip(), value.strip()) for name, _, value in (line.partition(":") for line in lines[1:])]
        issued = _ticket_of(headers)
        if issued is None:
            _answer(client, 407, "Proxy Authentication Required", extra='Proxy-Authenticate: Basic realm="mosael"\r\n')
            client.close()
            return
        if len(parts) != 3:
            _answer(client, 400, "Bad Request")
            client.close()
            return
        method, target, version = parts
        try:
            if method.upper() == "CONNECT":
                host, port = _split_authority(target)
                destination = outbound_guard.check(f"https://{_authority(host, port)}/", origin=issued.origin, route=issued.route)
                upstream = _open(destination)
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                url = httpx.URL(target)
                if url.scheme != "http":
                    raise ValueError(f"not an absolute http address: {target[:200]}")
                destination = outbound_guard.check(url, origin=issued.origin, route=issued.route)
                kept = [(name, value) for name, value in headers if name and name.lower() not in _HOP_HEADERS]
                if not any(name.lower() == "host" for name, _ in kept):
                    kept.insert(0, ("Host", url.netloc.decode("ascii")))
                upstream_proxy = httpx.URL(destination.proxy) if destination.proxy else None
                if upstream_proxy is not None and not upstream_proxy.scheme.startswith("socks"):
                    #: 下一跳是 http 代理:明文请求照代理的规矩发绝对地址(不少代理只许往 443 开隧道)。
                    upstream = socket.create_connection(
                        (upstream_proxy.host, upstream_proxy.port or 80), timeout=_CONNECT_TIMEOUT
                    )
                    request_target = str(url)
                    if upstream_proxy.username or upstream_proxy.password:
                        pair = f"{upstream_proxy.username}:{upstream_proxy.password}".encode()
                        kept.append(("Proxy-Authorization", f"Basic {base64.b64encode(pair).decode('ascii')}"))
                else:
                    upstream = _open(destination)
                    request_target = url.raw_path.decode("ascii") or "/"
                forwarded = f"{method} {request_target} {version}\r\n" + "".join(f"{n}: {v}\r\n" for n, v in kept)
                rest = (forwarded + "Connection: close\r\n\r\n").encode("latin-1") + rest
        except OutboundBlocked as exc:
            if issued.refused is None:
                issued.refused = exc
            logger.info("outbound proxy refused %s (%s)", target[:200], exc.key)
            _answer(client, 403, "Forbidden", str(exc))
            client.close()
            return
        except (OSError, ValueError, httpx.HTTPError) as exc:
            logger.info("outbound proxy could not reach %s: %s", target[:200], exc)
            _answer(client, 502, "Bad Gateway", str(exc)[:300])
            client.close()
            return
        if rest:
            try:
                upstream.sendall(rest)
            except OSError:
                upstream.close()
                client.close()
                return
        _pipe(client, upstream)


__all__ = ["Ticket", "ticket"]
