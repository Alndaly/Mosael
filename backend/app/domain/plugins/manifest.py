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
from typing import Any

#: 配置项 / 凭据项的键。同时是 `${...}` 占位符的名字,也是进程插件的环境变量名(大写化)。
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

FIELD_TYPES = ("string", "enum", "number", "boolean")


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
                    options.append({"value": str(option["value"]), "label": str(option.get("label") or option["value"])})
                elif isinstance(option, str):
                    options.append({"value": option, "label": option})
        declared_type = str(entry.get("type") or ("string" if not options else "enum"))
        out.append(
            Field(
                key=key,
                label=str(entry.get("label") or key),
                type=declared_type if declared_type in FIELD_TYPES else "string",
                help=str(entry.get("help") or ""),
                required=entry.get("required") is not False,
                # 凭据默认按密文对待,漏标不该导致明文回显;配置默认明文。
                secret=bool(entry.get("secret", secret)),
                options=options,
                default=str(entry.get("default") or ""),
            )
        )
    return out


def _runtime(raw: dict[str, Any]) -> Runtime:
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
            label=str(spec.get("label") or ""),
            description=str(spec.get("description") or ""),
            read_only=spec.get("read_only") is True,
            node=spec.get("node") if isinstance(spec.get("node"), dict) else None,
        )
    declared = [t for t in (tools.get("declare") or []) if isinstance(t, dict) and isinstance(t.get("name"), str)]
    recommended = [str(n) for n in (tools.get("recommended") or [])]
    return ("all" if expose == "all" else "selected"), recommended, overrides, declared


def parse(raw: dict[str, Any], path: str) -> Manifest:
    for key in ("id", "name", "version"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ManifestError(f"插件清单 {path} 缺少必填字段: {key}")
    instance = raw.get("instance") if isinstance(raw.get("instance"), dict) else {}
    expose, recommended, overrides, declared = _tools_policy(raw)
    return Manifest(
        id=raw["id"].strip(),
        name=raw["name"].strip(),
        version=raw["version"].strip(),
        path=path,
        runtime=_runtime(raw),
        permissions=[p for p in (raw.get("permissions") or []) if isinstance(p, str) and p.strip()],
        skills=[s for s in (raw.get("skills") or []) if isinstance(s, dict)],
        config=_fields(instance.get("config"), secret=False),
        credentials=_fields(instance.get("credentials"), secret=True),
        multiple=instance.get("multiple") is True,
        name_template=str(instance.get("name_template") or ""),
        expose=expose,
        recommended=recommended,
        overrides=overrides,
        declared_tools=declared,
    )


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


__all__ = ["Field", "Manifest", "ManifestError", "Runtime", "ToolOverride", "expand", "parse", "render_name"]
