"""插件:市场、安装、接入实例、工具暴露、权限与凭据、调用。"""

from __future__ import annotations

from datetime import datetime
from pydantic import Field
from app.api.schemas.base import ApiModel, OrmModel

class PluginOAuthCode(ApiModel):
    """对方显示出来、由用户贴回来的授权码。"""

    code: str = Field(min_length=1, max_length=2000)


class PluginFieldOut(ApiModel):
    """一个配置项或凭据项。凭据只是 secret=True 的配置 —— 差别在控件和回显,不在语义。"""

    key: str
    label: str
    type: str = "string"  # string | enum | number | boolean | json | code
    help: str = ""
    required: bool = True
    secret: bool = False
    options: list[dict] = Field(default_factory=list)
    default: str = ""
    #: 多行文本。界面给多行框。
    multiline: bool = False
    #: `json` / `code` 的语言(给代码编辑器挑高亮)。其余类型是空串。
    language: str = ""


class PluginToolStateOut(ApiModel):
    name: str
    label: str = ""
    description: str = ""
    read_only: bool = False
    input_schema: dict = Field(default_factory=dict)
    #: 暴不暴露给智能体与工作流。默认关 —— 一个 MCP 端点可能报几十个工具。
    exposed: bool = False
    #: 试跑表单的字段:和这个工具当工作流节点时同一份声明(节点目录的形状,已按语言翻好)。
    form: dict = Field(default_factory=dict)


class PluginCapabilityStatusOut(ApiModel):
    """一项宿主能力上一次对齐的结果。生成能力:刷出了几个模型、什么时候、没刷出来的话为什么。"""

    #: 上一次刷新成功时插件列了几个能用的模型。从没成功过就是 None。
    models: int | None = None
    #: 运行时报出的工具那一项:上一次报了几个工具。
    tools: int | None = None
    refreshed_at: str | None = None
    #: 上一次失败的原因(已按看的人的语言翻好)。成功过后清空。
    error: str = ""


class PluginProvidedInputOut(ApiModel):
    role: str
    max: int = 1
    required: bool = False


class PluginProvidedParameterOut(ApiModel):
    key: str
    title: str = ""
    type: str = ""
    advanced: bool = False


class PluginProvidedModelOut(ApiModel):
    """一个替宿主做生成的实例**提供的一个模型**(模型行上缓存的那一份),给插件页列出来。"""

    id: str
    label: str
    kind: str
    enabled: bool = True
    modes: list[str] = Field(default_factory=list)
    inputs: list[PluginProvidedInputOut] = Field(default_factory=list)
    #: 宿主自己有控件的那几项(尺寸、种子、反向提示词、一次几张……)。
    host_parameters: list[str] = Field(default_factory=list)
    #: 这个模型自己的参数(参数表里的那些)。
    parameters: list[PluginProvidedParameterOut] = Field(default_factory=list)


class PluginInstanceOut(ApiModel):
    id: str
    package_id: str
    name: str
    enabled: bool
    config: dict = Field(default_factory=dict)
    #: 为什么还不能用(未启用 / 缺配置 / 缺凭据 / 未授权)。空串 = 可用。
    blocked_reason: str = ""
    tools: list[PluginToolStateOut] = Field(default_factory=list)
    #: 它替宿主做的那些事上一次做得怎么样,按能力分(今天只有 generation)。
    capability_status: dict[str, PluginCapabilityStatusOut] = Field(default_factory=dict)


class PluginPackageOut(ApiModel):
    id: str
    name: str
    version: str
    kind: str = "process"  # process | mcp
    multiple: bool = False
    permissions: list[str] = Field(default_factory=list)
    #: 插件自己的文档/主页。空 = 作者没写,界面就不画那个链接。
    homepage: str = ""
    author_name: str = ""
    author_url: str = ""
    #: 这个插件在 Mosael 里怎么用的文档(已按看的人的语言挑好)。空 = 没写。
    docs: str = ""
    config_fields: list[PluginFieldOut] = Field(default_factory=list)
    credential_fields: list[PluginFieldOut] = Field(default_factory=list)
    #: 这个插件能不能自己走 OAuth。界面据此决定要不要给「去授权」。
    oauth: bool = False
    #: 它能替宿主做成哪些事(`public_url` / `generation`)。
    provides: list[str] = Field(default_factory=list)
    #: 随应用一起发的(见 domain/plugins/bundled)。卸不掉,界面不给「卸载」。
    bundled: bool = False
    instances: list[PluginInstanceOut] = Field(default_factory=list)


class PluginMarketTool(ApiModel):
    """市场里一个插件声明的工具。只有「它是什么」,没有入参 —— 怎么调是装上之后的事。"""

    name: str
    label: str = ""
    #: 作者写的说明,**可能带 markdown**(`**公网直链**`)—— 界面负责渲染,不在这里剥。
    description: str = ""


class PluginMarketEntry(ApiModel):
    """市场里的一条。索引给什么就是什么 —— 不做补全,免得看起来比实际更可信。"""

    id: str
    name: str = ""
    description: str = ""
    version: str = ""
    author: str = ""
    author_url: str = ""
    homepage: str = ""
    docs: str = ""
    download: str = ""
    permissions: list[str] = Field(default_factory=list)
    #: process = 本机脚本,工具就是 `tools` 那几个;mcp = 接一个 MCP server,工具由它自己报,装上才知道。
    runtime: str = "process"
    #: 它能替 Mosael 做的几类事(public_url …)。
    provides: list[str] = Field(default_factory=list)
    tools: list[PluginMarketTool] = Field(default_factory=list)
    #: 这台机器上装没装过同 id 的包。装过的话界面给的是「更新」而不是「安装」。
    installed: bool = False
    installed_version: str = ""
    #: 随应用一起发的(`plugins/bundled/`,见 domain/plugins/bundled)。它不从市场装、也不从市场
    #: 更新 —— 新版跟着应用来,所以界面不给装 / 更新 / 卸载,只标「内置」。
    bundled: bool = False


class PluginMarketOut(ApiModel):
    """市场这一屏:条目 + 远端索引这一次拉没拉到。

    **随应用内置的插件不依赖远端索引** —— 它就在这台机器上。所以索引拉不到时照样列出它们,
    同时把拉不到的原因交给界面说出来:只给一个空列表,人会以为市场里就这么几个。
    """

    plugins: list[PluginMarketEntry]
    #: 远端索引拉不到的原因(已按看的人的语言译好);拉到了就是空串。
    index_error: str = ""


class PluginInstallRequest(ApiModel):
    url: str = Field(min_length=1, max_length=1000)
    #: 覆盖已装的同 id 包。要单独同意 —— 那个目录里可能已经有用户填过的东西,
    #: 而且新版本可能声明了完全不同的权限。
    overwrite: bool = False


class PluginInstallPreview(ApiModel):
    """装之前先看清楚:它是谁、要什么权限。"""

    id: str
    name: str = ""
    version: str = ""
    description: str = ""
    permissions: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    homepage: str = ""
    author_name: str = ""
    author_url: str = ""
    docs: str = ""
    installed: bool = False
    installed_version: str = ""


class PluginInstanceCreate(ApiModel):
    name: str = ""
    config: dict = Field(default_factory=dict)


class PluginInstanceUpdate(ApiModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None


class PluginCapabilityUpdate(ApiModel):
    #: 工具名 → 暴不暴露。
    tools: dict[str, bool] = Field(default_factory=dict)


class PluginEnableRequest(ApiModel):
    enabled: bool


class PluginPermissionGrantOut(OrmModel):
    instance_id: str
    permission: str
    granted: bool
    created_at: datetime
    updated_at: datetime


class PluginPermissionGrantUpdate(ApiModel):
    grants: dict[str, bool] = Field(default_factory=dict)


class PluginCredentialOut(ApiModel):
    """插件声明的一项凭据 + 当前状态。secret 项的 value 是掩码,不是原值。"""

    key: str
    label: str
    help: str = ""
    secret: bool = True
    required: bool = True
    filled: bool = False
    value: str = ""


class PluginCredentialUpdate(ApiModel):
    #: 键 → 值。掩码原样回传表示"这项没改";空串表示清空。
    values: dict[str, str] = Field(default_factory=dict)


class PluginToolOut(ApiModel):
    """一个**已暴露**的工具。智能体工具表与工作流节点面板读的就是这个。"""

    instance_id: str
    instance_name: str
    package_id: str
    name: str
    label: str = ""
    description: str = ""
    read_only: bool = False
    input_schema: dict = Field(default_factory=dict)


class PluginInvokeRequest(ApiModel):
    input: dict = Field(default_factory=dict)
    workspace_id: str | None = Field(default=None, min_length=1)


class PluginInvocationOut(OrmModel):
    id: str
    instance_id: str
    tool_name: str
    status: str
    input: dict
    output: dict
    error: str | None
    created_at: datetime


# --- 素材外链用哪一家存储(设置 → 视频生成) ---

class AssetLinkStorageOption(ApiModel):
    instance_id: str
    name: str
    #: 还缺哪些必填项;空 = 配好了,选得了。
    missing: list[str] = Field(default_factory=list)


class AssetLinkStorageOut(ApiModel):
    #: 我定的那一家;没定是 None。
    current: str | None = None
    #: 不定的话会用的那一家(只有一家配好时),和现在定没定无关;几家都配好时是 None —— 不定就会当场问。
    automatic: str | None = None
    options: list[AssetLinkStorageOption] = Field(default_factory=list)


class AssetLinkStorageUpdate(ApiModel):
    instance_id: str | None = None
