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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

#: i18n 是纯叶子(只依赖标准库),运行时 import 它不会把这个模块拖出叶子位置。
from app.core.i18n import LocalizedError, pick_text

if TYPE_CHECKING:  # 仅为类型;运行时不 import models,保持这个模块是叶子
    from app.db.models import PluginPackage

#: 配置项 / 凭据项的键。同时是 `${...}` 占位符的名字,也是进程插件的环境变量名(大写化)。
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: 配置项的类型。`json` / `code` 是**一段代码**:界面给代码编辑器(不是一个多行文本框),`json` 保存前
#: 必须能解析(错在第几行第几列当场说)。值照旧存成字符串 —— 插件拿到的就是它粘进去的那一段原文,
#: 自己解析;存成解析后的对象会让「原文里的注释、键的顺序、缩进」在一次保存之后悄悄变样。
FIELD_TYPES = ("string", "enum", "number", "boolean", "json", "code")
#: 代码类的配置项。
CODE_FIELD_TYPES = ("json", "code")

#: 插件能替宿主做成的事里,**只给宿主调**的那几项(见 docs/adr/0020)。
#:
#: `public_url` 不在里面:对象存储的上传工具本身就是个正经工具,智能体和工作流也该调得到。
#: `generation` 在:认领它的那个工具说的是一套流式协议(进度、回执、取消),不是一次普通调用 ——
#: 让智能体直接调它,等于留一条绕开生成任务、用量台账和回执的后门(和 `internal: true` 同一个理由,
#: 这里由能力本身决定,作者不必再写一遍)。
GENERATION = "generation"
#: `tools`:**运行时报出工具清单**(见 domain/plugins/dynamic_tools)。认领它的那个工具只回答「我这个连接此刻
#: 有哪些工具」,本身不是给智能体调的。
TOOLS = "tools"
HOST_ONLY_CAPABILITIES = frozenset({GENERATION, TOOLS})


#: 这次调用要说哪种语言,插件自己也会拿到它(见 runtime/mcp_bridge 里的 MOSAEL_LOCALE)。
LOCALE_ENV = "MOSAEL_LOCALE"


def text_of(value: Any, locale: str | None = None, *, author_locale: str = "") -> str:
    """清单里一段**给人看的文字**。既可以是普通字符串,也可以是按语言分的对象:

        "label": "起始目录"
        "label": { "zh": "起始目录", "en": "Start directory" }

    **翻译贴着它翻译的那个东西写**,不放在清单顶上的一张 `{"config.X.label": …}` 表里 ——
    那种表的键要和别处对得上,而对不上时不会报错,只会让那一条永远显示原文。这个项目在
    「手抄一张表」上栽过好几次。

    挑法见 `core.i18n.pick_text`(内置模板的节点名走同一个:两边都是"数据自带的文案")。
    """
    return pick_text(value, locale, author_locale=author_locale)


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
    #: 多行文本。只对 `string` 有意义:单行框装一份几百行的东西,用户看到的只是它的第一行。
    #: 一段 JSON、一段脚本不要用它 —— 用 `type: "json"` / `type: "code"`,那两种有代码编辑器和校验。
    multiline: bool = False
    #: `code` 的语言(`python` / `yaml` / …),决定编辑器按什么高亮;`json` 固定是 json。
    language: str = ""

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
class OAuthSpec:
    """插件自己去走一次 OAuth,而不是让用户手抄 refresh_token。

    **这些字段是插件作者声明的,不是我们猜的。** 每家的授权端点、参数名、返回体都不一样,
    而我们既不认识百度网盘也不认识下一个 —— 作者知道,所以由清单说。

    `client_id_field` / `client_secret_field` 指向**已有的凭据键**:AppKey 和 SecretKey 本来
    就要用户去开放平台注册,那一步替代不了。能替代的是后面那一段 —— 拼授权链接、拿 code
    换 token、把 token 存回哪几个键,这些是纯机械的,却正是最容易抄错的部分。

    `stores` 把令牌响应里的字段映射到凭据键(`{"refresh_token": "REFRESH_TOKEN"}`):
    响应里叫什么由对方定,存进哪个键由插件定,两边都不该由我们写死。
    """

    authorize_url: str = ""
    token_url: str = ""
    client_id_field: str = ""
    client_secret_field: str = ""
    scope: str = ""
    #: 重定向地址。`oob` = 对方把授权码显示出来让人贴回来(百度网盘等支持)。
    redirect_uri: str = "oob"
    #: 令牌响应字段 → 凭据键。
    stores: dict[str, str] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return bool(self.authorize_url and self.token_url and self.client_id_field and self.stores)


@dataclass(frozen=True)
class ToolOverride:
    label: str = ""
    description: str = ""
    read_only: bool = False
    node: dict[str, Any] | None = None
    #: 只给宿主自己的适配层调(比如 3D 场景与 Blender 的互通),**不暴露给智能体和工作流**。
    #: 用在「插件自带一个不经确认的原始入口、而 Mosael 已经有带确认卡的同一能力」时 ——
    #: 两条路并存,不经确认的那条就是绕开确认的后门。
    internal: bool = False


@dataclass(frozen=True)
class Author:
    """谁做的、去哪儿找他。名字可以按语言分(和清单里别的文案一样),主页只认 http(s)。"""

    name: str = ""
    url: str = ""


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
    #: 作者。插件是别人的代码,装之前、用的时候都该看得见是谁写的、去哪儿找他。
    author: Author = field(default_factory=Author)
    #: **这个插件在 Mosael 里怎么用**的文档。和 homepage 不是一回事:homepage 常常是它背后那家
    #: 服务的站点(百度网盘的开放平台文档),而「在这里怎么配、工具各干什么」只有插件自己的文档讲。
    #: 可以按语言分(`{"zh": …, "en": …}`),界面挑看的人那种语言的。
    docs: str = ""
    #: 声明了就能在设置页点「去授权」,不必手抄令牌(见 domain/plugins/oauth)。
    oauth: OAuthSpec | None = None
    #: 这个插件**能替宿主做成哪几件事**。今天只有一项:`public_url` —— 「把一份本地素材变成
    #: 一条公网可下载的地址」。
    #:
    #: **声明,不是猜。** 宿主需要这个能力时(比如某家生成模型的参考视频只收链接),得找得到
    #: 一个能做这件事的插件;靠工具名后缀 `_upload` 去猜的话,任何一个叫这个名字的工具都会被
    #: 当成对象存储,而猜错的表现是把用户的素材传去了别的地方。
    provides: list[str] = field(default_factory=list)
    #: 清单里那些**裸字符串**是用哪种语言写的。挑不到要的语言时先退到它,再退到部署缺省 ——
    #: 不写就退到作者写的第一条。它同时是告诉插件进程「这次要说哪种语言」的兜底(见 runtime)。
    default_locale: str = ""

    def tool_providing(self, capability: str) -> str:
        """清单里**声明自己负责** `capability` 的那个工具名(工具声明上的 `provides`);没有就是空串。

        能力声明在包上(`provides`)说的是「这个插件能做这件事」,而做这件事的是哪一个工具,
        要由工具自己说 —— 此前宿主按 `_upload` 后缀去猜,和上面「声明,不是猜」自相矛盾。
        """
        for tool in self.declared_tools:
            provides = tool.get("provides")
            if isinstance(provides, list) and capability in provides:
                return str(tool.get("name") or "")
        return ""

    def text(self, value: Any, locale: str | None = None) -> str:
        """按这份清单的语言习惯挑一段文字(见 text_of)。清单在手时一律走它。"""
        return text_of(value, locale, author_locale=self.default_locale)

    @property
    def is_mcp(self) -> bool:
        return self.runtime.kind == "mcp"

    def field_for(self, key: str) -> Field | None:
        for item in (*self.config, *self.credentials):
            if item.key == key:
                return item
        return None


class ManifestError(LocalizedError, ValueError):
    """清单不合法。带文案 key(`pluginErr_manifest*`)。"""


def _humanized(entry: dict[str, Any], *keys: str, pick: Callable[[Any], str] = text_of) -> dict[str, Any]:
    """把一个原样透传的字典里那几个给人看的键就地定下语言 —— 其余原封不动。

    技能、工具声明这些是整个字典往下传的(它们的形状由插件作者定,我们不该逐字段抄一遍),
    所以只挑名字确定的那几个键翻,别的一个字不动。
    """
    picked = {k: pick(entry[k]) for k in keys if k in entry}
    return {**entry, **picked} if picked else entry


def localized_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """一个**运行时报出的**工具声明,按此刻的语言定下给人看的字(名字、说明、入参的 title / description)。

    清单里声明的工具在解析清单时就定了;运行时报出的那些原样存着(刷新发生在后台,那一刻的语言不是
    看的人的语言),每次读的时候走这里。
    """
    return _humanized_schema(_humanized(tool, "label", "description"))


#: JSON Schema 里给人看的键。**这两个会显示在界面上**,别的(type、format、enum…)是数据。
_SCHEMA_TEXT_KEYS = ("description", "title")


#: 这些键下面是「名字 → 子 schema」的表:键是**字段名**,不是关键字。一个参数就叫 `title` 或
#: `description`(发布类插件里再常见不过)时,不能把它当成说明文字去翻 —— 那会把整个字段的
#: schema 换成一个字符串(Remotion 插件的 `title` 参数就这样丢了类型和说明)。
_SCHEMA_NAME_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})


def _named_schemas(value: Any, pick: Callable[[Any], str]) -> Any:
    """名字 → 子 schema:名字原样保留,每个子 schema 照常走一遍。"""
    if isinstance(value, dict):
        return {name: _humanized_schema(item, pick) for name, item in value.items()}
    return _humanized_schema(value, pick)


def _humanized_schema(value: Any, pick: Callable[[Any], str] = text_of) -> Any:
    """把 `input_schema` 里的 description / title 也定下语言。

    工具自己的 description 一直是翻的,而**参数的那一份不是** —— 于是试运行面板里每个
    参数标签后面跟着一句 `[object Object]`,因为界面直接把 `{"zh": …, "en": …}` 这个对象
    渲染了出来。作者按清单里到处都能用的写法写了双语,而这一处偏偏不认。

    整棵树走一遍而不是只看 `properties`:JSON Schema 里说明文字可以出现在 items、
    oneOf、$defs 的任何一层,只认一层等于换个写法就又漏了。
    """
    if isinstance(value, dict):
        out = {
            key: _named_schemas(item, pick) if key in _SCHEMA_NAME_MAPS else _humanized_schema(item, pick)
            for key, item in value.items()
        }
        for key in _SCHEMA_TEXT_KEYS:
            # 只有本来就是「语言对象」的才动。普通字符串经过 text_of 也原样返回,
            # 但显式判断能让"这里为什么不会误伤别的结构"一眼看得出来。
            if isinstance(value.get(key), dict):
                out[key] = pick(value[key])
        return out
    if isinstance(value, list):
        return [_humanized_schema(item, pick) for item in value]
    return value


def _fields(raw: Any, *, secret: bool, pick: Callable[[Any], str] = text_of) -> list[Field]:
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
                    options.append({"value": str(option["value"]), "label": pick(option.get("label")) or str(option["value"])})
                elif isinstance(option, str):
                    options.append({"value": option, "label": option})
        declared_type = str(entry.get("type") or ("string" if not options else "enum"))
        out.append(
            Field(
                key=key,
                label=pick(entry.get("label")) or key,
                type=declared_type if declared_type in FIELD_TYPES else "string",
                help=pick(entry.get("help")),
                required=entry.get("required") is not False,
                # 凭据默认按密文对待,漏标不该导致明文回显;配置默认明文。
                secret=bool(entry.get("secret", secret)),
                options=options,
                default=str(entry.get("default") or ""),
                multiline=entry.get("multiline") is True and declared_type in ("string", ""),
                language=_language(declared_type, entry.get("language")),
            )
        )
    return out


def _language(declared_type: str, raw: Any) -> str:
    """代码类配置项的语言:`json` 就是 json;`code` 取声明的(只收小写字母数字,那是给编辑器挑高亮的名字)。"""
    if declared_type == "json":
        return "json"
    if declared_type != "code":
        return ""
    language = str(raw or "").strip().lower()
    return language if re.fullmatch(r"[a-z0-9+#-]{1,20}", language) else "text"


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


def _tools_policy(raw: dict[str, Any], pick: Callable[[Any], str] = text_of) -> tuple[str, list[str], dict[str, ToolOverride], list[dict[str, Any]]]:
    """→ (expose, recommended, overrides, 进程插件声明的工具)。

    `tools` 是个策略对象:`declare` 是进程插件的工具声明,`recommended` 是首次启用默认勾上
    的那些,`overrides` 按名字覆盖(目前只认 read_only、node 和 internal)。三个名字各说各的 ——
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
            label=pick(spec.get("label")),
            description=pick(spec.get("description")),
            read_only=spec.get("read_only") is True,
            node=spec.get("node") if isinstance(spec.get("node"), dict) else None,
            internal=spec.get("internal") is True,
        )
    declared = [
        _humanized_schema(_humanized(t, "label", "description"))
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
            raise ManifestError("pluginErr_manifestMissingField", path=path, field=key)
    author_locale = str(raw.get("default_locale") or "").strip()

    def pick(value: Any) -> str:
        return text_of(value, author_locale=author_locale)

    #: 名字是给人看的,可以按语言写;但空的仍然是缺字段。
    name = pick(raw.get("name")).strip()
    if not name:
        raise ManifestError("pluginErr_manifestMissingField", path=path, field="name")
    instance = raw.get("instance") if isinstance(raw.get("instance"), dict) else {}
    expose, recommended, overrides, declared = _tools_policy(raw, pick)
    # 工具上声明的能力必须是包声明过的 —— 包上没说「我能换公网地址」,某个工具却自称负责它,
    # 两处说的不是一回事,宿主不该替作者选一个信。
    package_provides = {str(one) for one in (raw.get("provides") or []) if isinstance(one, str)}
    for tool in declared:
        extra = set(tool.get("provides") or []) - package_provides if isinstance(tool.get("provides"), list) else set()
        if extra:
            raise ManifestError(
                "pluginErr_manifestToolExtraCapability", path=path, tool=tool.get("name"), capabilities=", ".join(sorted(extra))
            )
    _check_host_only(package_provides, declared, runtime_of(raw), path)
    return Manifest(
        id=raw["id"].strip(),
        name=name,
        version=raw["version"].strip(),
        path=path,
        runtime=runtime_of(raw),
        permissions=[p for p in (raw.get("permissions") or []) if isinstance(p, str) and p.strip()],
        skills=[_humanized(s, "name", "description", pick=pick) for s in (raw.get("skills") or []) if isinstance(s, dict)],
        config=_fields(instance.get("config"), secret=False, pick=pick),
        credentials=_fields(instance.get("credentials"), secret=True, pick=pick),
        multiple=instance.get("multiple") is True,
        name_template=pick(instance.get("name_template")),
        expose=expose,
        recommended=recommended,
        overrides=overrides,
        declared_tools=declared,
        homepage=web_url(raw.get("homepage")),
        author=_author(raw.get("author"), pick),
        docs=web_url(pick(raw.get("docs"))),
        provides=[str(one) for one in (raw.get("provides") or []) if isinstance(one, str)],
        default_locale=author_locale,
        # **读 instance 里那一层。** oauth 块引用的 client_id_field / stores 全是
        # instance.credentials 里的键,放在顶层的话作者会把它写在它引用的东西旁边(合理),
        # 然后得到一个静默消失的授权按钮 —— 这个坑第一个踩进去的就是写解析器的人。
        oauth=_oauth(instance.get("oauth")),
    )


def _check_host_only(
    package_provides: set[str], declared: list[dict[str, Any]], runtime: Runtime, path: str
) -> None:
    """只给宿主调的能力(今天是 `generation`)比 `public_url` 多三条硬规矩,**装的那一刻就说清楚**。

    `public_url` 那边「包上声明了、没有工具认领」是一个老版本,生成时再让用户去更新;这里不留那个口子:
    生成能力是新的,没有老版本要照顾,而一个认领不清的生成插件会在选择器里长出一排点了必然失败的模型。
    """
    for capability in sorted(package_provides & HOST_ONLY_CAPABILITIES):
        # MCP 是别人的协议,我们不往里加字段(和 artifact / state 同一条)。
        if runtime.kind != "process":
            raise ManifestError("pluginErr_manifestCapabilityNeedsProcess", path=path, capability=capability)
        owners = [
            str(tool.get("name")) for tool in declared
            if isinstance(tool.get("provides"), list) and capability in tool["provides"]
        ]
        if not owners:
            raise ManifestError("pluginErr_manifestCapabilityUnclaimed", path=path, capability=capability)
        if len(owners) > 1:
            raise ManifestError(
                "pluginErr_manifestCapabilityClaimedTwice", path=path, capability=capability, tools=", ".join(owners)
            )


def _author(raw: object, pick: Callable[[Any], str] = text_of) -> Author:
    """`{"name": …, "url": …}`。只有这一种写法 —— 两种写法并存,读的人就得记两种。"""
    if not isinstance(raw, dict):
        return Author()
    return Author(name=pick(raw.get("name")).strip(), url=web_url(raw.get("url")))


def _oauth(raw: object) -> OAuthSpec | None:
    """解析 oauth 块。**声明不全就当没声明** —— 半个声明会让界面长出一个点了必然失败的按钮。"""
    if not isinstance(raw, dict):
        return None
    spec = OAuthSpec(
        authorize_url=web_url(raw.get("authorize_url")),
        token_url=web_url(raw.get("token_url")),
        client_id_field=text_of(raw.get("client_id_field")).strip(),
        client_secret_field=text_of(raw.get("client_secret_field")).strip(),
        scope=text_of(raw.get("scope")).strip(),
        redirect_uri=text_of(raw.get("redirect_uri")).strip() or "oob",
        stores={
            str(key): str(value)
            for key, value in (raw.get("stores") or {}).items()
            if isinstance(key, str) and isinstance(value, str) and key and value
        },
    )
    return spec if spec.usable else None


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
    "GENERATION",
    "HOST_ONLY_CAPABILITIES",
    "Manifest",
    "ManifestError",
    "PATH_KEY",
    "Runtime",
    "TOOLS",
    "ToolOverride",
    "expand",
    "localized_tool",
    "manifest_of",
    "parse",
    "render_name",
]
