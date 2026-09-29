"""一个插件连接装包从哪个镜像拉 —— 宿主替它决定,**只在这里决定**。和出站代理(egress)同一个形状。

插件在清单里声明它要从哪几个包生态装东西(`package_sources: ["pypi"]`、`["npm"]`),宿主按这个连接的决定把
镜像地址注入它的进程,变量名是各生态自己认的(mosael_formats.plugin_env.PACKAGE_SOURCE_ENV:pip 的
PIP_INDEX_URL、uv 的 UV_DEFAULT_INDEX、npm 的 npm_config_registry)。插件不必自己带一个「镜像」配置项。

决定只有两层:

- 连接自己的覆盖(`PluginInstance.package_sources[生态]`):预设 key(清华、npmmirror……)或自定义地址;
- 没覆盖就**跟随**「管理 → 下载源」(`ai.runtime.config` 的 pip_index / npm_registry)—— 装本机引擎用的也是那一份。

**为什么不留给插件在清单里各写一个下拉**:镜像地址是这台机器、这个人的网络状况,不是插件的业务配置。此前
Manim 和 Remotion 各带一个自由文本框,每个插件各存一份地址,和管理页的下载源互不知道,选了清华 pip 还得在
每个插件里再填一遍(用户截图:「镜像应该是下拉选择而不是输入」)。
"""

from __future__ import annotations

from typing import Any

from mosael_formats.plugin_env import PACKAGE_SOURCE_ENV

from app.ai.runtime import config as runtime_config
from app.core.i18n import tr
from app.domain.plugins.errors import PluginDomainError

#: 各生态的预设(key → 地址;地址空 = 官方源)和它们在界面上叫什么。
PRESETS: dict[str, dict[str, str]] = {"pypi": runtime_config.PIP_INDEXES, "npm": runtime_config.NPM_REGISTRIES}
_LABELS = {
    "pypi": {"pypi": "pkgSource_pypiOfficial", "tsinghua": "pkgSource_tsinghua", "aliyun": "pkgSource_aliyun",
             "tencent": "pkgSource_tencent"},
    "npm": {"npmjs": "pkgSource_npmOfficial", "npmmirror": "pkgSource_npmmirror", "tencent": "pkgSource_tencent",
            "huawei": "pkgSource_huawei"},
}
_SOURCE_LABELS = {"pypi": "pkgSource_pypiTitle", "npm": "pkgSource_npmTitle"}


def host_choice(source: str) -> str:
    """「管理 → 下载源」这一生态定的是什么(预设 key 或自定义地址;空 = 官方)。"""
    current = runtime_config.get()
    return (current.pip_index if source == "pypi" else current.npm_registry) or ""


def url_of(source: str, choice: str) -> str:
    """预设 key 或自定义地址 → 真正的地址;空串 = 官方源(什么都不注入)。自定义的只收 http(s):它会进子进程环境。"""
    choice = (choice or "").strip()
    if choice in PRESETS[source]:
        return PRESETS[source][choice]
    return choice if choice.startswith(("http://", "https://")) else ""


def effective_choice(source: str, overrides: dict[str, Any] | None) -> str:
    """这个连接在这一生态上实际用的那一个:覆盖优先,没覆盖跟随宿主。"""
    own = str((overrides or {}).get(source) or "").strip()
    return own or host_choice(source)


def child_env(declared: list[str], overrides: dict[str, Any] | None) -> dict[str, str]:
    """注入插件进程的镜像变量。只给清单里声明了的生态;官方源什么都不注入(各工具的默认就是官方)。"""
    env: dict[str, str] = {}
    for source in declared:
        url = url_of(source, effective_choice(source, overrides))
        if url:
            env.update({key: url for key in PACKAGE_SOURCE_ENV[source]})
    return env


def normalize(source: str, choice: str) -> str:
    """保存前的校验:认得的生态;空(= 跟随)、预设 key 或 http(s) 地址。存进去一个 `registry.npmmirror.com`
    (缺 scheme)的话,npm 当它是相对路径,报的是一串看不出原因的 ENOTFOUND。"""
    if source not in PACKAGE_SOURCE_ENV:
        raise PluginDomainError("pluginErr_packageSourceUnknown", source=source)
    choice = (choice or "").strip()
    if not choice or choice in PRESETS[source] or choice.startswith(("http://", "https://")):
        return choice
    raise PluginDomainError("pluginErr_packageSourceUrl", url=choice)


def presets_out(source: str) -> list[dict[str, str]]:
    """界面下拉里的预设:key、名字、地址(官方那一项地址是空串)。"""
    return [{"value": key, "label": tr(_LABELS[source].get(key, key)), "url": url} for key, url in PRESETS[source].items()]


def choice_label(source: str, choice: str) -> str:
    """一个选择在界面上叫什么:预设叫它的名字,自定义的就是地址本身,空 = 官方。"""
    choice = (choice or "").strip()
    key = choice or next(key for key, url in PRESETS[source].items() if not url)
    return tr(_LABELS[source][key]) if key in _LABELS[source] else choice


def describe(declared: list[str], overrides: dict[str, Any] | None) -> list[dict[str, Any]]:
    """插件页每个声明了的生态一行:它叫什么、连接自己的覆盖(空 = 跟随)、跟随时是哪一个、有哪些预设。"""
    return [
        {
            "source": source,
            "label": tr(_SOURCE_LABELS[source]),
            "value": str((overrides or {}).get(source) or ""),
            "host_label": choice_label(source, host_choice(source)),
            "presets": presets_out(source),
        }
        for source in declared
    ]


__all__ = ["PRESETS", "child_env", "choice_label", "describe", "effective_choice", "host_choice", "normalize",
           "presets_out", "url_of"]
