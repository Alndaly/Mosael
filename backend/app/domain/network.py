"""出站网络代理:一处配置,所有出口遵守。

**为什么必须是统一的一处**:触发它的场景是「OpenAI 判你所在地区不支持」——换令牌被拒的同时,
后续的对话请求同样会被拒。只给 OAuth 配代理没有意义;能用的最小单位就是「整个应用的出站」。

三个出口各有各的机制,但都从这里取值:
  - 后端 httpx —— `trust_env` 默认为真,认进程的 HTTP_PROXY / HTTPS_PROXY / NO_PROXY。
    所以这里改的是**本进程的环境变量**,而不是给十几处 httpx.Client 逐个传 proxy=。
  - sidecar(Node/undici)—— 默认**不认**环境变量,要显式装 EnvHttpProxyAgent;
    后端起进程时把这几个变量放进 env(见 adapters / login)。
  - Electron 内嵌浏览器 —— 走 session.setProxy。

**回环永远不走代理**,这条不是默认值而是硬规则:sidecar 的每一次工具调用都要回连
`127.0.0.1:<后端端口>`,一旦被送进代理,整个智能体就全废了 —— 而且表现是「工具全部超时」,
很难联想到是代理配错。所以用户填什么,回环都会被补进 NO_PROXY。
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.db.models import NetworkConfig

#: 无论用户怎么填都要绕过代理的目标。localhost 变体全列出来:NO_PROXY 是逐项精确/后缀匹配,
#: 不做等价推断,漏一个就是一类回连失败。
LOOPBACK_NO_PROXY = ("localhost", "127.0.0.1", "::1", "0.0.0.0")

#: 新装时预填的绕过列表:应用自带集成里的**国内**端点。
#:
#: 配代理的典型动机是「某家境外供应商按地区拒绝」,而这个开关一开就覆盖后端所有出站 ——
#: 飞书、火山、百炼、Kling 这些跟着走境外代理只会更慢甚至不通。所以给一份合理的默认。
#:
#: 是**默认值不是规则**:用户可以在设置里删掉任意一条(比如公司代理在国内、要求全量走代理)。
#: 与之相对,LOOPBACK 是强制的 —— 那条错了会让智能体的工具调用全废。
DEFAULT_BYPASS_HOSTS = (
    "open.feishu.cn",
    "accounts.feishu.cn",
    "accounts.larksuite.com",
    "openspeech.bytedance.com",
    "ark.cn-beijing.volces.com",
    "dashscope.aliyuncs.com",
    "api.moonshot.cn",
    "api.minimaxi.com",
    "api.klingai.com",
)

#: 进程环境里要同步的键。大小写两份都写:httpx 认小写优先,别的库(和 Node)习惯大写。
_PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def get_config(db: Session) -> NetworkConfig:
    row = db.get(NetworkConfig, "default")
    if row is None:
        # 默认绕过列表在这里给,不放在列默认值上:那会让 db.models 反向 import 领域层,
        # 形成 models ⇄ domain.network 的循环(分层测试会拦住)。
        row = NetworkConfig(id="default", no_proxy=",".join(DEFAULT_BYPASS_HOSTS))
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def effective_no_proxy(no_proxy: str) -> str:
    """用户填的绕过列表 + 回环。去重保序,用户写过的排在前面。"""
    items: list[str] = []
    for raw in (no_proxy or "").replace("，", ",").replace("\n", ",").split(","):
        item = raw.strip()
        if item and item not in items:
            items.append(item)
    for item in LOOPBACK_NO_PROXY:
        if item not in items:
            items.append(item)
    return ",".join(items)


def proxy_env(proxy_url: str, no_proxy: str) -> dict[str, str]:
    """要注入进程/子进程的环境变量。proxy_url 为空 → 空字典(直连)。"""
    url = (proxy_url or "").strip()
    if not url:
        return {}
    bypass = effective_no_proxy(no_proxy)
    values = {"HTTP_PROXY": url, "HTTPS_PROXY": url, "ALL_PROXY": url, "NO_PROXY": bypass}
    # 小写同名一并给出:两种写法在生态里都有人读,只设一种会出现"有的库走了代理有的没走"。
    return {**values, **{key.lower(): value for key, value in values.items()}}


def apply_to_process(proxy_url: str, no_proxy: str) -> None:
    """把设置写进**本进程**的环境变量,后端自己的 httpx 调用随即生效。

    改设置后不需要重启:httpx 在构造 Client 时读环境,而这里的调用几乎都是即用即建。
    已经建好的长生命周期 client(如果将来有)不会热更新——真出现时应当显式传 proxy=。
    """
    env = proxy_env(proxy_url, no_proxy)
    if env:
        os.environ.update(env)
        return
    for key in _PROXY_ENV_KEYS:
        os.environ.pop(key, None)
        os.environ.pop(key.lower(), None)


def apply_from_db(db: Session) -> None:
    row = get_config(db)
    apply_to_process(row.proxy_url, row.no_proxy)


def subprocess_env(db: Session, base: dict[str, str]) -> dict[str, str]:
    """给子进程(sidecar)的环境。没配代理时**主动删掉**继承来的那几个变量 ——
    否则用户在应用里关掉了代理,子进程却还在用启动 shell 里的老变量,行为对不上界面。"""
    row = get_config(db)
    env = dict(base)
    for key in _PROXY_ENV_KEYS:
        env.pop(key, None)
        env.pop(key.lower(), None)
    env.update(proxy_env(row.proxy_url, row.no_proxy))
    return env


def subprocess_env_for_child(base: dict[str, str]) -> dict[str, str]:
    """给子进程算环境,**自开一个会话**。

    调用方(ai/sidecar)持有的那个 db 可能正处在一次回合的事务里,而这里只是读一行配置,
    不该被卷进去。装配在 app/main.py:`adapters.use_proxy_source(subprocess_env_for_child)`
    —— 基础设施声明它要什么,领域把答案喂进去,而不是反过来让它认识这张表。
    """
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        return subprocess_env(db, base)
