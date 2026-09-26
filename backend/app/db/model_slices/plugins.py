"""插件:包、接入实例、它暴露哪些工具、授了哪些权限、凭据,以及每次调用的留痕。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.core.secrets_at_rest import EncryptedText
from app.db.model_base import new_id, now

class PluginPackage(Base):
    """磁盘上的一个插件目录 + 它的 manifest。**没有「启用」状态** —— 启用的是实例。

    包与实例分开,是因为一个包可以被接入多次:TikHub 一个包对应十几个平台端点,B站一个
    实例、抖音一个实例,各有各的凭据和显示名。此前包和接入是同一行记录,于是"平台"只能
    是一个凭据,而包名写死在 manifest 里 —— 用户配了 bilibili,面板上仍然写着「抖音」。
    """

    __tablename__ = "plugin_packages"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PluginMarketHold(Base):
    """市场许了一个新版,点「更新」下下来的却不比装着的新 —— 记下来,市场先别再说「有新版」。

    索引说 0.2.0、下载地址给的还是 0.1.0 时,「更新」装回的是同一版,而索引照旧说 0.2.0:
    「有新版」永远不消失,用户点多少次都一样(见 domain/plugins/updates)。

    **记的是「这一份索引的这一条」**:索引许的版本 + 它给的下载地址。两样任何一样变了(发了新版、
    索引换了地址),这条就不再算数,市场照常比版本;装上任何一版也清掉它。另有一个时限兜底 ——
    自己架的索引可能一直用同一个地址,而那个地址背后的包迟早会换成真正的新版。
    """

    __tablename__ = "plugin_market_holds"

    package_id: Mapped[str] = mapped_column(ForeignKey("plugin_packages.id", ondelete="CASCADE"), primary_key=True)
    #: 索引里写的版本(许诺的那一版)。
    advertised_version: Mapped[str] = mapped_column(String(40), nullable=False)
    #: 索引里给的下载地址。
    download: Mapped[str] = mapped_column(String(1000), nullable=False)
    #: 那个地址实际给的包里,清单写的版本。
    served_version: Mapped[str] = mapped_column(String(40), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class PluginInstance(Base):
    """一次具体接入:包 + 一组配置 + 一个显示名 + 启用开关。凭据与授权都挂在这里。

    显示名默认由包的 name_template 从配置生成(「TikHub · 哔哩哔哩」),用户可以改。
    """

    __tablename__ = "plugin_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 谁接的。**包是这台机器装了什么(部署级),接入是某个人用他的账号连上了它。**
    #: 此前整份都是部署级:管理员配一次,所有人的智能体共用那一把第三方密钥 —— 于是用量算不到
    #: 人头上,而新账号一进插件页就看到别人接好的一排。和供应商连接同一条(见 ProviderProfile)。
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("plugin_packages.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: 明文配置(枚举 / 文本 / 数字 / 开关)。凭据不在这里 —— 那是 PluginCredential。
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: MCP 实例的工具清单从服务现拉,缓存在这里(进程类插件写在 manifest 里,此列为空)。
    discovered_tools: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: 这个实例替宿主做的那些事(`provides`)**上一次做得怎么样**:按能力分,
    #: `{"generation": {"models": 12, "refreshed_at": "…", "error": ""}}`。插件页据此说
    #: 「12 个生成模型 · 刚刷新」或者「连不上服务器:…」—— 目录刷新发生在后台(启动、改配置),
    #: 失败了不记下来的话,用户只会看到选择器里少了东西,不知道为什么。
    capability_status: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: 插件上一次调用时说「对方不再接受已存的令牌」(失败响应里的 `reauthorize: true`)是什么时候。
    #: 插件页据此把这个连接标成「需要重新授权」。重新授权、或手动改了授权写的那几格凭据、或之后
    #: 一次调用成功了,就清掉 —— 见 domain/plugins/instances 的 note_authorization。
    #: 只有声明了 `instance.oauth` 的插件才会记。
    authorization_rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginCapability(Base):
    """这个实例的某个工具暴不暴露给智能体和工作流。**默认不暴露**。

    一个 MCP 端点报几十上百个工具(TikHub 的 bilibili 报了 41 个)。全量涌进节点面板和
    智能体工具表,面板要人从四十行里找一行,工具表让每轮对话为四十条描述付 token 并挤占
    模型在内置工具之间的选择权。要人从四十个里挑出该关的三十七个,没有人会做 ——
    默认值就是实际行为,所以默认关,由 manifest 的 recommended 给一个起点。
    """

    __tablename__ = "plugin_capabilities"

    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(160), primary_key=True)
    exposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PluginPermissionGrant(Base):
    __tablename__ = "plugin_permission_grants"

    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(120), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginCredential(Base):
    """一个实例自己的凭据(API Key 等),按 manifest 的 `credentials` 声明逐条存。

    **为什么插件不能共用应用的供应商凭据**:插件运行时只向子进程透传 PATH/HOME/LANG,
    刻意不给任何应用凭据——插件因此绕不过确认卡和权限系统。但"什么都不给"也意味着任何
    需要 API Key 的插件只能自己在插件目录里放一个 config.json,让用户开终端去 cp 文件。
    这张表是那个缺口的补丁:**只把该实例自己声明的那几个键**注入它自己的进程环境。

    落盘加密,和 provider_credentials 一致(见 core/secrets_at_rest)—— 主密钥取环境变量,
    取不到才落到数据目录里那个 0600 文件。后一种情况下整个数据目录被一起拷走时加密不起作用,
    这一点如实降级,不假装解决了。

    **归属和 provider_credentials 不一样**:这把钥匙挂在**实例**上,不挂在人身上。插件实例本身
    就是部署级配置(增删改全在 ensure_deployment_admin 后面),所以它的钥匙是这个部署的钥匙 ——
    任何成员的智能体调这个插件工具时,用的都是管理员配的那一把。这是有意的:插件是"这台部署
    装了什么",不是"我是谁";但它确实意味着**用量算不到人头上**,和供应商调用不同。
    """

    __tablename__ = "plugin_credentials"

    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginInvocation(Base):
    __tablename__ = "plugin_invocations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class PluginCapabilityDefault(Base):
    """某个人把哪一个插件实例定为某项能力的默认 —— 今天只有 `public_url`(素材外链)。

    **一个人配了几家对象存储时,用哪一家必须由他说了算。** 此前按实例名的字母序取第一个:
    谁被用上取决于它叫什么,而排第一的那个没配好时整条生成直接报错,不会换到配好的那一家。

    在「设置 → 素材外链」里定。按人分:存储实例本来就是个人的
    (PluginInstance.owner_user_id),默认当然也是。实例删掉时
    这一条跟着删(外键级联),不会留下一个指向不存在实例的「默认」。
    """

    __tablename__ = "plugin_capability_defaults"

    owner_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capability: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginPublicLink(Base):
    """传到对象存储后拿到的那条**限时直链**,按(素材, 存储实例)记住。

    同一份参考视频点两次生成,此前就传两次 —— 最大 200MB 的文件,每次都重新上传。链接还在
    有效期内就直接用;快到期(留一小时余量,供应商在提交时取文件)才重传。
    """

    __tablename__ = "plugin_public_links"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
