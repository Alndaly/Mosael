"""AI 供应商:连接、凭据、模型、能力默认、配额与计价的出入参。"""

from __future__ import annotations

from datetime import datetime
from pydantic import Field, field_validator
from app.api.schemas.base import ApiModel, OrmModel

class ProviderModelOut(ApiModel):
    """一条连接下的一个模型 —— **已配置的行与供应商目录合并后的样子**。

    两个来源缺一不可:目录说"这个端点有什么"(会变),模型行说"我对它做过什么"(不该被目录
    冲掉)。所以这里同时带 `configured`(有没有行)和 `in_catalog`(目录里还在不在):
    目录有而没行 = 可一键加入;有行而目录没了 = 标出来但不删,别名与私有部署仍要能用。

    元数据取不到就留空:contextWindow 之类硬编一个默认值(曾经是 128000)会让配了小上下文的
    本地模型在真正请求时才被服务端拒绝。
    """

    id: str
    display_name: str = ""
    #: 该模型能干什么。为空表示跟随 vendor 预设(回填来的老行、以及还没细分过的连接)。
    capability_ids: list[str] = Field(default_factory=list)
    #: 生效能力(已回落 vendor 预设)。界面显示这个,而 capability_ids 是"用户填了什么"。
    effective_capability_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
    configured: bool = False
    in_catalog: bool = False
    source: str = "catalog"
    #: 用户填过的 / 目录给的窗口。为空 = 两边都没有,运行时按 effective_context_window 走。
    context_window: int | None = None
    context_window_source: str = "fallback"
    max_output_tokens: int | None = None
    max_output_tokens_source: str = "fallback"
    #: **运行时真正会用的那两个数**,包含回退。界面显示它们,而不是自己再算一份回退 ——
    #: 弹窗此前写死了 32000,而远程端点运行时用的是 128000:用户看到的数和请求带的数不是一个。
    effective_context_window: int = 0
    effective_max_output_tokens: int = 0
    reasoning: bool | None = None
    vision: bool | None = None
    reasoning_effort: bool | None = None
    developer_role: bool | None = None
    #: 生成参数按什么来 —— `model:<provider>/<model>` 或 `profile:<id>`,留空 = 跟随目录。
    generation_capability_ref: str | None = None
    #: 按生成类型分别声明。双能力模型不能让 image 与 video 共用一个引用。
    generation_capability_refs: dict[str, str] = Field(default_factory=dict)
    #: 这个模型的生成参数是**认出来的**还是落到兜底。界面据此分开"确实没有参数"和
    #: "我们不认识这个模型" —— 合成一个的话,后者会静默地什么都不显示。
    generation_capabilities_known: bool = True
    generation_capabilities_known_by_kind: dict[str, bool] = Field(default_factory=dict)


class ProviderModelUpdate(ApiModel):
    """模型行的增改。传 null 的运行时项表示**清除**、回到跟随目录/保守默认。"""

    model_id: str | None = Field(default=None, min_length=1, max_length=160)
    display_name: str | None = None
    capability_ids: list[str] | None = None
    enabled: bool | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    reasoning: bool | None = None
    vision: bool | None = None
    reasoning_effort: bool | None = None
    developer_role: bool | None = None
    generation_capability_ref: str | None = None
    generation_capability_refs: dict[str, str | None] | None = None


class GenerationCapabilityProfileOut(ApiModel):
    """一份用户自己写下的参数组。"""

    id: str
    name: str
    kind: str
    capabilities: dict = Field(default_factory=dict)
    #: 模型行上要存的那个值。前端不自己拼 —— 拼错了是一个解析不到的 ref。
    ref: str


class GenerationCapabilityProfileCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "image"
    capabilities: dict = Field(default_factory=dict)


class GenerationCapabilityProfileUpdate(ApiModel):
    """只改传了的那几项。kind 不给改 —— 要换就新建一份(见路由里的说明)。"""

    name: str | None = Field(default=None, max_length=120)
    capabilities: dict | None = None


class CapabilityProfileFieldOut(ApiModel):
    """可视表单的一个字段:键、形状、分组。分组是后端语义,前端只翻译标签。"""

    key: str
    shape: str
    group: str
    #: 这一格是**哪个参数**的默认值(`default_quality` → `quality`)。只有 defaults 组有。
    #: 界面据此决定"这个旋钮要不要有一格默认值",而不是自己攒一张名单。
    defaults_for: str | None = None


class CapabilityProfileSchemaOut(ApiModel):
    """参数组可视表单的结构描述 —— 表单唯一的事实源(见 domain/generation/custom_profiles.py)。"""

    parameters: list[str]
    enum_parameters: list[str]
    source_roles: list[str]
    #: 参数 → 装它可选值的那个键。不在这里的枚举参数,取值装在 parameter_choices 里。
    choices_key: dict[str, str]
    fields: list[CapabilityProfileFieldOut]


class OAuthPromptOut(ApiModel):
    """登录流程中需要用户作答的一步(输入授权码、选账号……)。"""

    prompt_id: str
    prompt_type: str = "text"
    message: str = ""
    placeholder: str = ""
    options: list[dict] = Field(default_factory=list)


class OAuthLoginOut(ApiModel):
    """一次登录的当前状态。前端轮询它,拿到什么就展示什么。"""

    login_id: str
    status: str  # running | done | error | cancelled
    #: pi 的 AuthEvent 原样透传(auth_url / device_code / progress / info)。
    #: 刻意不翻译成自定义结构:上游加一种事件时,前端至少还能拿到原文而不是空白。
    events: list[dict] = Field(default_factory=list)
    prompt: OAuthPromptOut | None = None
    error: str = ""
    models: list[ProviderModelOut] = Field(default_factory=list)


class ProviderHealthOut(ApiModel):
    """一次探活的结果。`supported=False` 表示这类档案没法探(订阅计划没有我们持有的端点),
    界面据此整列不显示,而不是显示一个假的"离线"。"""

    supported: bool
    online: bool = False
    latency_ms: int | None = None
    detail: str = ""


class ProviderQuotaMetricOut(ApiModel):
    """一条额度指标。

    各家的额度类型和周期对不齐,所以不压成单一数字:每条指标自带 kind(百分比 / 余额)、
    周期长度与重置时间,怎么展示交给前端。硬归一要么丢信息,要么得为它编一个不存在的分母。
    """

    key: str
    kind: str  # percent | balance
    used_percent: float | None = None
    used: float | None = None
    limit: float | None = None
    unit: str | None = None
    window_seconds: int | None = None
    resets_at: str | None = None
    unlimited: bool = False


class ProviderQuotaOut(ApiModel):
    """一次额度查询的结果。

    `supported=False` 与 `error` 是两回事:前者是这家压根没有可查的端点(界面该说"不支持"),
    后者是这次没查成(界面该说原因并允许重试)。混成一个会让"查不了"和"查失败"长一样。
    """

    supported: bool
    plan: str | None = None
    metrics: list[ProviderQuotaMetricOut] = Field(default_factory=list)
    fetched_at: float | None = None
    error: str = ""


class PricingPrefillOut(ApiModel):
    """按模型目录预填计价规则的结果。三个数分开报,是为了让「一条没建」可解释:
    是目录本身没报价(多数 OpenAI 兼容端点如此),还是规则早就配齐了。"""

    #: 本次新建的规则条数。
    created: int
    #: 目录里带报价的模型数。
    models_with_price: int
    #: 目录里的模型总数。
    models_seen: int


class OAuthAnswerIn(ApiModel):
    prompt_id: str
    answer: str


class ProviderCredentialIn(ApiModel):
    """我在某条连接上的钥匙。"""

    api_key: str | None = None
    #: ProviderDefinition 里标了 secret 而不落 api_key 的那几个(火山 ak/sk、快手 secret_key)。
    secrets: dict[str, str] = Field(default_factory=dict)


class ProviderCredentialOut(ApiModel):
    profile_id: str
    key_hint: str = ""
    is_mine: bool = True


class ProviderProfileCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    vendor: str = Field(min_length=1, max_length=60)
    #: Adapter-specific form values, keyed by VendorFieldOut.key.
    config: dict[str, str] = Field(default_factory=dict)
    #: 服务端从既有档案复制 secret 字段(如同一把方舟 Key 配到另一能力的独立档案),
    #: 密钥全程不出后端、不下发前端。仅在本档案未显式提供该字段时生效。
    copy_credentials_from: str | None = None
    #: 鉴权方式("oauth" / "api_key");不传则取该 vendor 的默认(见 default_auth_type)。
    #: 非该 vendor 支持的值会被收敛掉,而不是报错——UI 只会给出支持的选项。
    auth_type: str | None = None


class ProviderProfileUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    #: Adapter-specific form values, keyed by VendorFieldOut.key.
    config: dict[str, str] | None = None
    enabled: bool | None = None
    auth_type: str | None = None


class VendorFieldOut(ApiModel):
    """One adapter-specific setting the form should collect."""

    key: str
    label: str
    storage: str = "extra"
    secret: bool = False
    required: bool = False
    default: str = ""
    hint: str = ""
    #: 长文本字段(如 ComfyUI 工作流模板 JSON)渲染为多行输入
    multiline: bool = False


class ProviderProfileOut(OrmModel):
    id: str
    name: str
    vendor: str
    capability_ids: list[str] = Field(default_factory=list)
    base_url: str
    enabled: bool
    created_at: datetime
    #: **我自己**那把钥匙的尾四位(订阅计划是「已登录」)。别人的钥匙这里一律为空 ——
    #: 连尾数都不该露(见 domain/provider_credentials)。
    key_hint: str = ""
    #: 我在这条连接上配过自己的钥匙吗。没配 → 这条连接对我不可用,界面直说。
    is_mine: bool = False
    #: 这家供应商**要不要钥匙**。免密钥的(本机 ComfyUI)为 False —— 界面据此决定要不要显示
    #: 那行「未配置你的密钥」。判据由后端给:前端按 vendor 名字硬编,下一个免密钥的 vendor
    #: 加进来时没有任何东西会提醒你。
    needs_key: bool = True
    #: Non-secret extras come back verbatim; secret ones only as "…abcd", never in full —
    #: same rule as api_key/key_hint.
    extra: dict[str, str] = Field(default_factory=dict)
    #: Masked, adapter-shaped config for the settings form; secret fields are hints only.
    config: dict[str, str] = Field(default_factory=dict)
    auth_type: str = "api_key"
    #: OAuth 档案是否已登录。**只回布尔**,令牌本身任何接口都不下发。
    oauth_linked: bool = False
    #: 这家有没有可查的额度接口。前端据此决定要不要摆「查询额度」——不给这个字段的话,
    #: 按钮会对着 Kimi/xAI 这类没有端点的供应商也亮着,点下去只能回一句"不支持",
    #: 等于摆了个做不到的操作。
    quota_supported: bool = False
    #: access token 是否已过期。`oauth_linked` 只说"存过凭据",不说"现在有效" —— 两者分开,
    #: 卡片才能把「已授权但令牌过期」如实说出来,而不是让用户看着"已授权"却处处碰壁。
    #: 过期不等于要重新授权:下次对话时 pi 会自动刷新(见 domain/provider_quota 的注释)。
    oauth_expired: bool = False

    #: ORM 列 capability_ids 可为 None(=沿用 vendor 默认);model_validate 时先归一成 []。
    #: 路由 _profile_out 随后会覆写成实际生效能力(effective_capability_ids)。
    @field_validator("capability_ids", mode="before")
    @classmethod
    def _caps_none_to_list(cls, value: object) -> object:
        return value if value is not None else []


class ProviderDefaultOut(ApiModel):
    capability: str
    provider_profile_id: str | None = None
    model: str = ""
    #: 这是我自己设的,还是部署给的起点(见 db.models.ProviderDefault)。界面据此区分,
    #: 否则"我没设过却有值"看着像 bug。
    is_mine: bool = False


class CapabilityModelOut(ApiModel):
    """某能力下的一个候选模型(跨连接)。

    界面直接列它 —— 一个模型现在自带能力与连接,"先选供应商再选模型"那两级下拉是模型还不是
    实体时的形状:它逼着用户先知道"这个模型在哪条连接下",而那恰恰是他不关心的。
    """

    provider_profile_id: str
    provider_name: str
    model: str
    display_name: str = ""
    #: 这个模型会不会思考。False = 完全不支持,界面上就不该出现思考档位这个控件。
    #: None = 还没探明(端点没报、用户没细分过),按"可能会"处理 —— 少一个档位比多一个更坏。
    reasoning: bool | None = None
    #: 能不能**分档**(low/medium/high)。False/None 而 reasoning 为真 = 只能开/关。
    reasoning_effort: bool | None = None
    #: 这个模型**真正发得出去**的思考档位(见 domain/thinking)。空 = 一档都发不出,
    #: 界面据此说"这条连接发不出思考档位",而不是摆四个做同一件事的选项。
    #: 这和上面两个字段是两回事:那两个说"这个模型会不会思考、能不能分档",
    #: 这个说"**我们**能不能把话传过去"。Kimi k3 会思考、也分档,但关不掉。
    thinking_levels: list[str] = []


class ProviderDefaultUpdate(ApiModel):
    provider_profile_id: str | None = None
    model: str = Field(default="", max_length=120)


class ProviderPricingRuleCreate(ApiModel):
    workspace_id: str | None = None
    provider_profile_id: str | None = None
    provider: str = Field(default="", max_length=80)
    capability: str = Field(min_length=1, max_length=40)
    model: str = Field(default="", max_length=120)
    billing_unit: str = Field(min_length=1, max_length=40)
    unit_amount_micros: int = Field(ge=0)
    currency: str = Field(default="USD", min_length=1, max_length=8)
    source: str = Field(default="manual", max_length=40)
    notes: str = Field(default="", max_length=2000)
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ProviderPricingRuleUpdate(ApiModel):
    workspace_id: str | None = None
    provider_profile_id: str | None = None
    provider: str | None = Field(default=None, max_length=80)
    capability: str | None = Field(default=None, min_length=1, max_length=40)
    model: str | None = Field(default=None, max_length=120)
    billing_unit: str | None = Field(default=None, min_length=1, max_length=40)
    unit_amount_micros: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    source: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ProviderPricingRuleOut(OrmModel):
    id: str
    workspace_id: str | None = None
    provider_profile_id: str | None = None
    provider: str
    capability: str
    model: str
    billing_unit: str
    unit_amount_micros: int
    currency: str
    source: str
    notes: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProviderUsageEventOut(OrmModel):
    id: str
    workspace_id: str
    provider_profile_id: str | None = None
    provider: str
    model: str
    capability: str
    operation: str
    source_type: str
    source_id: str
    job_id: str | None = None
    agent_message_id: str | None = None
    status: str
    duration_seconds: float | None = None
    units: dict
    raw_usage: dict
    cost_micros: int | None = None
    currency: str
    cost_confidence: str
    pricing_rule_id: str | None = None
    created_at: datetime


class VendorPresetOut(ApiModel):
    vendor: str
    label: str
    capability_ids: list[str] = Field(default_factory=list)
    base_url: str = ""
    default_model: str = ""
    capabilities: str = ""
    #: Adapter-specific configuration inputs. The form renders these, so adding a vendor stays
    #: a one-dict-entry change.
    fields: list[VendorFieldOut] = Field(default_factory=list)
    #: 支持的鉴权方式,顺序即优先级。含 "oauth" 的档案表单渲染「登录」而不是密钥输入框。
    auth: list[str] = Field(default_factory=lambda: ["api_key"])
