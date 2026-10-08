"""出站请求的那一道检查:后端发出去的每一个请求、每一跳,都在这里判能不能去。

## 一道闸,装在网络层

判据只有一份(`check`),装在发请求的那一层,而不是靠每个调用点记得先问一句:
- httpx:`RetryingClient` 缺省就用 `GuardedTransport`,每一跳(含跟随的重定向)发出之前都过 `check`;
- 不经 httpx 的(yt-dlp 和它调起的 ffmpeg、websocket、远程 MCP):走本进程里的守卫代理(core/outbound_proxy),
  代理在每条连接发出之前过同一个 `check`;
- `send`:用户给的地址要自己管重定向时的改写规则(见下),也是同一个 `check`。

## 地址的出处

- **别人给的**(`Origin.GIVEN`):工作流的 HTTP 请求节点、智能体的 http_request / fetch_url、从链接导入素材
  (和它一路跟过去的每一跳)、生成参数里填的图片地址。哪种部署都只许去公网,除非部署管理员把那个地址放进了允许名单。
- **部署配的**(`Origin.CONFIGURED`):内置的服务地址、连接里填的地址,以及这些服务回给我们去取的地址。
  桌面版照连 —— 本机的模型服务就在回环上,配它的就是这台电脑的主人;多人共用的部署里,它们和别人给的一样
  只许去公网 —— 连接是每个成员自己填的。

## 为什么要有

这些能力的地址是用户、模板、模型写的。不拦的话,它们就是一条「借这台服务器摸进内网」的路:
`http://127.0.0.1:…` 打本机上没有鉴权的服务(Ollama 能删模型、ComfyUI 能跑任意节点),`192.168.x.x`
打路由器和 NAS,`169.254.169.254` 拿云服务器的元数据和临时凭据。社区里分享的模板、网页里藏着的提示词
注入,都能把这样一个地址塞进来,而跑的人不会逐个去看 URL。

## 怎么判

- **按解析出来的 IP 判,不按名字判**:`localhost`、`foo.internal`、`127.0.0.1.nip.io` 写法无穷,解析结果
  只有一个。只认全局单播地址(`ipaddress` 的 is_global、且不是组播);IPv4 映射 / 6to4 包着的 v4 地址拆开再判。
  一个名字解析出好几个地址时,**有一个不行就整个不行** —— 否则对方可以一半公网一半内网地赌连接顺序。
- **解析一次、就连那个 IP**(防 DNS 重绑定):先查的和后连的如果各解析一次,对方的 DNS 可以第一次答公网、
  第二次答 127.0.0.1。直连时把请求发到查过的那个 IP,`Host` 头和 TLS 的 SNI / 证书校验仍按原来的名字。
- **重定向每一跳都重新判**:公网页面回一个 `302 http://169.254.169.254/` 是最常见的绕法。
- **走代理时**(进程的 HTTP(S)_PROXY,没有就是操作系统的代理设置;本机回环永远直连,见 `route_for`):连接由代理
  发起,我们连不了「那个 IP」,只能在发出前按本机的解析结果判一次,而且只拿它挡明摆着的内网 —— 本机的解析结果
  不是要连的地方;本机解析不了(只有代理那边能解析的内网环境)就交给代理 —— 它是部署者自己配的出口。

## 怎么放行

部署设置里的允许名单(管理 → 内网访问,存在 DeploymentConfig.outbound_allowlist,启动时和改完时推到这里,
与重试次数同一套做法):每一项是主机名、IP 或 CIDR 网段,主机名和 IP 可以带端口(`127.0.0.1:11434`、
`nas.local`、`10.0.0.0/8`)。**别人给的地址桌面版也默认拒**,包括本机回环 —— 本机回环上恰恰住着最要紧的那些服务
(本应用自己的后端与 sidecar、模型服务、Docker),而导入别人的模板在桌面版上一样常见。

住在 core:它只是 httpx 加 ipaddress,没有数据库;允许名单由 domain/outbound_allowlist 推进来。
"""

from __future__ import annotations

import enum
import ipaddress
import socket
import threading
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple
from urllib.parse import urljoin

import httpx

from app.core import abort
from app.core.config import settings
from app.core.i18n import LocalizedError, fragment

#: 跟随重定向时最多几跳。
MAX_REDIRECTS = 5

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

#: 云服务器的元数据接口。单独认出来只是为了报错时说清「这是元数据」—— 它们本来就不是全局地址。
_METADATA = frozenset(
    ipaddress.ip_address(one)
    for one in (
        "169.254.169.254",  # AWS / GCP / Azure / 腾讯云 / 华为云
        "100.100.100.200",  # 阿里云
        "fd00:ec2::254",  # AWS IPv6
    )
)
_LAN = tuple(ipaddress.ip_network(one) for one in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


class Origin(enum.StrEnum):
    """一个地址是谁定的(见模块说明)。"""

    #: 部署配的:内置的服务地址、连接里填的地址,以及这些服务回给我们去取的地址。
    CONFIGURED = "configured"
    #: 别人给的:用户、模板、智能体、网页给的地址,和从链接导入时一路跟过去的每一跳。
    GIVEN = "given"


class _Route(enum.Enum):
    FOLLOW = "follow"


#: 走不走代理「照这个进程的环境变量判」—— network.apply_to_process 写进去的那一份。
FOLLOW_ENVIRONMENT = _Route.FOLLOW
#: 一个请求走哪条路:照环境变量(FOLLOW_ENVIRONMENT)、直连(None)、或者明说的那个代理地址。
Route = _Route | str | None


def checks(origin: Origin) -> bool:
    """这个出处的地址要不要过检查。只有桌面版上部署配的那些不查(见模块说明)。"""
    return not (origin is Origin.CONFIGURED and settings.local_desktop)


class OutboundBlocked(LocalizedError):
    """这个地址不许去。带文案 key(`outboundErr_*`),参数里说清是哪个地址、为什么、怎么放行。

    **不是 ValueError**:不少调用点用 `except ValueError` 接「回包不是 JSON」,被拦下的请求混进去就成了一句「回的结构不认识」。"""


class ResponseTooLarge(LocalizedError, ValueError):
    """回来的东西比调用方说的上限大:读到上限就停,不把整个塞进内存。带文案 key(`outboundErr_tooLarge`)。"""


class AllowlistError(LocalizedError, ValueError):
    """允许名单里有一项写不对。带文案 key(`outboundErr_badEntry`)。"""


@dataclass(frozen=True)
class AllowEntry:
    """允许名单里的一项:主机名 / IP / 网段,可选端口(网段不带端口)。"""

    text: str
    host: str = ""
    network: IPNetwork | None = None
    port: int | None = None

    def admits(self, host: str, address: IPAddress, port: int) -> bool:
        if self.port is not None and self.port != port:
            return False
        if self.host:
            return self.host == host.lower().rstrip(".")
        assert self.network is not None
        return address in self.network


def _split_port(raw: str) -> tuple[str, int | None]:
    """`host:port` / `[v6]:port` / `1.2.3.4:port` → (主机, 端口)。裸 IPv6 不拆(它自己就带冒号)。"""
    if raw.startswith("["):
        host, _, rest = raw[1:].partition("]")
        if rest and not rest.startswith(":"):
            raise AllowlistError("outboundErr_badEntry", entry=raw)
        return host, _port(rest[1:], raw) if rest else None
    if raw.count(":") == 1:
        host, _, port = raw.partition(":")
        return host, _port(port, raw)
    return raw, None


def _port(text: str, raw: str) -> int:
    if not text.isdigit() or not 0 < int(text) < 65536:
        raise AllowlistError("outboundErr_badEntry", entry=raw)
    return int(text)


def parse_entry(raw: str) -> AllowEntry:
    """一项允许名单 → AllowEntry。写不对抛 AllowlistError(说清是哪一项)。"""
    text = str(raw or "").strip()
    if not text or any(ch.isspace() for ch in text) or "/" in text and ":" in text.split("/")[-1]:
        raise AllowlistError("outboundErr_badEntry", entry=text)
    if "/" in text:
        try:
            return AllowEntry(text=text, network=ipaddress.ip_network(text, strict=False))
        except ValueError as exc:
            raise AllowlistError("outboundErr_badEntry", entry=text) from exc
    host, port = _split_port(text)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        name = host.lower().rstrip(".")
        if not name or any(not (ch.isalnum() or ch in "-._") for ch in name):
            raise AllowlistError("outboundErr_badEntry", entry=text) from None
        return AllowEntry(text=text, host=name, port=port)
    return AllowEntry(text=text, network=ipaddress.ip_network(address), port=port)


def parse_allowlist(entries: Iterable[str]) -> tuple[AllowEntry, ...]:
    return tuple(parse_entry(one) for one in entries if str(one or "").strip())


_allowlist: tuple[AllowEntry, ...] = ()


def set_allowlist(entries: Iterable[str]) -> None:
    """部署设置改完(以及启动时)由 domain/outbound_allowlist 调。"""
    global _allowlist
    _allowlist = parse_allowlist(entries)


def current_allowlist() -> tuple[AllowEntry, ...]:
    return _allowlist


def _unwrapped(address: IPAddress) -> IPAddress:
    """IPv4 映射(::ffff:127.0.0.1)、6to4(2002:7f00:1::)包着的 v4 地址拆出来判 —— 连过去落在的是那个 v4。"""
    if isinstance(address, ipaddress.IPv6Address):
        inner = address.ipv4_mapped or address.sixtofour
        if inner is not None:
            return inner
    return address


def blocked_reason(address: IPAddress) -> str | None:
    """这个地址为什么不许去(文案 key 的后缀);公网地址是 None。"""
    address = _unwrapped(address)
    if address in _METADATA:
        return "metadata"
    if address.is_loopback:
        return "loopback"
    if address.is_unspecified:
        return "unspecified"
    if address.is_link_local:
        return "linkLocal"
    if any(address in network for network in _LAN):
        return "private"
    if address.is_multicast or not address.is_global:
        return "special"
    return None


#: 明摆着是内网的那几类。走代理时只拿本机解析结果挡这几类(见 check)。
_INTERNAL = frozenset({"metadata", "loopback", "unspecified", "linkLocal", "private"})


def lookup(host: str, port: int) -> list[str]:
    """把主机名解析成 IP(去重保序)。单独成一个函数:测试在这里换成假的 DNS。"""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]).split("%", 1)[0] for info in infos))


@dataclass(frozen=True)
class Destination:
    """检查过的一跳:原来的地址,和要连的那个 IP。`address` 为空 = 走代理且本机解析不了,交给代理。"""

    url: httpx.URL
    host: str
    port: int
    address: str
    proxy: str | None


def _suggestion(host: str, port: int, address: IPAddress) -> str:
    """报错里建议加进允许名单的那一项:按原来写的名字(或 IP)加端口。"""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return f"{host}:{port}"
    return f"[{address}]:{port}" if address.version == 6 else f"{address}:{port}"


def _is_loopback_host(host: str) -> bool:
    if host.lower().rstrip(".") == "localhost":
        return True
    try:
        return _unwrapped(ipaddress.ip_address(host)).is_loopback
    except ValueError:
        return False


def route_for(url: httpx.URL, route: Route = FOLLOW_ENVIRONMENT) -> str | None:
    """这一跳交给哪个代理(None = 直连)。**本机回连永远直连**:系统代理、shell 里的老变量都带不来绕过名单,
    本机的服务被送进代理只会收到代理替它回的错(SEC-10)。"""
    if _is_loopback_host(url.host):
        return None
    if route is FOLLOW_ENVIRONMENT:
        return _proxy_for(url)
    return route or None


def _proxy_for(url: httpx.URL) -> str | None:
    """这个地址会不会走代理 —— 和后端的 httpx 一直以来的答案一样:进程的 HTTP(S)_PROXY / NO_PROXY(见 domain/network);
    进程里没有,就是操作系统的代理设置(macOS、Windows)和它的例外名单。"""
    proxies = urllib.request.getproxies()
    if not proxies:
        return None
    host = url.host
    if "no" in proxies:
        if urllib.request.proxy_bypass_environment(host, proxies):
            return None
    elif urllib.request.proxy_bypass(host):
        return None
    scheme = {"ws": "http", "wss": "https"}.get(url.scheme, url.scheme)
    return proxies.get(scheme) or proxies.get("all") or None


#: 认哪几种地址。ws / wss 只来自守卫代理替 websocket 问的那一句(见 core/outbound_proxy)。
_SCHEMES = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def check(
    url: str | httpx.URL,
    *,
    origin: Origin = Origin.GIVEN,
    route: Route = FOLLOW_ENVIRONMENT,
    allowlist: Sequence[AllowEntry] | None = None,
) -> Destination:
    """这一跳能不能去;能去就交回要连的 IP 和走哪个代理。不能去抛 OutboundBlocked,解析不了抛 httpx.ConnectError。

    不用查的(`checks(origin)` 为假)不解析、不改连哪,只定走哪个代理。
    """
    try:
        parsed = httpx.URL(str(url).strip())
    except (httpx.InvalidURL, TypeError, ValueError) as exc:
        raise OutboundBlocked("outboundErr_badUrl", url=str(url)[:200]) from exc
    if parsed.scheme not in _SCHEMES or not parsed.host:
        raise OutboundBlocked("outboundErr_badUrl", url=str(url)[:200])
    host = parsed.host
    port = parsed.port or _SCHEMES[parsed.scheme]
    proxy = route_for(parsed, route)
    if not checks(origin):
        return Destination(url=parsed, host=host, port=port, address="", proxy=proxy)
    try:
        literal: IPAddress | None = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            addresses = [ipaddress.ip_address(one) for one in lookup(host, port)]
        except (OSError, UnicodeError, ValueError) as exc:
            if proxy:
                return Destination(url=parsed, host=host, port=port, address="", proxy=proxy)
            raise httpx.ConnectError(f"cannot resolve {host}: {exc}") from exc
    if not addresses:
        raise httpx.ConnectError(f"cannot resolve {host}")
    entries = _allowlist if allowlist is None else allowlist
    for address in addresses:
        reason = blocked_reason(address)
        if reason is None:
            continue
        if proxy and literal is None and reason not in _INTERNAL:
            #: 走代理时连接由代理发起,本机的解析结果不是要连的地方:只拿它挡明摆着的内网。
            continue
        if not any(entry.admits(host, address, port) for entry in entries):
            raise OutboundBlocked(
                "outboundErr_private" if origin is Origin.GIVEN else "outboundErr_privateConfigured",
                host=host,
                address=str(address),
                reason=fragment(f"outboundReason_{reason}"),
                entry=_suggestion(host, port, address),
            )
    return Destination(url=parsed, host=host, port=port, address=str(addresses[0]), proxy=proxy)


def _pinned(url: httpx.URL, destination: Destination) -> tuple[httpx.URL, dict[str, str]]:
    """直连时把这一跳改成连查过的那个 IP:交回改过的地址和要加的 extensions。名字留在 Host 头和 SNI 里 ——
    虚拟主机按它分站点,证书按它校验。不用改(走代理、没解析、本来就是 IP)时原样交回。"""
    if not destination.address or destination.proxy or destination.address == url.host:
        return url, {}
    extensions = {"sni_hostname": url.raw_host.decode("ascii")} if url.scheme == "https" else {}
    return url.copy_with(host=destination.address), extensions


#: 交给内层 httpx 传输的那几个参数(证书、协议、连接池);别的(超时、头)在 Client 那一层。
TRANSPORT_OPTIONS = ("verify", "cert", "http1", "http2", "limits")


class GuardedTransport(httpx.BaseTransport):
    """httpx 的传输层:每一跳发出之前过 `check`,直连时连查过的那个 IP,走代理时交给那个代理。

    `RetryingClient` 缺省就装它(见 core/http_retry),于是跟随的重定向、重试的每一次都在这里过一遍 —— 不靠调用点记得先问。

    **每个主机名一个连接池**:钉 IP 之后,两个名字解析到同一个 IP 时,连接池会把 A 名字握手的 TLS 连接拿去发 B 名字的请求。
    """

    def __init__(self, origin: Origin, *, route: Route = FOLLOW_ENVIRONMENT, **options: Any) -> None:
        self._origin = origin
        self._route = route
        self._options = {key: value for key, value in options.items() if key in TRANSPORT_OPTIONS}
        self._transports: dict[tuple[str, str], httpx.BaseTransport] = {}
        self._lock = threading.Lock()

    def _transport(self, proxy: str | None, host: str) -> httpx.BaseTransport:
        key = (proxy or "", "" if proxy else host)
        with self._lock:
            transport = self._transports.get(key)
            if transport is None:
                transport = httpx.HTTPTransport(proxy=proxy, trust_env=False, **self._options)
                self._transports[key] = transport
            return transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            destination = check(request.url, origin=self._origin, route=self._route)
        except httpx.ConnectError as exc:
            raise httpx.ConnectError(str(exc), request=request) from exc
        transport = self._transport(destination.proxy, destination.host)
        original, original_extensions = request.url, request.extensions
        pinned, extensions = _pinned(original, destination)
        if pinned is original:
            return transport.handle_request(request)
        request.url = pinned
        request.extensions = {**original_extensions, **extensions}
        try:
            return transport.handle_request(request)
        finally:
            #: 换回原来的样子:跟随重定向时下一跳按它拼地址、照抄它的 extensions(不能把这一跳的 SNI 带过去),
            #: 调用方读 response.url 看到的也是原来的名字。
            request.url = original
            request.extensions = original_extensions

    def close(self) -> None:
        with self._lock:
            transports = list(self._transports.values())
            self._transports.clear()
        for transport in transports:
            transport.close()


class Exchange(NamedTuple):
    """一次(可能跟过几跳重定向的)请求:最后那一跳的响应,和它原来的地址(不是连过去的 IP)。"""

    response: httpx.Response
    url: str


def client(*, timeout: float, proxy: str | None) -> httpx.Client:
    """`send` 发一跳用的 httpx 客户端。这一跳已经在 `send` 里过了 `check`、改成了要连的 IP,所以这里用不带闸的传输
    (再过一遍的话,按名字放行的那一项会对不上改过的 IP)。**不认环境变量**:代理走不走已经按同一份环境判过了。

    认得「这件活被取消了」(core/abort,取消时连接当场关掉);不重试 —— 用户的请求多半不是幂等的,和此前一样只发一次。
    单独成一个函数:测试在这里装 MockTransport。
    """
    return abort.AbortableClient(
        timeout=timeout, follow_redirects=False, transport=httpx.HTTPTransport(proxy=proxy, trust_env=False),
    )


#: 截下来的正文已经解过压缩、长度也变了:重新包成响应时这几个头不能照抄,否则读的人会再解一遍。
_BODY_FRAMING = frozenset({"content-encoding", "content-length", "transfer-encoding"})


def _send_once(
    destination: Destination,
    method: str,
    headers: dict[str, str],
    content: bytes | None,
    timeout: float,
    max_bytes: int | None = None,
) -> httpx.Response:
    sent_headers = dict(headers)
    url, extensions = _pinned(destination.url, destination)
    if url is not destination.url and not any(key.lower() == "host" for key in sent_headers):
        #: netloc 是 IDNA 编码过的名字(加上非默认端口),正是 Host 头该有的样子。
        sent_headers["Host"] = destination.url.netloc.decode("ascii")
    with client(timeout=timeout, proxy=destination.proxy) as one:
        if max_bytes is None:
            return one.request(method, url, headers=sent_headers, content=content, extensions=extensions)
        #: 有上限就边收边数:对面说的 Content-Length 可能是假的,也可能根本不说(分块传)。
        request = one.build_request(method, url, headers=sent_headers, content=content, extensions=extensions)
        response = one.send(request, stream=True)
        try:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ResponseTooLarge("outboundErr_tooLarge", host=destination.host, limit_mb=max(1, max_bytes // (1024 * 1024)))
        finally:
            response.close()
        kept = [(key, value) for key, value in response.headers.multi_items() if key.lower() not in _BODY_FRAMING]
        return httpx.Response(response.status_code, headers=kept, content=bytes(body), request=request)


def _same_origin(a: httpx.URL, b: httpx.URL) -> bool:
    return (a.scheme, a.host, a.port) == (b.scheme, b.host, b.port)


def send(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float,
    follow_redirects: bool = False,
    max_redirects: int = MAX_REDIRECTS,
    max_bytes: int | None = None,
) -> Exchange:
    """发一次经过守卫的请求。`follow_redirects` 时每一跳都重新 check、重新解析。

    `max_bytes`:正文最多收多少字节,超了抛 ResponseTooLarge(边收边数,不先整个读进内存)。不给就不限 ——
    读网页、调接口的那些地方回来的东西本来就小。

    跟随时的改写和浏览器一致:303,以及 301/302 上的非 GET/HEAD,改成不带请求体的 GET;跨站的那一跳不带
    Authorization / Cookie。
    """
    verb = (method or "GET").upper()
    current = str(url).strip()
    sent = dict(headers or {})
    body = content
    for _hop in range(max_redirects + 1):
        destination = check(current)
        response = _send_once(destination, verb, sent, body, timeout, max_bytes)
        location = response.headers.get("location") if response.is_redirect else None
        if not follow_redirects or not location:
            return Exchange(response, str(destination.url))
        target = urljoin(str(destination.url), location)
        if response.status_code == 303 or (response.status_code in (301, 302) and verb not in ("GET", "HEAD")):
            verb, body = "GET", None
            sent = {key: value for key, value in sent.items() if key.lower() not in ("content-type", "content-length")}
        if not _same_origin(destination.url, httpx.URL(target)):
            sent = {key: value for key, value in sent.items() if key.lower() not in ("authorization", "cookie")}
        current = target
    raise httpx.TooManyRedirects(f"more than {max_redirects} redirects", request=response.request)


__all__ = [
    "AllowEntry",
    "AllowlistError",
    "Destination",
    "Exchange",
    "FOLLOW_ENVIRONMENT",
    "GuardedTransport",
    "MAX_REDIRECTS",
    "Origin",
    "OutboundBlocked",
    "Route",
    "ResponseTooLarge",
    "blocked_reason",
    "check",
    "checks",
    "client",
    "current_allowlist",
    "lookup",
    "parse_allowlist",
    "parse_entry",
    "route_for",
    "send",
    "set_allowlist",
]
