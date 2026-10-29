"""这个连接背后的服务**现在通不通**:按连接的关键地址发一次短请求(ComfyUI 的 `server_url`)。

只回答「有没有人在那个地址上应答」:回了任何 HTTP 响应(401、404 也算 —— 有人在)就是通,连不上 / 超时才是不通。不解析回包、
不鉴权,所以既快又不需要钥匙。界面据此决定「在 ComfyUI 工作台里打开」能不能点:连不上就置灰、说是哪个地址连不上,
而不是给一颗点了只会打开一页旧画布的按钮。

宿主起停的本机服务(ADR 0041)停着时也是「不通」,但那颗按钮会先请宿主把它起起来 —— 判断在界面那一侧(它同时知道本机服务的状态)。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.http_retry import RetryingClient
from app.core.outbound_guard import Origin, OutboundBlocked
from app.db.models import PluginInstance
from app.domain.plugins.instances import manifest_for
from app.domain.plugins.manifest import summary_field

#: 探一次等多久。工作台按钮等它决定能不能点,不能让人干等。
PROBE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class Reachability:
    reachable: bool
    #: 探的是哪个地址(界面写进悬停说明);连接没写地址时为空串,也就谈不上通不通(`reachable` 为假)。
    address: str


def probe(db: Session, instance: PluginInstance) -> Reachability:
    key = summary_field(manifest_for(db, instance))
    address = str((instance.config or {}).get(key) or "").strip() if key else ""
    if not address.startswith(("http://", "https://")):
        return Reachability(reachable=False, address="")
    try:
        # 地址是部署 / 用户配给这个连接的:按「配置的」出处过出网检查(桌面版上不拦本机地址,见 core/outbound_guard)。
        with RetryingClient(timeout=PROBE_TIMEOUT_SECONDS, max_retries=0, origin=Origin.CONFIGURED) as client:
            client.get(address)
    except (httpx.HTTPError, OutboundBlocked):
        return Reachability(reachable=False, address=address)
    return Reachability(reachable=True, address=address)
