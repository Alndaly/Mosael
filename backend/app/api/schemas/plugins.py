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
    type: str = "string"  # string | enum | number | boolean
    help: str = ""
    required: bool = True
    secret: bool = False
    options: list[dict] = Field(default_factory=list)
    default: str = ""


class PluginToolStateOut(ApiModel):
    name: str
    label: str = ""
    description: str = ""
    read_only: bool = False
    input_schema: dict = Field(default_factory=dict)
    #: 暴不暴露给智能体与工作流。默认关 —— 一个 MCP 端点可能报几十个工具。
    exposed: bool = False


class PluginInstanceOut(ApiModel):
    id: str
    package_id: str
    name: str
    enabled: bool
    config: dict = Field(default_factory=dict)
    #: 为什么还不能用(未启用 / 缺配置 / 缺凭据 / 未授权)。空串 = 可用。
    blocked_reason: str = ""
    tools: list[PluginToolStateOut] = Field(default_factory=list)


class PluginPackageOut(ApiModel):
    id: str
    name: str
    version: str
    kind: str = "process"  # process | mcp
    multiple: bool = False
    permissions: list[str] = Field(default_factory=list)
    #: 插件自己的文档/主页。空 = 作者没写,界面就不画那个链接。
    homepage: str = ""
    config_fields: list[PluginFieldOut] = Field(default_factory=list)
    credential_fields: list[PluginFieldOut] = Field(default_factory=list)
    #: 这个插件能不能自己走 OAuth。界面据此决定要不要给「去授权」。
    oauth: bool = False
    instances: list[PluginInstanceOut] = Field(default_factory=list)


class PluginMarketEntry(ApiModel):
    """市场里的一条。索引给什么就是什么 —— 不做补全,免得看起来比实际更可信。"""

    id: str
    name: str = ""
    description: str = ""
    version: str = ""
    author: str = ""
    homepage: str = ""
    download: str = ""
    permissions: list[str] = Field(default_factory=list)
    #: 这台机器上装没装过同 id 的包。装过的话界面给的是「更新」而不是「安装」。
    installed: bool = False
    installed_version: str = ""


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
