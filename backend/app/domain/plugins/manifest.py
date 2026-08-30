"""manifest 的**唯一**解析入口:文件里写的形状 → 代码里用的形状。

以前 manifest 的字段是被各处直接 `.get()` 出来的,于是同一个 `tools` 字段在三个地方有三种
语义(进程插件的完整声明 / MCP 插件的白名单 / MCP 插件的覆盖层),读的人得先知道 `kind`
才能理解它。这里把"文件长什么样"收成一个函数,别处只认下面这几个规整过的结构。

**这里只认当前形状**。老写法在扫描时就地改写成新写法(见 migrations.py),和 core/db.py 里
那串 `_migrate_*` 同一个思路:兼容负担只在升级那一刻付一次。读取路径里的
`if 老写法 elif 新写法` 是永久的税 —— 每加一个字段都要想"另一种形状下它在哪",而两条分支里
总有一条平时没人走、坏了也没人发现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

#: i18n 是纯叶子(只依赖标准库),运行时 import 它不会把这个模块拖出叶子位置。
from app.core.i18n import DEFAULT_LOCALE, get_current_locale

if TYPE_CHECKING:  # 仅为类型;运行时不 import models,保持这个模块是叶子
    from app.db.models import PluginPackage

#: 配置项 / 凭据项的键。同时是 `${...}` 占位符的名字,也是进程插件的环境变量名(大写化)。
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

FIELD_TYPES = ("string", "enum", "number", "boolean")


def text_of(value: Any, locale: str | None = None) -> str:
    """清单里一段**给人看的文字**。既可以是普通字符串,也可以是按语言分的对象:

        "label": "起始目录"
        "label": { "zh": "起始目录", "en": "Start directory" }

    **翻译贴着它翻译的那个东西写**,不放在清单顶上的一张 `{"config.X.label": …}` 表里 ——
    那种表的键要和别处对得上,而对不上时不会报错,只会让那一条永远显示原文。这个项目在
    「手抄一张表」上栽过好几次。

    退路是**给原文**,不是给空:插件只写了中文时,英文界面上看到中文,总好过看到一片空白。
    """
    if isinstance(value, dict):
        want = locale or get_current_locale()
        for key in (want, DEFAULT_LOCALE):
            picked = value.get(key)
            if isinstance(picked, str) and picked.strip():
                return picked
        #: 连缺省语言都没有:退到作者写的第一条,而不是空串。
        for picked in value.values():
            if isinstance(picked, str) and picked.strip():
                return picked
        return ""
    return str(value or "")


@dataclass(frozen=True)
class Field:
    """一个配置项或凭据项。凭据只是「secret=True 的配置」—— 差别在控件和回显,不在语义。"""

    key: str
    label: str
    type: str = "string"
    help: str = ""
    required: bool = True
    secret: bool = False
    options: list[dict[str, str]] = field(default_factory=list)
    default: str = ""

    def option_label(self, value: str) -> str:
        for option in self.options:
            if option["value"] == value:
                return option["label"]
        return value


@dataclass(frozen=True)
class Runtime:
    kind: str = "process"  # "process" | "mcp"
    entry: str = ""
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolOverride:
    label: str = ""
    description: str = ""
    read_only: bool = False
    node: dict[str, Any] | None = None


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    path: str
    runtime: Runtime
    permissions: list[str] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    config: list[Field] = field(default_factory=list)
    credentials: list[Field] = field(default_factory=list)
    #: 允许建多个实例(同一个包接多个端点 / 多套凭据)。
    multiple: bool = False
    #: 实例显示名模板,`{key}` 取配置值,`{key:label}` 取枚举的显示文案。
    name_template: str = ""
    #: "selected"(默认,逐个勾选)| "all"(工具本来就少的包)。
    expose: str = "selected"
    recommended: list[str] = field(default_factory=list)
    overrides: dict[str, ToolOverride] = field(default_factory=dict)
    #: 进程类插件在 manifest 里声明的工具(MCP 插件此项为空,清单从服务拉)。
    declared_tools: list[dict[str, Any]] = field(default_factory=list)
    #: 插件**自己的**文档/主页。界面上给一个「文档」链接 —— 一个插件带来几十个工具、一串权限
    #: 和一套要去某个后台申请的凭据,而这些怎么用只有作者说得清;我们能做的是把人送到那儿。
    homepage: str = ""

    @property
    def is_mcp(self) -> bool:
        return self.runtime.kind == "mcp"

    def field_for(self, key: str) -> Field | None:
        for item in (*self.config, *self.credentials):
            if item.key == key:
                return item
        return None


class ManifestError(ValueError):
    pass


def _humanized(entry: dict[str, Any], *keys: str) -> dict[str, Any]:
    """把一个原样透传的字典里那几个给人看的键就地定下语言 —— 其余原封不动。

    技能、工具声明这些是整个字典往下传的(它们的形状由插件作者定,我们不该逐字段抄一遍),
    所以只挑名字确定的那几个键翻,别的一个字不动。
    """
    picked = {k: text_of(entry[k]) for k in keys if k in entry}
    return {**entry, **picked} if picked else entry


def _fields(raw: Any, *, secret: bool) -> list[Field]:
    if not isinstance(raw, list):
        return []
    out: list[Field] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        # 键名不合法的直接丢:它注入不进环境、也当不了占位符名,留着只是一个填了没用的框。
        if not KEY_RE.match(key):
            continue
        raw_options = entry.get("options")
        options: list[dict[str, str]] = []
        if isinstance(raw_options, list):
            for option in raw_options:
                if isinstance(option, dict) and option.get("value") is not None:
                    options.append({"value": str(option["value"]), "label": text_of(option.get("label")) or str(option["value"])})
                elif isinstance(option, str):
                    options.append({"value": option, "label": option})
        declared_type = str(entry.get("type") or ("string" if not options else "enum"))
        out.append(
            Field(
                key=key,
                label=text_of(entry.get("label")) or key,
                type=declared_type if declared_type in FIELD_TYPES else "string",
                help=text_of(entry.get("help")),
                required=entry.get("required") is not False,
                # 凭据默认按密文对待,漏标不该导致明文回显;配置默认明文。
                secret=bool(entry.get("secret", secret)),
                options=options,
                default=str(entry.get("default") or ""),
            )
        )
    return out


def runtime_of(raw: dict[str, Any]) -> Runtime:
    """原始清单 → 怎么跑。**执行器也走这里** —— 它只要跑法,不该顺带要求 id、version 齐全。"""
    block = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    kind = str(block.get("kind") or "process").strip().lower()
    return Runtime(
        kind="mcp" if kind == "mcp" else "process",
        entry=str(block.get("entry") or "").strip(),
        transport=str(block.get("transport") or "stdio").strip().lower(),
        command=str(block.get("command") or "").strip(),
        args=[str(a) for a in (block.get("args") or []) if str(a).strip()],
        url=str(block.get("url") or "").strip(),
        headers={str(k): str(v) for k, v in (block.get("headers") or {}).items()},
    )


def _tools_policy(raw: dict[str, Any]) -> tuple[str, list[str], dict[str, ToolOverride], list[dict[str, Any]]]:
    """→ (expose, recommended, overrides, 进程插件声明的工具)。

    `tools` 是个策略对象:`declare` 是进程插件的工具声明,`recommended` 是首次启用默认勾上
    的那些,`overrides` 按名字覆盖(目前只认 read_only 和 node)。三个名字各说各的 ——
    此前它是个数组,同时承担这三种语义,读的人得先知道 kind 才能理解那个字段。
    """
    tools = raw.get("tools")
    if not isinstance(tools, dict):
        return "all", [], {}, []
    expose = str(tools.get("expose") or "selected").strip().lower()
    overrides: dict[str, ToolOverride] = {}
    for name, spec in (tools.get("overrides") or {}).items():
        if not isinstance(spec, dict):
            continue
        overrides[str(name)] = ToolOverride(
            label=text_of(spec.get("label")),
            description=text_of(spec.get("description")),
            read_only=spec.get("read_only") is True,
            node=spec.get("node") if isinstance(spec.get("node"), dict) else None,
        )
    declared = [
        _humanized(t, "label", "description")
        for t in (tools.get("declare") or [])
        if isinstance(t, dict) and isinstance(t.get("name"), str)
    ]
    recommended = [str(n) for n in (tools.get("recommended") or [])]
    return ("all" if expose == "all" else "selected"), recommended, overrides, declared


def web_url(raw: Any) -> str:
    """清单里给的一条链接,**只认 http(s)**。

    不认的一律当没写:界面上那个「文档」按钮点下去就是打开它,而 `javascript:` / `file:`
    是一条从第三方清单直通用户浏览器的路。这里不是在防御格式,是在防御来源。
    """
    url = str(raw or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def parse(raw: dict[str, Any], path: str) -> Manifest:
    for key in ("id", "version"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ManifestError(f"插件清单 {path} 缺少必填字段: {key}")
    #: 名字是给人看的,可以按语言写;但空的仍然是缺字段。
    name = text_of(raw.get("name")).strip()
    if not name:
        raise ManifestError(f"插件清单 {path} 缺少必填字段: name")
    instance = raw.get("instance") if isinstance(raw.get("instance"), dict) else {}
    expose, recommended, overrides, declared = _tools_policy(raw)
    return Manifest(
        id=raw["id"].strip(),
        name=name,
        version=raw["version"].strip(),
        path=path,
        runtime=runtime_of(raw),
        permissions=[p for p in (raw.get("permissions") or []) if isinstance(p, str) and p.strip()],
        skills=[_humanized(s, "name", "description") for s in (raw.get("skills") or []) if isinstance(s, dict)],
        config=_fields(instance.get("config"), secret=False),
        credentials=_fields(instance.get("credentials"), secret=True),
        multiple=instance.get("multiple") is True,
        name_template=text_of(instance.get("name_template")),
        expose=expose,
        recommended=recommended,
        overrides=overrides,
        declared_tools=declared,
        homepage=web_url(raw.get("homepage")),
    )


#: 清单里插件目录的绝对路径。下划线开头 = 运行时注入,不是作者写的。
PATH_KEY = "_path"


def manifest_of(package: "PluginPackage") -> Manifest:
    """包记录 → 解析好的清单。**别处一律走这里**,不要直接 `.get()` 那个字典。"""
    raw = dict(package.manifest or {})
    return parse(raw, str(raw.get(PATH_KEY) or ""))


_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(text: str, values: dict[str, str]) -> str:
    """把 `${key}` 展开成配置 / 凭据的值。未填的展开成空串,而不是把 `${key}` 原样发出去。"""
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), text)


_NAME_FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(:label)?\}")


def render_name(manifest: Manifest, config: dict[str, Any]) -> str:
    """实例显示名。`{platform}` 取配置值,`{platform:label}` 取枚举的显示文案。

    **名字必须由配置生成**:此前包名是常量而平台是配置,于是用户配了 bilibili、面板上仍然
    写着「TikHub 抖音数据」。名字跟不上身份,比没有名字更坏。
    """
    template = manifest.name_template or manifest.name
    if template == manifest.name and not manifest.name_template:
        return manifest.name

    def _sub(match: re.Match[str]) -> str:
        key, wants_label = match.group(1), bool(match.group(2))
        value = str(config.get(key, ""))
        spec = manifest.field_for(key)
        return spec.option_label(value) if (wants_label and spec) else value

    return _NAME_FIELD.sub(_sub, template).strip() or manifest.name


__all__ = [
    "Field",
    "Manifest",
    "ManifestError",
    "PATH_KEY",
    "Runtime",
    "ToolOverride",
    "expand",
    "manifest_of",
    "parse",
    "render_name",
]
