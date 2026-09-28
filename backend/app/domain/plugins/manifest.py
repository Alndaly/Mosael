"""插件清单:解析与校验在 `mosael_formats.plugin_manifest`,这里接过来,再加上桌面运行时的那一点。

**清单只有一套规则。** 用户点「从文件安装」时过的清单校验,和社区服务收到一个插件包时过的,是同一个
`parse`(ADR 0026:社区上能上架的,装得上;装不上的,上不了架)。所以解析器住在两边共用的格式包里,
这个模块不再有自己的一份 —— 别处照旧 `from app.domain.plugins.manifest import parse`,拿到的就是那一份。

留在这里的只有桌面端自己的事:包记录上的清单怎么读(`manifest_of`,它认得数据库模型),
以及宿主告诉插件进程「这次说哪种语言」的那个环境变量名。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mosael_formats.plugin_manifest import (
    AUDIO_DENOISE,
    AUDIO_SEPARATION,
    CODE_FIELD_TYPES,
    DOCUMENT_PARSE,
    FIELD_TYPES,
    GENERATION,
    HOST_ONLY_CAPABILITIES,
    KEY_RE,
    PLUGIN_ID_RE,
    TOOL_NAME_RE,
    TOOLS,
    Author,
    Field,
    Manifest,
    ManifestError,
    OAuthSpec,
    Runtime,
    ToolOverride,
    expand,
    localized_tool,
    oauth_spec,
    parse,
    render_name,
    runtime_of,
    text_of,
    tool_label,
    web_url,
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
    "Author",
    "CODE_FIELD_TYPES",
    "AUDIO_DENOISE",
    "AUDIO_SEPARATION",
    "DOCUMENT_PARSE",
    "FIELD_TYPES",
    "Field",
    "GENERATION",
    "HOST_ONLY_CAPABILITIES",
    "KEY_RE",
    "LOCALE_ENV",
    "Manifest",
    "ManifestError",
    "OAuthSpec",
    "PATH_KEY",
    "PLUGIN_ID_RE",
    "Runtime",
    "TOOLS",
    "TOOL_NAME_RE",
    "ToolOverride",
    "expand",
    "localized_tool",
    "manifest_of",
    "oauth_spec",
    "parse",
    "render_name",
    "runtime_of",
    "text_of",
    "tool_label",
    "web_url",
]
