"""插件清单:解析与校验在 `mosael_formats.plugin_manifest`,这里接过来,再加上桌面运行时的那一点。

**清单只有一套规则。** 用户点「从文件安装」时过的清单校验,和社区服务收到一个插件包时过的,是同一个
`parse`(ADR 0026:社区上能上架的,装得上;装不上的,上不了架)。所以解析器住在两边共用的格式包里,
这个模块不再有自己的一份,也不转出那一份:调用方直接 `from mosael_formats.plugin_manifest import parse`。

留在这里的只有桌面端自己的事:包记录上的清单怎么读(`manifest_of`,它认得数据库模型),
以及宿主告诉插件进程「这次说哪种语言」的那个环境变量名。
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

from mosael_formats.plugin_manifest import (
    Manifest,
    parse,
)

if TYPE_CHECKING:  # 仅为类型;运行时不 import models,保持这个模块是叶子
    from app.db.models import PluginPackage

#: 这次调用要说哪种语言,插件自己也会拿到它(见 runtime/mcp_bridge 里的 MOSAEL_LOCALE)。
LOCALE_ENV = "MOSAEL_LOCALE"

#: 清单里插件目录的绝对路径。下划线开头 = 运行时注入,不是作者写的。
PATH_KEY = "_path"


def manifest_of(package: "PluginPackage") -> Manifest:
    """包记录 → 解析好的清单。**别处一律走这里**,不要直接 `.get()` 那个字典。"""
    raw = dict(package.manifest or {})
    return parse(raw, str(raw.get(PATH_KEY) or ""))


__all__ = [
    "LOCALE_ENV",
    "PATH_KEY",
    "manifest_of",
]


_TEMPLATE_KEY = re.compile(r"\{([A-Za-z0-9_]+)(?::label)?\}")


def summary_field(manifest: Manifest) -> str:
    """一个连接的**关键地址**是哪一项配置:名字模板里引用的第一个配置项(ComfyUI 的 `{server_url}`、TikHub 的 `{platform:label}`);
    没写模板就是第一个必填的文本配置项;都没有就是空串。插件页收起的连接那一行摆它,探「这台服务通不通」也问它。"""
    config = {field.key: field for field in manifest.config}
    for key in _TEMPLATE_KEY.findall(manifest.name_template or ""):
        if key in config:
            return key
    return next((field.key for field in manifest.config if field.required and field.type == "string"), "")
