"""出站请求的内网守卫:**用户给的地址**(工作流的 HTTP 请求节点、智能体的 http_request / fetch_url、
从链接导入素材)只许去公网,除非部署管理员把那个地址放进了允许名单。

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
- **走代理时**(进程的 HTTP(S)_PROXY,见 domain/network):连接由代理发起,我们连不了「那个 IP」,只能在发出前
  按本机的解析结果判一次;本机解析不了(只有代理那边能解析的内网环境)就交给代理 —— 它是部署者自己配的出口。

## 怎么放行

部署设置里的允许名单(管理 → 内网访问,存在 DeploymentConfig.outbound_allowlist,启动时和改完时推到这里,
与重试次数同一套做法):每一项是主机名、IP 或 CIDR 网段,主机名和 IP 可以带端口(`127.0.0.1:11434`、
`nas.local`、`10.0.0.0/8`)。**桌面版也默认拒**,包括本机回环 —— 本机回环上恰恰住着最要紧的那些服务
(本应用自己的后端与 sidecar、模型服务、Docker),而导入别人的模板在桌面版上一样常见。

住在 core:它只是 httpx 加 ipaddress,没有数据库;允许名单由 domain/outbound_allowlist 推进来。
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import urljoin

import httpx

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


class OutboundBlocked(LocalizedError, ValueError):
    """这个地址不许去。带文案 key(`outboundErr_*`),参数里说清是哪个地址、为什么、怎么放行。"""


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


def _proxy_for(url: httpx.URL) -> str | None:
    """这个地址会不会走代理 —— 和后端其余的 httpx 一样认进程的 HTTP(S)_PROXY / NO_PROXY(见 domain/network)。"""
    proxies = urllib.request.getproxies_environment()
    if not proxies:
        return None
    host = url.host
    if urllib.request.proxy_bypass_environment(host, proxies):
        return None
    return proxies.get(url.scheme) or proxies.get("all") or None


def check(url: str | httpx.URL, *, allowlist: Sequence[AllowEntry] | None = None) -> Destination:
    """这一跳能不能去;能去就交回要连的 IP。不能去抛 OutboundBlocked,解析不了抛 httpx.ConnectError。"""
    try:
        parsed = httpx.URL(str(url).strip())
    except (httpx.InvalidURL, TypeError, ValueError) as exc:
        raise OutboundBlocked("outboundErr_badUrl", url=str(url)[:200]) from exc
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise OutboundBlocked("outboundErr_badUrl", url=str(url)[:200])
    host = parsed.host
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    proxy = _proxy_for(parsed)
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
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
        if reason and not any(entry.admits(host, address, port) for entry in entries):
            raise OutboundBlocked(
                "outboundErr_private",
                host=host,
                address=str(address),
                reason=fragment(f"outboundReason_{reason}"),
                entry=_suggestion(host, port, address),
            )
    return Destination(url=parsed, host=host, port=port, address=str(addresses[0]), proxy=proxy)


class Exchange(NamedTuple):
    """一次(可能跟过几跳重定向的)请求:最后那一跳的响应,和它原来的地址(不是连过去的 IP)。"""

    response: httpx.Response
    url: str


def client(*, timeout: float, proxy: str | None) -> httpx.Client:
    """发一跳用的 httpx 客户端。**不认环境变量**:代理走不走已经在 check 里按同一份环境判过了。
    单独成一个函数:测试在这里装 MockTransport。"""
    return httpx.Client(timeout=timeout, proxy=proxy, trust_env=False, follow_redirects=False)


def _send_once(
    destination: Destination, method: str, headers: dict[str, str], content: bytes | None, timeout: float
) -> httpx.Response:
    url = destination.url
    extensions: dict[str, str] = {}
    sent_headers = dict(headers)
    if destination.address and not destination.proxy:
        #: 连查过的那个 IP;名字留在 Host 头和 SNI 里 —— 虚拟主机按它分站点,证书按它校验。
        #: netloc 是 IDNA 编码过的名字(加上非默认端口),正是 Host 头该有的样子。
        if not any(key.lower() == "host" for key in sent_headers):
            sent_headers["Host"] = url.netloc.decode("ascii")
        if url.scheme == "https" and destination.address != url.host:
            extensions["sni_hostname"] = url.raw_host.decode("ascii")
        url = url.copy_with(host=destination.address)
    with client(timeout=timeout, proxy=destination.proxy) as one:
        return one.request(method, url, headers=sent_headers, content=content, extensions=extensions)


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
) -> Exchange:
    """发一次经过守卫的请求。`follow_redirects` 时每一跳都重新 check、重新解析。

    跟随时的改写和浏览器一致:303,以及 301/302 上的非 GET/HEAD,改成不带请求体的 GET;跨站的那一跳不带
    Authorization / Cookie。
    """
    verb = (method or "GET").upper()
    current = str(url).strip()
    sent = dict(headers or {})
    body = content
    for _hop in range(max_redirects + 1):
        destination = check(current)
        response = _send_once(destination, verb, sent, body, timeout)
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
    "MAX_REDIRECTS",
    "OutboundBlocked",
    "blocked_reason",
    "check",
    "client",
    "current_allowlist",
    "lookup",
    "parse_allowlist",
    "parse_entry",
    "send",
    "set_allowlist",
]
