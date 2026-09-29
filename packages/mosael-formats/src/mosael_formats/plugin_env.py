"""插件子进程环境里**宿主占着的名字** —— 清单里的配置 / 凭据键不能用它们。

进程插件和 MCP 的 stdio 插件起的都是插件的子进程,宿主给一份最小环境(见 backend 的
domain/plugins/child_env.base_env)。插件自己声明的配置 / 凭据也注入这份环境(键大写化),
**同名就会盖掉宿主给的**:一个叫 `path` 的配置项会把 PATH 换成用户填的一个文件路径,插件连解释器
都找不到。所以这些名字在清单校验时就挡住 —— 这是清单格式的一条规则,放在这里,装包和上架过的是同一条。

宿主替每个连接定的出站代理(backend 的 domain/plugins/egress)也在这份环境里。它此前靠「注入时排在插件
配置之后」保住,而那等于一个叫 `https_proxy` 的配置项在界面上照样有个框、用户填了却静默不生效 —— 所以
这几个名字同样在校验时挡。名字只在这里写一份:宿主注入的代理变量必须落在 `EGRESS_KEYS` 里(backend 的
test_plugin_egress 钉住),多注入一个而这里没记,插件就又能声明一个同名的去跟宿主抢。
"""

from __future__ import annotations

#: 所有平台都给的三个。
BASE_KEYS = ("PATH", "HOME", "LANG")

#: Windows 上**没有它们子进程就起不来**的那几个。Python 初始化要 SYSTEMROOT(否则连随机数都拿
#: 不到),Node 要它做 DNS,npm 要 APPDATA / LOCALAPPDATA 放缓存,TEMP 是一切临时文件的去处。
WINDOWS_ESSENTIALS = (
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
)

#: 宿主替这个连接定的出站代理:代理地址与绕过列表。大小写两份都注入;`is_reserved` 先大写再比,这里只记大写。
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")

#: 给了代理时一并注入:Node(24.5 起)只有看到它才让内置的 fetch 认 HTTP(S)_PROXY。`npx` 起的 MCP 服务
#: 多半是 Node,不给它,注入的代理对它们等于没有;老版本 Node 不认识这个变量,多给一个无害。
NODE_USE_ENV_PROXY = "NODE_USE_ENV_PROXY"

#: 出站代理那一组宿主会写的全部名字。
EGRESS_KEYS = (*PROXY_KEYS, NODE_USE_ENV_PROXY)

#: 装包从哪个镜像拉(清单里的 `package_sources`),宿主替这个连接定、按各生态自己认的变量名注入:
#: pip 认 PIP_INDEX_URL,uv 认 UV_DEFAULT_INDEX,npm 认 npm_config_registry(大小写都认,这里只记大写)。
#: 插件不必自己带一个「镜像」配置项 —— 那样每个插件各存一份镜像地址,和管理页的下载源互不知道。
PACKAGE_SOURCE_ENV = {
    "pypi": ("PIP_INDEX_URL", "UV_DEFAULT_INDEX"),
    "npm": ("NPM_CONFIG_REGISTRY",),
}
PACKAGE_SOURCE_KEYS = tuple(key for keys in PACKAGE_SOURCE_ENV.values() for key in keys)

#: 宿主和插件之间的约定变量(产出目录、持久目录、取消文件、语言……)都用这个前缀。
HOST_PREFIX = "MOSAEL_"


def is_reserved(key: str) -> bool:
    """这个配置 / 凭据键大写之后会不会盖掉宿主给的变量。**按所有平台算**:清单是跨平台的。"""
    upper = key.upper()
    return (
        upper in BASE_KEYS
        or upper in WINDOWS_ESSENTIALS
        or upper in EGRESS_KEYS
        or upper in PACKAGE_SOURCE_KEYS
        or upper.startswith(HOST_PREFIX)
    )


__all__ = [
    "BASE_KEYS", "EGRESS_KEYS", "HOST_PREFIX", "NODE_USE_ENV_PROXY", "PACKAGE_SOURCE_ENV", "PACKAGE_SOURCE_KEYS",
    "PROXY_KEYS", "WINDOWS_ESSENTIALS", "is_reserved",
]
