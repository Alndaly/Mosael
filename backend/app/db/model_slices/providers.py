"""AI 供应商的接入:连接、凭据、模型,以及每种能力默认用谁。

凭据归人不归工作区(见 ADR 0008):同一个连接,每个人填自己的 key,谁的账单记在谁头上。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.core.secrets_at_rest import EncryptedJSON, EncryptedText
from app.db.model_base import new_id, now

class ProviderProfile(Base):
    """某个人配的一条供应商连接。同一家可以配多条(两个 OpenAI 兼容端点、两把 key)。

    **归建它的那个人。** 曾经是部署级的:任何登录用户都看得见全部连接,而只有部署管理员建得了、
    改得了。理由写的是"怎么连到这家供应商是部署的配置" —— 那在单人机器上成立,在多租户产品里
    不成立,而这个应用是后者。

    代价跑出来过:新账号一进设置页就看到八条别人建的连接,每条底下一行红字「未配置你的密钥」——
    看得见、用不了、也建不了自己的。端点泄露也是同一个根(别人的私有部署地址印在他的列表里),
    当时是遮住地址,那只是打补丁。

    现在钥匙和连接归同一个人,所以它们其实是一件事的两半;ProviderCredential 仍然单独一张表,
    因为它装的是 oauth 令牌、模型目录这些**会变**的东西,而连接是用户填的那份配置。
    """

    __tablename__ = "provider_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 谁的。不设外键、也不做级联:账号删除走 domain/members.delete_account 那条统一的路
    #: (它按 schema 扫所有指向人的列),FK 在这里只会多一种删不掉账号的失败方式。
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor: Mapped[str] = mapped_column(String(60), nullable=False)  # alibaba|bytedance|openai|moonshot|minimax|openai-compatible|...
    base_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    #: 鉴权方式。"api_key" = 每个人自己的那把(见 ProviderCredential);"oauth" = 订阅计划
    #: (Claude Pro/Max、Kimi Code 等),密钥同样按人存。哪些方式可用由 ProviderDefinition 声明。
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="api_key")
    #: 这条连接的**非密**附加配置(区域、端点变体等)。密的那几个(火山 ak/sk、快手 secret_key)
    #: 跟着钥匙走,存在 ProviderCredential.secrets 里 —— 哪些字段是密的由 ProviderDefinition 的
    #: `secret: True` 声明,而那也正是渲染表单的同一份声明。
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: 这条连接**是一个插件实例**(提供生成能力的插件,见 ADR 0020)。有值时 vendor 是
    #: `plugin:<包 id>`,配置与凭据都在那个实例上 —— 这一行只是生成领域指向它的把手
    #: (模型、默认模型、生成历史、用量的外键都挂在连接上)。实例删掉,连接跟着删。
    plugin_instance_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("plugin_instances.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderCredential(Base):
    """某个人在某条连接上的钥匙。

    **为什么钥匙不能待在 ProviderProfile 上**:那张表回答的是「怎么连到这家供应商」——
    端点、模型目录、定价规则,那是部署的配置,由部署管理员维护。而钥匙回答的是「谁在花钱、
    以谁的身份调用」。压在一起的后果跑出来过:能发起一轮对话的人就能 acquire 到那份明文
    凭据,而普通成员又没法带自己的钥匙 —— 订阅制账号(Claude Pro/Max)被多人共用,供应商
    那边看到的是同一个账号。

    **没有"共享钥匙"这回事**:每个人配自己的。曾经有过一个 `shared` 位,是为了让升级无缝 ——
    但它没有任何界面(等于隐藏状态),而且和这张表存在的理由自相矛盾:钥匙归人,正是为了不再
    「所有人共用一把、花的是同一个人的钱」。
    """

    __tablename__ = "provider_credentials"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    api_key: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="", server_default="")
    #: pi 的 Credential **原样**存放({type, access, refresh, expires, ...})。刻意不拆成列:
    #: 各家 OAuth 的附加字段(Copilot 的 endpoint、Codex 的 account_id)由 pi 自己解释,
    #: 这边拆一次就等于把各家协议复制进 Python,下次上游加字段就悄悄丢了。
    oauth_credential: Mapped[dict | None] = mapped_column(EncryptedJSON, nullable=True, default=None)
    #: ProviderDefinition 里标了 `secret: True` 而又不落 api_key 的那几个(火山 ak/sk、快手 secret_key)。
    secrets: Mapped[dict] = mapped_column(EncryptedJSON, nullable=False, default=dict, server_default="{}")
    #: 订阅计划登录后拿到的可用模型目录([{id, name, contextWindow, maxTokens}])。跟着钥匙走:
    #: 它是**这次登录**的结果 —— Copilot 的模型随订阅档位变,两个人的订阅目录可以不一样。
    model_catalog: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    #: 乐观并发版本号。多个会话可以同时开对话,各自 spawn 一个 sidecar;若两个同时刷新
    #: 同一份 OAuth 凭据,后写的会把已被服务端轮换作废的 refresh token 覆盖回去 ——
    #: 表现为用户莫名其妙被登出。写入时带上读到的版本,不匹配就拒绝(见 credentials 路由)。
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderModel(Base):
    """一条连接下的一个模型。

    **为什么模型必须是一等实体**:此前「档案」的粒度是不一致的 —— 有的是一条连接(一个端点
    多个模型),有的其实是一个模型(用户拿模型名当档案名建了 gpt-image-2、火山seedream)。
    用户被迫这样,是因为能力挂在档案上、而档案只有一个 default_model:想用同一个端点的两个
    模型做两件事,就只能建两个档案。

    能力下沉到模型这一层之后,一条连接可以同时提供对话模型和生图模型,「某能力的默认模型」
    也才有东西可指 —— ProviderDefault 早就是 (capability → profile + model) 的形状,
    只是没有模型实体可以引用。

    **表里存的是"已配置的模型",不是模型全集**。供应商目录仍是发现来源(见 ai.model_catalog
    与订阅计划的 model_catalog),界面把两者合并展示:目录有而这里没有 = 未配置,可一键加入;
    这里有而目录没了 = 标记"目录中已不存在"但不删,别名与私有部署仍要能用。
    """

    __tablename__ = "provider_models"
    __table_args__ = (
        # 同一条连接下模型 id 唯一 —— 否则"哪一行是这个模型"就没有答案了。
        UniqueConstraint("provider_profile_id", "model_id", name="uq_provider_models_profile_model"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider_profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 发给供应商的模型标识,原样。
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    #: 展示名。留空即用 model_id —— 大多数情况下模型 id 本身就是最好的名字。
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    #: 这个模型能干什么(chat / image / video / tts / podcast)。**能力在模型上而不是连接上**:
    #: 同一个端点既有对话模型也有生图模型,挂在连接上就只能二选一。
    capability_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 停用的模型不出现在任何选择器里。OpenRouter 几百个模型全铺进下拉是不可用的。
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: catalog = 来自供应商目录;manual = 用户手填(私有部署、别名,目录里查不到)。
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="catalog")

    #: 以下是"我对这个模型做过什么"。**留空表示跟随目录/保守默认**,不是 0/False ——
    #: 两者混淆会让"没设过"被当成"显式设成了关"。
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    #: 都对应 pi 里真实生效的开关(思考格式 / 图片输入 / reasoning_effort / developer 角色)。
    reasoning: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    vision: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    reasoning_effort: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    developer_role: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    #: 这个端点能不能把 JSON Schema 当成**生成时的硬约束**(见 domain/structured_output)。
    #: 留空 = 跟随查证过的结论;查不到就维持现状(照发,被拒了由网关降级)。
    structured_output: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    #: 生成参数(尺寸/时长/参考图…)**按什么来**。上面那几格都是对话模型的开关,生成模型此前一格
    #: 都没有 —— 于是用户明知道自己那行 `gpt-image-2-client` 就是 gpt-image-2、明知道某个中转的
    #: gemini 支持尺寸,却没有任何地方写得下来,只能等我们往静态目录里补一行。
    #:
    #: 两种写法,一个概念(解析见 domain/generation/catalog.resolve_capability_ref):
    #:   `model:openai-compatible/gpt-image-2`  「它和 X 一样」——**跟着 X 的更新走**
    #:   `profile:openai-image`                 目录里没有对应模型时,直接指一份能力档案
    #:
    #: 留空 = 跟随目录,和旁边几格同一个约定。**它不参与"猜"**:要么目录认得这个模型,要么
    #: 用户在这里说了,两者都没有就落到兜底(什么参数都不声明),界面据此说"还没认出来"。
    generation_capability_ref: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    #: **连接自己声明的**生成参数描述符,按 kind 分(`{"image": {...}}`)。今天只有插件连接写它:
    #: 插件在目录里说出每个模型收什么(ComfyUI 的每张工作流各有各的采样器、步数、参考图槽位),
    #: 刷新目录时落到这里(见 domain/generation/plugin_connections)。解析顺序:用户声明 → 它 →
    #: 内置目录 → 兜底(见 domain/generation/resolution)。留空 = 连接什么都没说。
    declared_capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    #: 解析一个模型时几乎总要同时拿到端点与凭据 —— 它们在连接上。
    profile: Mapped["ProviderProfile"] = relationship(lazy="joined")


class GenerationCapabilityProfile(Base):
    """用户自己写下的一份「这个端点接受什么参数」。

    **为什么需要**:生成参数来自一张静态目录,按 (provider, model, kind) 精确查。那张表装的是
    我们查证过的东西,而中转端点的组合是装不完的 —— 同一个 gemini 经两家中转,一家支持尺寸和
    多张、另一家只支持尺寸。指向内置那份会**过度承诺**:界面摆出一个「张数」旋钮,发出去被拒。

    **归连接**,不归人也不归部署:它描述的就是「这条连接后面那个端点接受什么」,和连接同生共死
    (删连接一起清,不会留下指向虚空的孤儿)。连接本来就是按人的 —— 归属这件事跟着它走就够了,
    不必再发明一层。

    **它不是"我们查证过的事实"**,是用户的断言。所以界面上要和内置目录区分开:填错了不会当场
    报错,而是等到生成请求被供应商拒掉 —— 这个代价由填的人承担,前提是他知道自己在断言。
    """

    __tablename__ = "generation_capability_profiles"
    __table_args__ = (
        # 同一条连接下名字唯一 —— 选择器里两个同名的档案,选哪个都说不清。
        UniqueConstraint("provider_profile_id", "name", name="uq_generation_profiles_profile_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider_profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 给人看的名字。它会出现在「参数按什么来」那个下拉里。
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: image / video。**一份档案只服务一种** —— 图片的尺寸清单套到视频上是另一套东西。
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 描述符本身,和内置目录里那几十份同形(parameter_keys / sizes / durations / source_limits…)。
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class GenerationCapabilityDeclaration(Base):
    """一行模型在一种生成能力下，参数契约从哪里来。

    声明按 ``(provider_model_id, kind)`` 唯一。图片和视频必须分开：同一个模型行可以同时拥有
    image / video 能力，但两者的尺寸、时长和素材角色没有可复用的默认关系。

    ``catalog_ref`` 指向代码目录里的已知模型或命名契约；``template_id`` 指向这条连接下用户写的
    参数模板。两者只会有一个，空行没有意义，因此“跟随目录”用没有声明行来表达。
    """

    __tablename__ = "generation_capability_declarations"
    __table_args__ = (
        UniqueConstraint(
            "provider_model_id", "kind", name="uq_generation_declarations_model_kind"
        ),
        CheckConstraint(
            "(catalog_ref IS NOT NULL AND template_id IS NULL) OR "
            "(catalog_ref IS NULL AND template_id IS NOT NULL)",
            name="ck_generation_declarations_one_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider_model_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("provider_models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    catalog_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("generation_capability_profiles.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderDefault(Base):
    """某个人在某种能力下默认用哪个模型。

    capability:chat / image / video / tts / podcast。用到该能力且未显式指定时取此默认。

    **默认模型是个人偏好,不是部署配置**:同一条连接,两个人完全可以各自默认不同的模型。此前它
    只按 capability 建行、且要部署管理员才能改 —— 那是把「钥匙归人」那把尺子没量到底(ADR 0008
    D3 的同一条道理)。

    **没有"部署默认"这一档。** 曾经有过一行 `owner_user_id=""` 当作"还没设过的人的起点",
    删掉了(见 domain/provider_defaults.get_row):它看起来温和 —— 只在你没设时生效 —— 但造成的
    正是这个应用里反复出现的那种误解:界面上你没选过任何模型,回答却来自某个你不知道的模型,
    花的是你的额度、用的是你的钥匙。没设就说没设。

    `owner_user_id` 用空串而不是 NULL 作默认值,是因为 SQLite 允许 PRIMARY KEY 列为 NULL ——
    那会让同一个人的同一项能力可以重复插入而不报错。
    """

    __tablename__ = "provider_defaults"

    capability: Mapped[str] = mapped_column(String(24), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="", server_default="")
    #: 指向具体的模型行 —— 一件事只存一处。此前这里还并存着 (provider_profile_id, model)
    #: 那一对:模型还不是实体时的写法。两份会漂移的真相里总有一份是错的,已删。
    provider_model_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_models.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
