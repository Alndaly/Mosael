"""插件:市场、安装、接入实例、工具暴露、权限与凭据、调用。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from app.api.schemas.base import ApiModel, OrmModel
from app.api.schemas.capabilities import CapabilityUseOut
from app.api.schemas.jobs import JobOut

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


class PluginCapabilityUseOut(CapabilityUseOut):
    #: 插件工具可以认领几项能力,每条标明是哪一项。
    capability: str


class PluginToolStateOut(ApiModel):
    name: str
    label: str = ""
    description: str = ""
    read_only: bool = False
    #: 后果(none / paid / external / local-code,见 domain/effects)。不是 none 的,智能体调它之前先开确认卡 ——
    #: 插件页据此在工具旁标「需确认」。
    effects: str
    input_schema: dict = Field(default_factory=dict)
    #: 暴不暴露给智能体与工作流。默认关 —— 一个 MCP 端点可能报几十个工具。
    exposed: bool = False
    #: 试跑表单的字段:和这个工具当工作流节点时同一份声明(节点目录的形状,已按语言翻好)。
    form: dict = Field(default_factory=dict)
    #: 它认领的调用类能力(`document_parse`、`audio_denoise` ……):它是一个普通工具,能力是加在它上面的一份契约
    #: (ADR 0033)。插件页据此标一枚能力徽标。
    provides: list[str] = Field(default_factory=list)
    #: 这些能力在 Mosael 里还用在哪 —— 能力表现算的(ADR 0032 §4)。宿主的这些入口调的也是这个工具。
    used_by: list[PluginCapabilityUseOut] = Field(default_factory=list)


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


class PackageSourcePresetOut(ApiModel):
    """一个预设镜像:key、名字、地址(官方源的地址是空串)。"""

    value: str
    label: str
    url: str = ""


class PluginPackageSourceOut(ApiModel):
    """这个连接装包从哪个镜像拉,一个生态一行(见 domain/plugins/package_sources)。只列清单里声明了的生态。"""

    #: `pypi` / `npm`。
    source: str
    label: str
    #: 连接自己的覆盖:预设 key 或自定义地址;空 = 跟随「管理 → 下载源」。
    value: str = ""
    #: 跟随时实际是哪一个(管理页定的那个的名字),下拉里「跟随 Mosael(…)」照它写。
    host_label: str = ""
    presets: list[PackageSourcePresetOut] = Field(default_factory=list)


class PluginNetworkOut(ApiModel):
    """这个连接往外连走哪条路(见 domain/plugins/egress)。"""

    #: follow = 跟随 Mosael 的出站代理;direct = 直连;proxy = 走下面这个地址。
    mode: Literal["follow", "direct", "proxy"] = "follow"
    #: 只有 `proxy` 模式下有值。
    proxy_url: str = ""


class PluginInstanceOut(ApiModel):
    id: str
    package_id: str
    name: str
    enabled: bool
    config: dict = Field(default_factory=dict)
    #: 为什么还不能用(未启用 / 缺配置 / 缺凭据 / 未授权)。空串 = 可用。
    blocked_reason: str = ""
    #: 清单声明了、还没授予的权限(按清单里的先后)。界面据此在连接上摆一条「授予这几项」。
    pending_permissions: list[str] = Field(default_factory=list)
    #: 还缺的权限是插件更新后多要的(这个连接之前授予过别的):界面说「插件多要了权限」,不是「还没授权」。
    permissions_added: bool = False
    #: 声明了 `instance.oauth` 的连接授权到哪一步:没授权过 / 授权过 / 插件上一次说对方不认了。
    #: 没声明 oauth 的是空串。只按授权写的那几格**填没填**算,令牌不出后端。
    authorization: Literal["", "unauthorized", "authorized", "rejected"] = ""
    tools: list[PluginToolStateOut] = Field(default_factory=list)
    #: 它替宿主做的那些事上一次做得怎么样,按能力分(今天只有 generation)。
    capability_status: dict[str, PluginCapabilityStatusOut] = Field(default_factory=dict)
    network: PluginNetworkOut = Field(default_factory=PluginNetworkOut)
    package_sources: list[PluginPackageSourceOut] = Field(default_factory=list)


class PluginOAuthOut(ApiModel):
    """插件声明的 OAuth,界面要知道的那一部分。端点、client_id 这些是后端拼链接用的,不往外给。"""

    #: 授权会写的那几格凭据的键(清单 `stores` 指向的,按清单里的先后)。界面把它们收进
    #: 「手动填写」,不和 AppKey 一样摆成主输入。
    fills: list[str] = Field(default_factory=list)


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
    #: 收起的连接那一行摆哪一项配置的键(名字模板里引用的第一个配置项,没有就第一个必填的文本项);空串 = 不摆。
    summary_field: str = ""
    credential_fields: list[PluginFieldOut] = Field(default_factory=list)
    #: 这个插件能自己走 OAuth 的话是它的声明,否则 None。界面据此决定要不要给「去授权」。
    oauth: PluginOAuthOut | None = None
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
    #: 后果(见 domain/effects),由清单算出来。老索引里没有这一项就是空串 —— 不猜,界面不标。
    effects: str = ""


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
    #: 包的 sha256(发版索引里有;内置插件、老索引没有)。从市场装时原样交回,后端下载后核对。
    sha256: str = ""
    permissions: list[str] = Field(default_factory=list)
    #: process = 本机脚本,工具就是 `tools` 那几个;mcp = 接一个 MCP server,工具由它自己报,装上才知道。
    runtime: str = "process"
    #: 它能替 Mosael 做的几类事(public_url …)。
    provides: list[str] = Field(default_factory=list)
    tools: list[PluginMarketTool] = Field(default_factory=list)
    #: 这台机器上装没装过同 id 的包。装过的话界面给的是「更新」而不是「安装」。
    installed: bool = False
    installed_version: str = ""
    #: 索引许的版本**比装着的新**(按语义化版本比先后,见 mosael_formats.versions),而且没被证实
    #: 「还没发布」。界面据此给「更新」—— 不自己拿两个字符串比不相等。
    update_available: bool = False
    #: 索引许的版本比装着的新,但点「更新」下下来的包并不比装着的新:新版本还没发布。
    #: 界面据此不给「更新」、说清为什么(见 domain/plugins/updates)。
    update_unreleased: bool = False
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
    #: 从市场点的:索引里给这一条写的版本。有它才是「从市场更新」—— 下下来的包不比装着的新时,
    #: 不装、不报「已更新」,而是说「新版本还没发布」。从链接装时为空(同一版重装是有意的)。
    advertised_version: str = Field(default="", max_length=40)
    #: 从市场点的:索引给这个包写的 sha256。下下来的包对不上就不装(地址被换、CDN 给错了文件)。
    sha256: str = Field(default="", pattern="^([0-9a-fA-F]{64})?$")


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
    #: 从市场点「更新」,而包里实际那一版(上面的 `version`)不比装着的新:新版本还没发布。
    #: 界面据此不给确认卡、说清为什么,市场里这一条也不再说「有新版」。
    update_unreleased: bool = False


class PluginInstanceCreate(ApiModel):
    name: str = ""
    config: dict = Field(default_factory=dict)


class PluginNetworkUpdate(ApiModel):
    mode: Literal["follow", "direct", "proxy"]
    #: `proxy` 模式必填;别的模式下忽略(存成空串)。
    proxy_url: str = Field(default="", max_length=300)


class PluginInstanceUpdate(ApiModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    network: PluginNetworkUpdate | None = None
    #: 生态 → 预设 key 或自定义地址;空串 = 改回跟随。只动给了的那几个生态。
    package_sources: dict[str, str] | None = None


class PluginCapabilityUpdate(ApiModel):
    #: 工具名 → 暴不暴露。
    tools: dict[str, bool] = Field(default_factory=dict)


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
    #: 后果(见 domain/effects)。不是 none 的,智能体调它之前先开确认卡。
    effects: str
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


# --- 模型库(ADR 0034) ----------------------------------------------------

class ModelLibraryRefOut(ApiModel):
    """一张工作流:id 和给人看的名字。"""

    id: str
    label: str


class ModelLibraryFolderOut(ApiModel):
    name: str
    count: int = 0


class ModelFileOut(ApiModel):
    """那台服务器上的一个模型文件。预览图走宿主的地址(`/model-library/preview`),那一头的地址不出现在这里。"""

    folder: str
    #: 目录内的相对路径(可带子目录;Windows 上的分隔符是反斜杠)。
    name: str
    size: int | None = None
    modified: float | None = None
    #: 推断的底模家族(SDXL、Illustrious、Flux……;认不出是空串)与凭的是什么(`metadata` / `filename`)。
    family: str = ""
    family_source: str = ""
    triggers: list[str] = Field(default_factory=list)
    #: `metadata`(作者写的触发词)或 `tags`(训练标签里出现最多的几个,不一定是触发词)。
    triggers_source: str = ""
    title: str = ""
    has_preview: bool = False
    used_by: list[ModelLibraryRefOut] = Field(default_factory=list)


class MissingModelOut(ApiModel):
    """工作流声明了下载地址、这台服务器上又没有的模型。"""

    folder: str
    name: str
    url: str
    workflows: list[ModelLibraryRefOut] = Field(default_factory=list)


class ModelDownloadRouteOut(ApiModel):
    """这台服务器下载走哪条路:`manager` / `local` / `none`,外加一句给人看的说明。"""

    route: str = "none"
    note: str = ""


class ModelLibraryOut(ApiModel):
    folders: list[ModelLibraryFolderOut] = Field(default_factory=list)
    models: list[ModelFileOut] = Field(default_factory=list)
    missing: list[MissingModelOut] = Field(default_factory=list)
    download: ModelDownloadRouteOut = Field(default_factory=ModelDownloadRouteOut)
    #: 这个连接最近的下载任务(在跑的总在里面)。
    downloads: list[JobOut] = Field(default_factory=list)


class ModelTagOut(ApiModel):
    tag: str
    count: int = 0


class ModelDetailOut(ApiModel):
    folder: str
    name: str
    metadata: dict[str, str] = Field(default_factory=dict)
    tags: list[ModelTagOut] = Field(default_factory=list)


class ModelResolveRequest(ApiModel):
    url: str = Field(min_length=1, max_length=4000)


class ModelResolveOut(ApiModel):
    """一个链接指的是什么。`exists`:这个名字在建议的目录里已经有了(不覆盖,界面要求换名)。"""

    source: str = ""
    url: str
    page: str = ""
    filename: str = ""
    size: int | None = None
    folder: str = ""
    family: str = ""
    triggers: list[str] = Field(default_factory=list)
    title: str = ""
    exists: bool = False
    note: str = ""
    #: 下载时会带上那个站的令牌(连接上填了 HuggingFace / Civitai / ModelScope 令牌)。经 ComfyUI-Manager 下载 Civitai 时,
    #: 令牌只能拼进下载地址、留在那台机器的任务记录里;HuggingFace / ModelScope 的带不过去 —— 界面据此在下载框里提醒。
    uses_token: bool = False


class ModelDownloadRequest(ApiModel):
    workspace_id: str
    url: str = Field(min_length=1, max_length=4000)
    folder: str = Field(min_length=1, max_length=200)
    filename: str = Field(max_length=300)


# --- 工作流库(ADR 0035) ---------------------------------------------------

class WorkflowGraphNodeOut(ApiModel):
    """缩略图上的一个节点:位置、大小(工作流里的坐标)、种类(着色用)、是否旁路 / 静音、标题。"""

    x: float
    y: float
    w: float
    h: float
    #: input / model / sampler / text / output / note / missing / other
    role: str = "other"
    muted: bool = False
    title: str = ""


class WorkflowGraphGroupOut(ApiModel):
    x: float
    y: float
    w: float
    h: float
    title: str = ""
    color: str = ""


class WorkflowGraphOut(ApiModel):
    """画缩略图用的图摘要。`links` 是节点下标对;`auto_layout`:图里没有位置(API 格式),位置是插件按依赖自动排的。"""

    nodes: list[WorkflowGraphNodeOut] = Field(default_factory=list)
    links: list[list[int]] = Field(default_factory=list)
    groups: list[WorkflowGraphGroupOut] = Field(default_factory=list)
    auto_layout: bool = False
    #: 节点太多,只画了前一部分
    truncated: bool = False


class WorkflowInputOut(ApiModel):
    """读素材的一格:哪个节点、读什么(image / video / audio)、在生成里当什么用(参考图、首帧……)。"""

    node: str = ""
    title: str = ""
    media: str = ""
    role: str = ""


class WorkflowParameterOut(ApiModel):
    key: str = ""
    title: str = ""
    type: str = ""


class WorkflowOutputOut(ApiModel):
    node: str = ""
    title: str = ""
    media: str = ""


class WorkflowModelRefOut(ApiModel):
    """它用到的一个模型文件,在不在这台服务器上。"""

    folder: str
    name: str
    present: bool = False


class WorkflowNodePackOut(ApiModel):
    """一个节点类型可能出自的节点包(ComfyUI-Manager 的映射)。"""

    id: str
    title: str = ""
    installed: bool = False


class WorkflowMissingNodeOut(ApiModel):
    type: str
    #: 图里有几个这种节点
    count: int = 1
    packs: list[WorkflowNodePackOut] = Field(default_factory=list)


class WorkflowMissingModelOut(ApiModel):
    """缺的、工作流声明了下载地址的模型。"""

    folder: str
    name: str
    url: str = ""


class WorkflowGenerationRefOut(ApiModel):
    """这张工作流在 Mosael 里是哪个生成模型(用它生成要它)。"""

    provider_profile_id: str
    kind: str
    model: str


class WorkflowLastOutputOut(ApiModel):
    asset_id: str
    created_at: datetime


class WorkflowUseOut(ApiModel):
    """Mosael 里选了它的一处:工作流(节点)或画板(格子)。"""

    kind: Literal["workflow", "board"]
    id: str
    name: str


class WorkflowFileOut(ApiModel):
    """那台服务器上存着的一张工作流。"""

    #: 相对 workflows/ 的路径(可带子目录,`/` 分隔)
    path: str
    label: str
    #: 子目录;在 workflows/ 根上是空串
    folder: str = ""
    size: int | None = None
    #: 秒
    modified: float | None = None
    #: image / video / audio;认不出(转不过来、只交出文字)是空串
    kind: str = ""
    #: 转不过来的原因;空串 = 没问题
    problem: str = ""
    node_count: int = 0
    graph: WorkflowGraphOut = Field(default_factory=WorkflowGraphOut)
    inputs: list[WorkflowInputOut] = Field(default_factory=list)
    parameters: list[WorkflowParameterOut] = Field(default_factory=list)
    outputs: list[WorkflowOutputOut] = Field(default_factory=list)
    models: list[WorkflowModelRefOut] = Field(default_factory=list)
    missing_nodes: list[WorkflowMissingNodeOut] = Field(default_factory=list)
    missing_models: list[WorkflowMissingModelOut] = Field(default_factory=list)
    generation: WorkflowGenerationRefOut | None = None
    #: 这个工作区里最近一次用它生成的产出
    last_output: WorkflowLastOutputOut | None = None
    #: 这个工作区里选了它的工作流节点、画板格子
    used_by: list[WorkflowUseOut] = Field(default_factory=list)


class WorkflowOtherFileOut(ApiModel):
    """workflows/ 里不是工作流的文件(拷进去的压缩包),和它为什么用不了。"""

    path: str
    reason: str = ""


class WorkflowTrashedOut(ApiModel):
    """回收目录里的一张(ADR 0035 §3)。"""

    path: str
    #: 原来在 workflows/ 里的相对路径
    original: str
    label: str
    deleted_at: float | None = None


class WorkflowManagerOut(ApiModel):
    #: ComfyUI-Manager 的版本;没装是空串
    version: str = ""


class WorkflowEditorOut(ApiModel):
    """「在编辑器里打开」开哪里:`kind` 决定界面怎么打开那一张(`comfyui`:桌面版在内嵌浏览器里经前端打开),`url` 是
    那台服务器的网页界面(只会是 http(s))。"""

    kind: str
    url: str


class WorkflowLibraryOut(ApiModel):
    workflows: list[WorkflowFileOut] = Field(default_factory=list)
    others: list[WorkflowOtherFileOut] = Field(default_factory=list)
    trash: list[WorkflowTrashedOut] = Field(default_factory=list)
    manager: WorkflowManagerOut = Field(default_factory=WorkflowManagerOut)
    #: 插件没报编辑器、或者报的不像样就没有 —— 界面不出「在编辑器里打开」
    editor: WorkflowEditorOut | None = None
    #: 这个连接最近的几次装节点包(在跑的总在里面)
    installs: list[JobOut] = Field(default_factory=list)


class WorkflowLibraryImportRequest(ApiModel):
    """要导入的东西,只给一样:一段文字(JSON 原文或一个链接)、一个文件(base64,带上文件名)、一个链接。"""

    text: str = ""
    data: str = ""
    filename: str = ""
    url: str = ""


class WorkflowLibraryImportOut(ApiModel):
    """导入前的预览:换成界面格式的那张图,和列出来的每一张同一套描述。"""

    #: 原来是界面格式还是 API 格式(API 格式没有布局,位置是自动排的)
    format: Literal["ui", "api"]
    #: 从哪儿认出来的:JSON 原文、PNG / WebP 里嵌的、压缩包里的、链接取回的
    source: Literal["json", "png", "webp", "zip", "url"]
    #: 要存进去的那张(界面格式,新的图 id)
    workflow: dict[str, Any]
    #: 插件建议的路径(不撞名);空 = 界面自己给一个
    suggested_path: str = ""
    #: 要告诉人的话(自动排的位置、压缩包里另外几张)
    notes: list[str] = Field(default_factory=list)
    kind: str = ""
    problem: str = ""
    node_count: int = 0
    graph: WorkflowGraphOut = Field(default_factory=WorkflowGraphOut)
    inputs: list[WorkflowInputOut] = Field(default_factory=list)
    parameters: list[WorkflowParameterOut] = Field(default_factory=list)
    outputs: list[WorkflowOutputOut] = Field(default_factory=list)
    models: list[WorkflowModelRefOut] = Field(default_factory=list)
    missing_nodes: list[WorkflowMissingNodeOut] = Field(default_factory=list)
    missing_models: list[WorkflowMissingModelOut] = Field(default_factory=list)


class WorkflowLibrarySaveRequest(ApiModel):
    path: str
    #: 界面格式的工作流
    content: dict[str, Any]


class WorkflowInstallNodesRequest(ApiModel):
    workspace_id: str
    #: 节点包:Manager 映射里的那个 id(registry 的包名,或只在 git 上的仓库地址)
    packs: list[str]


class WorkflowRebootOut(ApiModel):
    #: 等到它重新起来了
    back: bool


class WorkflowContentOut(ApiModel):
    path: str
    content: dict


class WorkflowCopyRequest(ApiModel):
    path: str = Field(min_length=1, max_length=500)
    new_path: str = Field(min_length=1, max_length=500)


class WorkflowRenameRequest(ApiModel):
    path: str = Field(min_length=1, max_length=500)
    new_path: str = Field(min_length=1, max_length=500)


class WorkflowTrashRequest(ApiModel):
    path: str = Field(min_length=1, max_length=500)


class WorkflowRestoreRequest(ApiModel):
    path: str = Field(min_length=1, max_length=600)
    #: 原处被占了时换的名字;不给就回原处
    new_path: str = Field(default="", max_length=500)


class WorkflowPathOut(ApiModel):
    """改完之后它在哪(复制、改名、恢复是 workflows/ 里的路径,删除是回收目录里的路径)。"""

    path: str
