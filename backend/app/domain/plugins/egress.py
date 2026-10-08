"""一个插件连接往外连走哪条路 —— 宿主替它决定,**只在这里决定**。

Mosael 有一处全局的出站代理(见 domain/network)。插件的子进程(进程插件、stdio 的 MCP)拿到的是宿主给的
最小环境(child_env.base_env),不继承后端进程的环境变量 —— 于是全局代理此前根本到不了插件:MinerU
为此在自己的清单里另发明了一套「网络 / 代理地址」,跟的是操作系统的系统代理,和 Mosael 的设置互不知道。

现在它是**连接级**的宿主设置,和账号池里每个账号自己的代理同一个形状:默认跟着全局走,单个连接可以覆盖
(有的插件要的代理和全局的不一样 —— MinerU 只在中国大陆提供服务,人在境外得走一个进大陆的代理)。三种:

- `follow`(默认):和 Mosael 自己的出站一样。全局配了代理就注入那一份(连同绕过列表);没配就**什么都
  不给**,插件用的库照它自己的默认办 —— Python 的 urllib / httpx 在 macOS、Windows 上会退到系统代理,
  这和后端自己的 httpx 在同样情况下的行为是同一个;
- `direct`:这个连接直连。光「不给代理变量」做不到这一点(库会退到系统代理),所以明说 `NO_PROXY=*`;
- `proxy`:这个连接走它自己的代理。绕过列表只有回环:全局那份是替全局代理调的(国内端点别走境外代理),
  而覆盖的意思是「这个连接整个走这一条」。

**为什么不留给每个插件在清单里声明**:走哪个代理是这台机器、这个人的网络状况,不是插件的业务配置。每个
插件各发明一个「网络」字段,就是每个插件各有一套不知道全局设置的规矩 —— MinerU 那一套就是这么来的。

决定出来的结果(`Egress`)有两个出口,说的是同一件事:
- `child_env()`:注入插件子进程的环境变量,进程插件和 stdio MCP 同一份;
- `httpx_options(url)`:后端**替这个连接**发的请求(远程 HTTP 的 MCP、按插件给的地址下载产出)用的 httpx 参数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from urllib.request import proxy_bypass_environment

from mosael_formats.plugin_env import NODE_USE_ENV_PROXY
from sqlalchemy.orm import Session

from app.core import outbound_guard
from app.db.models import PluginInstance
from app.domain import network
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import Manifest

FOLLOW = "follow"
DIRECT = "direct"
PROXY = "proxy"
MODES = (FOLLOW, DIRECT, PROXY)

#: 连接自己的代理认哪几种地址。和全局设置能填的一样(http 与 socks);插件用的库认不认 socks 是它自己的事。
PROXY_SCHEMES = ("http", "https", "socks5", "socks5h")

#: 「谁都绕过」。curl、urllib、httpx、requests、Node 都认这个写法 —— 这是「直连」唯一能跨库说清的方式。
BYPASS_ALL = "*"


@dataclass(frozen=True)
class Egress:
    """一个连接这一次往外连的路。

    `proxy_url` 空 = 不走代理。`no_proxy` 在走代理时是绕过列表(已含回环);不走代理时,`*` 表示「明说直连」,
    空串表示「宿主什么都不说」—— 两者对插件是不同的环境,见模块说明里 follow 与 direct 的区别。
    """

    proxy_url: str = ""
    no_proxy: str = ""
    #: 装包从哪个镜像拉(见 domain/plugins/package_sources):注入进程的那几个变量。和代理同属「宿主替这个连接
    #: 定的对外环境」,一起算、一起注入;远程请求用不上它。
    package_env: tuple[tuple[str, str], ...] = ()

    def child_env(self) -> dict[str, str]:
        """注入插件子进程的那几个变量。大小写两份都给(见 network.proxy_env)。

        名字全在 `mosael_formats.plugin_env.EGRESS_KEYS` 里:清单校验按那一份挡插件声明同名的配置 / 凭据,
        所以插件的配置本来就进不了这几格,不靠注入顺序。
        """
        mirrors = dict(self.package_env)
        if self.proxy_url:
            return {**network.proxy_env(self.proxy_url, self.no_proxy), NODE_USE_ENV_PROXY: "1", **mirrors}
        if self.no_proxy == BYPASS_ALL:
            return {"NO_PROXY": BYPASS_ALL, "no_proxy": BYPASS_ALL, **mirrors}
        return mirrors

    def bypasses(self, url: str) -> bool:
        """走代理时,`url` 的主机在绕过列表里(这一个直连)。不走代理时总是假 —— 那时谈不上「绕过」。"""
        if not self.proxy_url:
            return False
        return bool(proxy_bypass_environment(urlsplit(url).hostname or "", {"no": self.no_proxy}))

    @property
    def shown_proxy(self) -> str:
        """给人看的代理地址:地址里的用户名、密码换成 `***`(安装计划这类地方要写明走哪个代理,但不该把密码摆出来)。"""
        parts = urlsplit(self.proxy_url)
        if not parts.username and not parts.password:
            return self.proxy_url
        host = parts.hostname or ""
        host = f"[{host}]" if ":" in host else host
        netloc = f"***@{host}" + (f":{parts.port}" if parts.port else "")
        return parts._replace(netloc=netloc).geturl()

    def httpx_options(self, url: str) -> dict[str, Any]:
        """后端替这个连接请求 `url` 时交给 httpx 的参数 —— 和 `child_env()` 是同一个决定。

        `trust_env=False` 是必须的:后端进程自己的环境变量里放着全局代理(network.apply_to_process),
        不关掉它,直连和「走这个连接自己的代理」都会被全局那一份盖掉。什么都不说(follow 且全局没配)时
        返回空字典,httpx 照后端自己的出站办。
        """
        if self.proxy_url:
            if self.bypasses(url):
                return {"trust_env": False}
            return {"trust_env": False, "proxy": self.proxy_url}
        if self.no_proxy == BYPASS_ALL:
            return {"trust_env": False}
        return {}

    def route(self, url: str) -> outbound_guard.Route:
        """同一个决定,换成出站检查认的说法(给不经 httpx 的那几处,经守卫代理出去时用,见 core/outbound_proxy)。"""
        options = self.httpx_options(url)
        if "proxy" in options:
            return options["proxy"]
        if options.get("trust_env") is False:
            return None
        return outbound_guard.FOLLOW_ENVIRONMENT


#: 没人替这个连接做过决定(直接调传输层的地方:测试、脚本):什么都不注入,httpx 照缺省。
#: 正式的调用路径(plugins.tools / plugins.generation)总是先 `resolve`。
UNDECIDED = Egress()


def resolve(db: Session, instance: PluginInstance, manifest: Manifest) -> Egress:
    """**唯一的决策**:连接自己的覆盖 > Mosael 的全局设置 —— 出站代理和包镜像都是。`manifest` 说它要从哪几个包
    生态装东西(清单的 `package_sources`),由调用方给:它们手里本来就有这个连接的清单。"""
    from app.domain.plugins import package_sources

    mirrors = tuple(sorted(package_sources.child_env(manifest.package_sources, instance.package_sources).items()))
    if instance.network_mode == DIRECT:
        return Egress(no_proxy=BYPASS_ALL, package_env=mirrors)
    if instance.network_mode == PROXY:
        return Egress(proxy_url=instance.proxy_url, no_proxy=network.effective_no_proxy(""), package_env=mirrors)
    config = network.get_config(db)
    url = (config.proxy_url or "").strip()
    return Egress(proxy_url=url, no_proxy=network.effective_no_proxy(config.no_proxy) if url else "", package_env=mirrors)


def normalize(mode: str, proxy_url: str) -> tuple[str, str]:
    """保存前的校验:认得的模式、`proxy` 模式下一个像样的代理地址。别的模式下地址清空。

    地址要在保存时就查:存进去一个 `127.0.0.1:7890`(缺 scheme),插件那边的库会各报各的错 ——
    urllib 当它是主机名去解析,报的是「连不上」,没人会想到是这一格少写了 `http://`。
    """
    mode = (mode or "").strip()
    if mode not in MODES:
        raise PluginDomainError("pluginErr_networkMode", mode=mode)
    if mode != PROXY:
        return mode, ""
    url = (proxy_url or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in PROXY_SCHEMES or not parts.hostname:
        raise PluginDomainError("pluginErr_proxyUrl", url=url)
    return mode, url


__all__ = ["BYPASS_ALL", "DIRECT", "Egress", "FOLLOW", "MODES", "PROXY", "UNDECIDED", "normalize", "resolve"]
