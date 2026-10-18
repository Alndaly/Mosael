"""页面 → 媒体地址的窄接缝。

**它只回答一个问题**:用户粘的是一个页面地址,这个页面真正能下的媒体在哪、取它要带什么头?
答案是**有或没有** —— 认不出来就是 `None`,调用方退回 yt-dlp。**绝不返回近似**:一个「大概
是这个地址」的结果,用户点下载之后会拿到一份不认识的东西,而报错会出现在离真正原因很远的地方。

## 契约

```python
def resolve(url: str) -> ResolvedMedia | None
```

- `ResolvedMedia.url` 必须是 http(s) 的**媒体地址本身**(不是又一个页面);
- `headers` 是取它**必需**的请求头(Referer、User-Agent……),没有就空着;
- `None` = 不认识这个地址。不是「可能吧」「大概」,也不是「试试看」;
- 约束:resolver 自己抓页面**必须**走 `core.http_retry.RetryingClient`(或
  `core.outbound_proxy.ticket(Origin.GIVEN)`)。裸 `httpx` 会绕过出站检查 —— 地址是别人给的,
  每一跳都得按同一道闸判。抓回来的内容只用于找媒体地址,不落素材库。

resolver 抛的错会原样上抛(守卫拦下时是 `OutboundBlocked`);调用方把它当这一条的失败原因说清,
不会悄悄退回 yt-dlp 假装什么都没发生。

## 现在

注册表是**空的**:还没有任何一个站点需要这条接缝。先有的接线、契约和测试是为了让「加一家站点」
变成一件小事 —— 一个新文件 + 几条测试,而不是回来改 `from_url` 的两处调用。
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

#: 一个站点 resolver 认出来的东西。
@dataclass(frozen=True)
class ResolvedMedia:
    """页面里那一条媒体:地址,和取它必需的头。"""

    url: str
    #: 取这个地址必须带上的请求头(Referer、User-Agent……)。空 = 不需要。
    headers: Mapping[str, str] = field(default_factory=dict)
    #: 界面上给这一条的名字。站点没给就空着,由界面画占位。
    title: str = ""


#: 一个 resolver:页面地址 → 媒体。认不出返回 None。
Resolver = Callable[[str], "ResolvedMedia | None"]

_resolvers: list[Resolver] = []
_lock = threading.Lock()


def register(resolver: Resolver) -> Resolver:
    """登记一个 resolver(以后每个站点一个文件,在它的模块里调这一句)。返回它自己,方便装饰。"""
    with _lock:
        if resolver not in _resolvers:
            _resolvers.append(resolver)
    return resolver


def unregister(resolver: Resolver) -> None:
    """摘掉一个 resolver。测试用;站点代码不需要。"""
    with _lock:
        if resolver in _resolvers:
            _resolvers.remove(resolver)


def registered() -> tuple[Resolver, ...]:
    """现在登记了哪些(顺序就是被问的顺序)。"""
    with _lock:
        return tuple(_resolvers)


def resolve(url: str) -> ResolvedMedia | None:
    """问所有 resolver,第一个认出来的说了算。**认不出来就是 None**。"""
    candidate = str(url or "").strip()
    if not candidate:
        return None
    for resolver in registered():
        found = resolver(candidate)
        if found is None:
            continue
        _validate(found)
        return found
    return None


def _validate(found: ResolvedMedia) -> None:
    """resolver 交回来的必须是一个 http(s) 媒体地址。写错了当场炸,不要让它走到下载那一步。"""
    try:
        parts = urlsplit(found.url)
    except ValueError as exc:  # pragma: no cover — urlsplit 对 str 几乎不抛
        raise ValueError(f"resolver returned an unparsable media url: {found.url!r}") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"resolver returned a non-http(s) media url: {found.url!r}")
