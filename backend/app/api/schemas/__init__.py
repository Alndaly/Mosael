from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.providers.contracts.generation import FIRST_FRAME, SOURCE_ROLES
from app.api.schemas.base import OrmModel
from app.api.schemas.browser import BrowserProfileCreate, BrowserProfileOut, BrowserProfileUpdate
from app.api.schemas.jobs import JobOut, TaskEventOut
from app.api.schemas.publish import (
    PublishAccountCreate,
    PublishAccountOut,
    PublishAccountUpdate,
    PublishCopyRequest,
    PublishCopyResponse,
    PublishCreate,
    PublishOptionChoice,
    PublishOptionSpec,
    PublishPlatformOut,
    PublishTaskOut,
)

class AuthCredentials(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=4, max_length=200)


class RegisterCredentials(AuthCredentials):
    display_name: str = Field(default="", max_length=120)
    #: 进这个部署的邀请码。空库的第一个账号不需要;开放注册的部署也不需要。
    invite_code: str = Field(default="", max_length=64)


class DeploymentAdminUpdate(BaseModel):
    granted: bool


class InviteCreate(BaseModel):
    note: str = Field(default="", max_length=120)


class UserOut(OrmModel):
    id: str
    username: str
    display_name: str
    signature: str
    #: 空 = 未设置头像;非空时前端以 /api/auth/users/{id}/avatar?v=<key> 取图并借 key 破缓存。
    avatar_key: str = ""
    #: 这个部署的管理员(见 core/permissions.ensure_deployment_admin)。界面据此决定要不要
    #: 摆出「部署」那一块、以及能不能把一把钥匙共享给全员。
    is_deployment_admin: bool = False


class AdminUserOut(BaseModel):
    """管理员看到的一个人。"""

    id: str
    username: str
    display_name: str
    is_deployment_admin: bool
    created_at: datetime
    #: 最近一次用到这个部署。空 = 从没登录过(或老会话还没记过)。
    last_seen_at: datetime | None = None
    #: 他现在跑的客户端版本。**由客户端自报**,空 = 那个客户端不报(老版本)——
    #: 空着而不是编一个,"不知道"和"0.0.0"是两回事。
    client_version: str = ""
    workspaces: int = 0


class DaySeriesPoint(BaseModel):
    day: str
    total: int = 0
    failed: int = 0


class UserSpendPoint(BaseModel):
    user_id: str = ""
    username: str = ""
    cost_micros: int = 0
    calls: int = 0


class AdminOverviewOut(BaseModel):
    users: int = 0
    active_users_7d: int = 0
    workspaces: int = 0
    assets: int = 0
    jobs_by_day: list[DaySeriesPoint] = Field(default_factory=list)
    spend_by_user: list[UserSpendPoint] = Field(default_factory=list)
    #: 金额的币种。此前没有这一栏,界面只好硬写 ¥ —— 一个按 USD 计价的部署会看到人民币符号。
    currency: str = "USD"
    window_days: int = 30


class BootstrapOut(BaseModel):
    """登录页开屏问的两件事(见 routes/auth.bootstrap)。不需要登录就能读。"""

    #: 这个部署里已经有账号了吗。没有 → 界面进「创建管理员账户」。
    has_users: bool = False
    #: 收不收自助注册。不收时注册要邀请码,界面才摆那个框。
    open_registration: bool = True


class AuthOut(BaseModel):
    token: str
    user: UserOut


class UserProfileUpdate(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    signature: str = Field(default="", max_length=500)


class PasswordUpdate(BaseModel):
    current_password: str = Field(min_length=4, max_length=200)
    new_password: str = Field(min_length=4, max_length=200)


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class WorkspaceOut(OrmModel):
    id: str
    name: str
    role: str | None = None  # the caller's role in this workspace (None if unknown)


class WorkspaceMemberOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str
    is_self: bool = False


class MembersOut(BaseModel):
    members: list[WorkspaceMemberOut]
    my_role: str


class InviteMemberRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    role: str = Field(default="editor", pattern="^(admin|editor|viewer)$")


class InvitationOut(BaseModel):
    id: str
    workspace_id: str
    workspace_name: str
    inviter_name: str
    invitee_name: str
    role: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvitationListOut(BaseModel):
    invitations: list[InvitationOut]


class SetRoleRequest(BaseModel):
    role: str = Field(pattern="^(owner|admin|editor|viewer)$")


class ProjectCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=180)


class ProjectOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    active_sequence_id: str | None


class ProjectWithStatsOut(ProjectOut):
    """列表页项目卡片用的汇总信息;单个项目端点仍返回精简 ProjectOut。"""

    asset_count: int = 0
    sequence_count: int = 0
    timeline_duration: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AssetCreate(BaseModel):
    workspace_id: str
    project_id: str | None = None
    kind: str
    name: str
    original_filename: str = ""
    file_key: str = ""
    media_info: dict = Field(default_factory=dict)


class AssetOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None
    kind: str
    source: str
    name: str
    original_filename: str
    file_key: str
    media_info: dict
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    tags: list[str] | None = Field(default=None, max_length=24)
    #: 归入某个项目;空串 = 移出项目(回到"未归档")。工作流的「素材整理」节点一直能做这件事,
    #: 而这个接口收不了 —— 于是同一个能力在两个界面上不一样。
    project_id: str | None = Field(default=None, max_length=64)


class LutOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    original_filename: str
    size: int
    created_at: datetime | None = None


class FontOut(OrmModel):
    id: str
    workspace_id: str
    family: str
    original_filename: str
    size: int
    created_at: datetime | None = None


class LutUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TranscriptTokenIn(BaseModel):
    start_time: float
    end_time: float
    text: str = Field(max_length=120)


class TranscriptSegmentIn(BaseModel):
    start_time: float
    end_time: float
    text: str
    speaker: str | None = None
    tokens: list[TranscriptTokenIn] = Field(default_factory=list)


class TranscriptAttachRequest(BaseModel):
    language: str = Field(default="", max_length=24)
    source: str = Field(default="imported", max_length=40)
    segments: list[TranscriptSegmentIn] = Field(default_factory=list)


class TranscriptTokenOut(OrmModel):
    id: str
    token_index: int
    start_time: float
    end_time: float
    text: str


class TranscriptSegmentOut(OrmModel):
    id: str
    start_time: float
    end_time: float
    text: str
    speaker: str | None
    tokens: list[TranscriptTokenOut] = Field(default_factory=list)


class TranscriptOut(OrmModel):
    id: str
    workspace_id: str
    asset_id: str
    language: str
    status: str
    source: str
    segments: list[TranscriptSegmentOut] = Field(default_factory=list)


class SequenceCreate(BaseModel):
    workspace_id: str
    project_id: str
    name: str = Field(min_length=1, max_length=180)
    width: int = 1920
    height: int = 1080
    fps: float = 30.0


class ClipOut(OrmModel):
    id: str
    workspace_id: str
    sequence_id: str
    track_id: str
    asset_id: str | None
    #: 这一段用的是哪一类素材(video/audio/image/…)。**轨道类型说明不了它** —— 视频轨上完全
    #: 可以放图片(AI 生成的静图就是这么落上去的),而界面要据此判断"这一段能不能转写"。
    asset_kind: str = ""
    timeline_start: float
    src_in: float
    src_out: float
    speed: float
    gain: float
    muted: bool
    linked_clip_id: str | None
    text_override: str | None
    effects: dict
    transform: dict = Field(default_factory=dict)

    @field_validator("transform", "effects", mode="before")
    @classmethod
    def _none_to_dict(cls, value: object) -> object:
        return {} if value is None else value


class TrackOut(OrmModel):
    id: str
    sequence_id: str
    kind: str
    name: str
    position: int
    locked: bool
    muted: bool
    solo: bool = False
    duck: bool = False
    #: 这条轨的用途;空 = 普通轨。界面据此认出「配音轨」并把再一次的配音放回同一条。
    role: str = ""
    clips: list[ClipOut] = Field(default_factory=list)


class SetSequenceReframeRequest(BaseModel):
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=8192)
    fill_mode: str = Field(default="cover", pattern="^(cover|contain|blur)$")


class SequenceOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str
    name: str
    width: int
    height: int
    fps: float
    reframe: dict = Field(default_factory=dict)
    subtitle_style: dict = Field(default_factory=dict)
    revision: int

    @field_validator("reframe", "subtitle_style", mode="before")
    @classmethod
    def _none_to_dict(cls, value: object) -> object:
        return {} if value is None else value
    can_undo: bool = False
    can_redo: bool = False
    tracks: list[TrackOut] = Field(default_factory=list)


class InsertClipRequest(BaseModel):
    track_id: str
    asset_id: str
    timeline_start: float = 0.0
    src_in: float = 0.0
    src_out: float
    ripple: bool = False


class MoveClipRequest(BaseModel):
    timeline_start: float
    track_id: str | None = None
    ripple: bool = False


class ClipMoveEntry(BaseModel):
    clip_id: str
    timeline_start: float
    track_id: str | None = None


class ClipIdsRequest(BaseModel):
    """多选批量操作的通用入参:一次手势一条操作,撤销一步全部还原。"""

    clip_ids: list[str] = Field(min_length=1)


class MoveClipsBatchRequest(BaseModel):
    """框选后整组拖动。没有 ripple —— 一组片段要"挤开"什么没有唯一解,组拖按覆盖语义。"""

    moves: list[ClipMoveEntry] = Field(min_length=1)


class TrimClipRequest(BaseModel):
    timeline_start: float
    src_in: float
    src_out: float


class ExportRequest(BaseModel):
    """导出参数;整个 body 可省略(老调用方/工作流节点按默认档导出)。"""

    resolution: Literal["original", "1080p", "720p", "480p"] = "original"
    fps: float | None = Field(default=None, ge=1, le=120)
    quality: Literal["high", "standard", "compact"] = "standard"


class CutClipRangeRequest(BaseModel):
    src_start: float
    src_end: float


class CutClipRangesRequest(BaseModel):
    ranges: list[CutClipRangeRequest] = Field(min_length=1)


class SplitClipRequest(BaseModel):
    src_time: float


class SplitClipPointsRequest(BaseModel):
    src_times: list[float] = Field(min_length=1)


class MoveTrackRequest(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class SubtitleCueInput(BaseModel):
    text: str
    timeline_start: float
    duration: float


class GenerateSubtitlesRequest(BaseModel):
    track_id: str
    cues: list[SubtitleCueInput] = Field(min_length=1)


class SetSubtitleStyleRequest(BaseModel):
    style: dict


class SetTrackStateRequest(BaseModel):
    muted: bool | None = None
    locked: bool | None = None
    solo: bool | None = None
    duck: bool | None = None


class AddTrackRequest(BaseModel):
    kind: str = Field(pattern="^(video|audio|subtitle)$")


class SetClipEffectsRequest(BaseModel):
    effects: dict = Field(default_factory=dict)


class SetClipSpeedRequest(BaseModel):
    speed: float = Field(ge=0.25, le=4.0)


class SetClipGainRequest(BaseModel):
    gain: float = Field(ge=0.0, le=4.0)
    muted: bool = False


class TranslateRequest(BaseModel):
    #: 这次翻译算在哪个工作区头上。以前没有这个字段 —— 于是这个接口回答不了「这笔钱算谁的」,
    #: 而用量表的 workspace_id 是 NOT NULL,AI 翻译因此一条账都记不了。补的是建模缺失,
    #: 不是一道闸门:它同时把这个接口纳入了工作区权限体系。
    workspace_id: str
    #: 一次请求的条数上限。这是**防止一次请求打垮自己**的安全阀,不是「能翻多少字幕」的答案 ——
    #: 一条一小时视频的字幕轨轻松上千条。分批在客户端做(见 frontend/src/api/client.translateTexts,
    #: 那是唯一出口),所以这里不必为了迁就轨道长度把它调大:每一批都在这个数以内。
    texts: list[str] = Field(min_length=1, max_length=500)
    target_lang: str
    engine: str = Field(default="google", pattern="^(google|ai)$")
    profile_id: str | None = None


class TranslateResponse(BaseModel):
    translations: list[str]


class SetClipTransformRequest(BaseModel):
    transform: dict = Field(default_factory=dict)  # {scale,x,y,rotation,opacity};后端按范围钳制


class InsertTextClipRequest(BaseModel):
    track_id: str
    text: str = Field(min_length=1, max_length=500)
    timeline_start: float = 0.0
    duration: float = Field(default=2.0, gt=0)


class SetClipTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ClipTextEntry(BaseModel):
    clip_id: str
    text: str = Field(min_length=1, max_length=500)


class SetClipTextsRequest(BaseModel):
    # Bounded so one request cannot rewrite an unbounded number of clips in a single revision.
    texts: list[ClipTextEntry] = Field(min_length=1, max_length=2000)


class NotificationOut(OrmModel):
    id: str
    workspace_id: str
    type: str
    title: str
    body: str
    link: str | None
    payload: dict
    read_at: datetime | None
    created_at: datetime


class NotifyRequest(BaseModel):
    workspace_id: str
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=2000)


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread: int


class ProviderModelOut(BaseModel):
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
    context_window: int | None = None
    context_window_source: str = "fallback"
    max_output_tokens: int | None = None
    reasoning: bool | None = None
    vision: bool | None = None
    reasoning_effort: bool | None = None
    developer_role: bool | None = None


class ProviderModelUpdate(BaseModel):
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


class OAuthPromptOut(BaseModel):
    """登录流程中需要用户作答的一步(输入授权码、选账号……)。"""

    prompt_id: str
    prompt_type: str = "text"
    message: str = ""
    placeholder: str = ""
    options: list[dict] = Field(default_factory=list)


class OAuthLoginOut(BaseModel):
    """一次登录的当前状态。前端轮询它,拿到什么就展示什么。"""

    login_id: str
    status: str  # running | done | error | cancelled
    #: pi 的 AuthEvent 原样透传(auth_url / device_code / progress / info)。
    #: 刻意不翻译成自定义结构:上游加一种事件时,前端至少还能拿到原文而不是空白。
    events: list[dict] = Field(default_factory=list)
    prompt: OAuthPromptOut | None = None
    error: str = ""
    models: list[ProviderModelOut] = Field(default_factory=list)


class AgentContextPart(BaseModel):
    """堆叠条里的一段。kind ∈ messages|tools|system|free。"""

    kind: str
    tokens: int


class AgentContextOut(BaseModel):
    """窗口被**什么**占满了,不只是占了多少。

    一个百分比回答不了任何该做的决定:满了要清什么?清对话有用吗?而这个应用里最大的一块
    往往**不是对话** —— 工具定义每轮重发一遍,一条消息没有时它也在。分项由后端算:它需要
    系统提示的实际内容和工具清单,那两样都在服务端,前端猜出来的分项比没有分项更糟。
    """

    #: 供应商上次实际看到的量(锚点用量 + 之后新增的估算)。水位条读 `used`,这个留给明细。
    tokens: int
    window: int
    #: 各分项之和 = window。堆叠条按它画。
    used: int
    parts: list[AgentContextPart] = []


class AgentCompactOut(BaseModel):
    """一次手动压缩的结果。

    `compaction` 为 None 表示没有可压缩的内容(对话还太短)—— 界面据此说"暂时不需要整理",
    而不是显示一个"压缩了 0 条"的空结果。
    """

    context: AgentContextOut | None = None
    compaction: dict | None = None


class ProviderHealthOut(BaseModel):
    """一次探活的结果。`supported=False` 表示这类档案没法探(订阅计划没有我们持有的端点),
    界面据此整列不显示,而不是显示一个假的"离线"。"""

    supported: bool
    online: bool = False
    latency_ms: int | None = None
    detail: str = ""


class ProviderQuotaMetricOut(BaseModel):
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


class ProviderQuotaOut(BaseModel):
    """一次额度查询的结果。

    `supported=False` 与 `error` 是两回事:前者是这家压根没有可查的端点(界面该说"不支持"),
    后者是这次没查成(界面该说原因并允许重试)。混成一个会让"查不了"和"查失败"长一样。
    """

    supported: bool
    plan: str | None = None
    metrics: list[ProviderQuotaMetricOut] = Field(default_factory=list)
    fetched_at: float | None = None
    error: str = ""


class PricingPrefillOut(BaseModel):
    """按模型目录预填计价规则的结果。三个数分开报,是为了让「一条没建」可解释:
    是目录本身没报价(多数 OpenAI 兼容端点如此),还是规则早就配齐了。"""

    #: 本次新建的规则条数。
    created: int
    #: 目录里带报价的模型数。
    models_with_price: int
    #: 目录里的模型总数。
    models_seen: int


class OAuthAnswerIn(BaseModel):
    prompt_id: str
    answer: str


class LocalImportRequest(BaseModel):
    """按本机绝对路径导入素材(仅桌面端自带后端可用,见 routes/assets.import_local_asset)。"""

    workspace_id: str
    path: str
    project_id: str | None = None


class AnalyzeAssetRequest(BaseModel):
    question: str = Field(default="", max_length=2000)
    profile_id: str | None = None
    #: 视频分析方式:auto(有原生能力就走原生,否则抽帧)/ native(强制原生)/ frames(强制抽帧+转写)。
    mode: str = "auto"


class AnalyzeAssetResponse(BaseModel):
    answer: str
    provider: str
    model: str
    #: 实际走的方式:image / native / frames。
    mode: str = "frames"
    #: 抽帧数(原生模式为 0)。
    frames: int = 0
    used_transcript: bool = False


class ProviderCredentialIn(BaseModel):
    """我在某条连接上的钥匙。"""

    api_key: str | None = None
    #: VENDOR_PRESETS 里标了 secret 而不落 api_key 的那几个(火山 ak/sk、快手 secret_key)。
    secrets: dict[str, str] = Field(default_factory=dict)


class ProviderCredentialOut(BaseModel):
    profile_id: str
    key_hint: str = ""
    is_mine: bool = True


class ProviderProfileCreate(BaseModel):
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


class ProviderProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    #: Adapter-specific form values, keyed by VendorFieldOut.key.
    config: dict[str, str] | None = None
    enabled: bool | None = None
    auth_type: str | None = None


class VendorFieldOut(BaseModel):
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


class ProviderDefaultOut(BaseModel):
    capability: str
    provider_profile_id: str | None = None
    model: str = ""
    #: 这是我自己设的,还是部署给的起点(见 db.models.ProviderDefault)。界面据此区分,
    #: 否则"我没设过却有值"看着像 bug。
    is_mine: bool = False


class CapabilityModelOut(BaseModel):
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


class ProviderDefaultUpdate(BaseModel):
    provider_profile_id: str | None = None
    model: str = Field(default="", max_length=120)


class ProviderPricingRuleCreate(BaseModel):
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


class ProviderPricingRuleUpdate(BaseModel):
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




class NetworkConfigOut(BaseModel):
    """出站代理设置。空 proxy_url = 直连。"""

    proxy_url: str = ""
    no_proxy: str = ""
    #: 实际生效的绕过列表(= 用户填的 + 强制补上的回环)。回显出来,省得用户以为本机回连也被代理了。
    effective_no_proxy: str = ""


class NetworkConfigUpdate(BaseModel):
    proxy_url: str | None = None
    no_proxy: str | None = None


class AiRuntimeConfigOut(BaseModel):
    max_retries: int = 3


class AiRuntimeConfigUpdate(BaseModel):
    # 供应商瞬断时的最大重试次数(不含首次);0 表示不重试。
    max_retries: int = Field(ge=0, le=10)


class VoiceOut(BaseModel):
    id: str
    name: str
    reference_text: str = ""
    source: str = "upload"
    source_speaker: str | None = None
    has_reference: bool = True
    created_at: datetime


class VoiceUpdate(BaseModel):
    """改音色。**只改说明性的字段** —— 参考音频不在其中:换了音频就是另一个音色了,
    而已经用它生成过的配音还在时间线上,让同一个 id 底下的声音悄悄换人比新建一条更糟。"""

    name: str | None = None
    reference_text: str | None = None


class TtsEngineOut(BaseModel):
    id: str
    label: str
    detail: str
    status: str
    downloaded_bytes: int = 0
    total_bytes: int = 0
    expected_bytes: int = 0
    #: 上面那个体积是**问下载源问出来的**,还是目录里写死的估算。
    #: 界面据此决定要不要说「约」—— 把一个猜出来的数字显示成实测值,用户会拿它当准数
    #: (然后发现进度条走到 93% 就完成了,或者反过来永远差最后几个百分点)。
    total_is_estimate: bool = True
    speed_bps: float = 0.0
    eta_seconds: float | None = None
    message: str = ""
    # Fish Speech only: the source checkout is separate from the weights, so surface it
    # on its own (weights can be "installed" while the source is still missing).
    needs_source: bool = False
    source_ready: bool = False
    source_dir: str = ""
    #: 这个引擎**真的**能用的下载源,按顺序给。界面据此渲染,而不是自己猜哪个引擎配哪些源
    #: —— 让界面猜的下场就是「ModelScope」最早的样子:列在那里、选得中、却什么都不改变。
    sources: list[str] = []
    #: 这个引擎吃不吃语速。界面据此决定显不显示那个下拉 —— 摆一个拨不动的旋钮比不摆更糟。
    supports_speed: bool = False
    #: **权重在不在盘上,和跑不跑得起来是两件事。** status 说前者,这个说后者:有没有一个
    #: Python 解释器能 import 这个引擎。两者完全可以一真一假(权重是别的工具下的、或者
    #: 托管 venv 被删了),而把它们合成一句「已安装,声音克隆可用」正是这一页说谎的方式。
    runtime_ready: bool = False
    #: 探过了没有。**"还没测过"和"测过了、跑不起来"是两回事** —— 探测要起子进程 import
    #: torch,不能卡在请求里,所以列状态时可能还没有答案。把未知说成"未就绪"就是拿一个未知
    #: 冒充一个结论。
    runtime_checked: bool = True


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None
    #: 这一次用哪个本地引擎(f5-tts / fish-speech)。空 = 用设置页那个默认 ——
    #: 设置页是默认,不是唯一。
    clone_model: str = Field(default="", max_length=40)
    clone_engine: str = Field(default="", max_length=40)
    #: 语速。**只有声明支持的引擎会用它**(见 TtsEngine.supports_speed):F5 的 infer 吃,
    #: fish 的请求结构里根本没有这一项。收下但不转发,好过让界面以为发了就生效。
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class UrlProbeRequest(BaseModel):
    workspace_id: str
    url: str = Field(min_length=4, max_length=2000)
    #: 探测也可能需要登录态:私享列表不登录就是"不可用"。
    profile_id: str | None = None
    #: 从列表的第几条开始(1 起)。频道能有上万条,一次探 200 条,往后翻靠它。
    start: int = Field(default=1, ge=1)


class RemoteEntryOut(BaseModel):
    id: str
    url: str
    title: str
    duration: float | None = None
    uploader: str = ""
    thumbnail: str = ""
    #: 这一条实际拿得到的画质高度(从高到低)。空 = 未知(播放列表只做浅层探测),不是"没有"。
    heights: list[int] = Field(default_factory=list)


class UrlProbeResponse(BaseModel):
    title: str
    is_playlist: bool
    entries: list[RemoteEntryOut]
    #: 这一批从第几条开始(1 起)。界面据此说「第 201–400 条」,而不是让人以为总共这么多。
    start: int = 1
    #: 清单被截断了吗。**要如实说** —— 否则用户以为这就是全部,勾完发现少了一半。
    truncated: bool = False


class UrlImportItem(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    title: str = Field(default="", max_length=300)


class UrlImportRequest(BaseModel):
    workspace_id: str
    project_id: str | None = None
    items: list[UrlImportItem] = Field(min_length=1, max_length=50)
    #: 下画面还是只下声轨。**不是下完再抽** —— 只要声音的人不该为此付几百 MB 和一次转码。
    kind: str = Field(default="video", pattern="^(video|audio)$")
    #: 借哪个浏览器池档案的登录态(会员视频、私享列表需要)。空 = 按公开内容下载。
    profile_id: str | None = None
    #: 画质上限(0 = 不限)。**上限而不是精确值**:同一批里每条能给的画质不一样。
    max_height: int = Field(default=0, ge=0, le=4320)


class SubtitleDubRequest(BaseModel):
    """给选中的字幕条配音。音色/引擎那一套与 /tts/synthesize 同构 —— 配音就是合成,只是文本
    来自字幕、产物直接落到时间线上。"""

    clip_ids: list[str] = Field(min_length=1, max_length=500)
    #: 把配音拉伸/压缩到字幕段落的长度。**默认关** —— 变速会改变语速听感,超出 ±20% 就开始
    #: 明显不自然,值不值这个代价由用户按素材决定,而不是替他默认承受。
    match_duration: bool = False
    #: 双语字幕(「原文\n译文」)念哪一行。整段念的话是先念一遍原文再念一遍译文 ——
    #: 一条 3 秒的字幕能配出 12 秒的音。默认全念:单语字幕就该全念,那是绝大多数情况。
    line: str = Field(default="all", pattern="^(all|first|last)$")
    engine: str = Field(default="clone", max_length=40)
    #: 克隆引擎要一个音色行;远端引擎不需要,它自带发音人。
    voice_id: str | None = None
    clone_engine: str = Field(default="", max_length=40)
    #: 明说要用哪一份克隆权重(见 ai/runtime/f5_models)。空 = 按文字自动挑。
    #: 法语/德语/西语/意语/芬兰语都写拉丁字母,自动挑**永远挑不中**,只能由人来说。
    clone_model: str = Field(default="", max_length=40)
    provider_profile_id: str | None = None
    engine_model: str = Field(default="", max_length=120)
    engine_voice: str = Field(default="", max_length=120)
    engine_voice_resource: str = Field(default="", max_length=60)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)


class EngineSynthesizeRequest(BaseModel):
    """Synthesis through a remote engine, which speaks in a stock voice and so has no Voice row."""

    workspace_id: str
    text: str = Field(min_length=1, max_length=2000)
    engine: str = Field(min_length=1, max_length=40)
    provider_profile_id: str | None = None
    engine_model: str = Field(default="", max_length=120)
    engine_voice: str = Field(default="", max_length=120)
    #: 火山 only: the voice's resource family. Only the account's voice list knows it, and the
    #: synthesis header must agree with it or the call fails with an opaque 55000000. Blank
    #: falls back to inferring it from the voice id, which works for the built-in voices.
    engine_voice_resource: str = Field(default="", max_length=60)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)
    project_id: str | None = None


class PodcastRequest(BaseModel):
    """A 火山 podcast: two voices reading or discussing the given material."""

    workspace_id: str
    project_id: str | None = None
    provider_profile_id: str | None = None
    #: The material. summarize/read use this; research uses `topic` instead.
    text: str = Field(default="", max_length=20000)
    topic: str = Field(default="", max_length=2000)
    mode: str = Field(default="summarize", pattern="^(summarize|read|research)$")
    speakers: list[str] = Field(default_factory=list, max_length=2)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)


class TtsVoiceOut(BaseModel):
    """One selectable voice. `resource_id` is 火山-specific: the synthesis header must name the
    voice's family, and only the listing knows it — inferring it from the id is guesswork that
    fails with an opaque 55000000."""

    value: str
    label: str
    resource_id: str = ""


class TtsEngineChoiceOut(BaseModel):
    """An engine the配音 UI can offer. Distinct from TtsEngineOut, which describes a downloadable
    LOCAL model — same word, different thing, and defining both as TtsEngineOut silently
    shadowed the older one and broke /tts/models' response validation."""

    id: str
    label: str
    needs_key: bool
    needs_voice_id: bool
    voices: list[str] = []
    #: 这个引擎接不接语速。接不了就别在界面上摆那个旋钮 —— 拨得动却不生效,
    #: 比没有更糟(配音要的正是"塞进原时长",用户会以为自己调过了)。
    supports_speed: bool = True
    note: str = ""
    #: 这台机器上现在就能跑吗。远程引擎恒真(能不能跑取决于档案,那是另一件事);
    #: 本地克隆按解释器探测结果给,好让界面在**挑引擎**时就说清楚。
    ready: bool = True


class VoiceFromSpeakerRequest(BaseModel):
    asset_id: str
    speaker: str | None = None
    name: str = ""


class TtsConfigOut(BaseModel):
    engine: str
    python_path: str = ""
    source: str = "hf-mirror"
    pip_index: str = ""  # 空 = 官方 PyPI
    fish_repo_dir: str = ""  # Fish Speech source checkout
    fish_model_dir: str = ""  # Fish Speech weights dir (contains codec.pth)
    worker_ready: bool = False  # an interpreter with the engine installed was found
    worker_python: str = ""  # the resolved interpreter path (for display)
    #: 探过了没有。**「还没测过」和「测过了、跑不起来」是两回事** —— 探测要起子进程
    #: import f5_tts(连带 torch,实测 7 秒),所以这个接口不等它。同 AsrModelOut.runtime_checked。
    worker_checked: bool = True


class TtsConfigUpdate(BaseModel):
    engine: str = Field(pattern="^(f5-tts|fish-speech)$")
    python_path: str = ""
    source: str = Field(default="hf-mirror", pattern="^(hf|hf-mirror|modelscope)$")
    #: 预设 key(pypi/tsinghua/aliyun/tencent)或自定义 index URL;空 = 官方 PyPI。
    pip_index: str = Field(default="", max_length=200)
    fish_repo_dir: str = ""
    fish_model_dir: str = ""


class AsrModelOut(BaseModel):
    id: str
    engine: str
    label: str
    detail: str
    status: str  # "installed" | "missing" | "downloading" | "failed"
    #: **模型文件在不在盘上,和跑不跑得起来是两件事。** status 说前者,这个说后者:有没有一个
    #: Python 解释器装了 funasr/whisperx。两者完全可以一真一假(模型缓存是别的工具下的),
    #: 而把它们合成一个「已安装」正是这一页此前说谎的原因。
    runtime_ready: bool = False
    #: 探过了没有。**"还没测过"和"测过了、跑不起来"是两回事** —— 探测要起子进程 import
    #: torch,不能卡在请求里,所以列状态时可能还没有答案。把未知说成"未就绪"就是拿一个未知
    #: 冒充一个结论。
    runtime_checked: bool = True
    downloaded_bytes: int = 0
    total_bytes: int = 0
    expected_bytes: int = 0
    #: 上面那个体积是问下载源问出来的,还是写死的估算(同 TtsEngineOut.total_is_estimate)。
    total_is_estimate: bool = True
    speed_bps: float = 0.0
    eta_seconds: float | None = None
    message: str = ""


class VendorPresetOut(BaseModel):
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


class GenerationOptionOut(BaseModel):
    """一个「用哪条连接的哪个模型来生成」的选项。

    **后端做联接**:以前这份列表由前端拿三张表(生成目录 / 启用的档案 / 能力默认)现拼,
    任何一份口径变一点就和设置页对不上。现在只有一条线 —— 有哪些模型看 provider_models。
    """

    id: str
    provider_profile_id: str
    profile_name: str
    provider: str
    kind: str
    model: str
    label: str
    capabilities: dict = Field(default_factory=dict)
    #: 这个 vendor+kind 有没有接入的生成 Adapter。不可用的照样列出但标出来 ——
    #: 藏起来的话用户配好了却找不到,只会以为是自己配错了。
    adapter_available: bool = False


class GenerationModelOut(OrmModel):
    id: str
    provider: str
    kind: str
    model: str
    enabled: bool
    capabilities: dict
    adapter_available: bool


class SourceAssetRef(BaseModel):
    """一份输入素材,**带着它的用途**。

    此前这里是一个裸的 id 列表,谁是首帧靠「第 0 个」这条约定 —— 尾帧、参考图、参考视频
    因此都没地方放。role 的取值见 ai/providers/contracts/generation.SOURCE_ROLES;哪个模型认哪几种,
    由 domain/generation/catalog 的描述符声明。
    """

    asset_id: str = Field(min_length=1, max_length=64)
    # 取值**从 SOURCE_ROLES 生成**,不手抄。注释里早写着"取值见 base.SOURCE_ROLES"了,
    # 而下面那条正则是抄的第二份 —— 加第九种角色时描述符说支持、这里却会以校验错误拒掉它,
    # 而报的是一句正则不匹配,和"角色"两个字没有关系。
    role: str = Field(default=FIRST_FRAME, pattern=f"^({'|'.join(SOURCE_ROLES)})$")


class GenerationCreate(BaseModel):
    workspace_id: str
    session_id: str | None = None
    project_id: str | None = None
    provider_profile_id: str | None = None
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(image|video)$")
    prompt: str = Field(min_length=1)
    negative_prompt: str = Field(default="", max_length=4000)
    parameters: dict = Field(default_factory=dict)
    source_assets: list[SourceAssetRef] = Field(default_factory=list)


class GenerationJobOut(OrmModel):
    id: str
    workspace_id: str
    session_id: str | None = None
    # 任务中心清理已完成 job 后置空(记录本身长存,状态由 result_asset_id 兜底)。
    job_id: str | None = None
    provider_profile_id: str | None = None
    provider: str
    model: str
    kind: str
    request: dict
    result_asset_id: str | None
    #: **全部产出。** 一次生成可能出多份(图像接口的 n),而 result_asset_id 只放得下封面 ——
    #: 界面照这一串出图,不然用户选了 4 张、只看得见 1 张(另外 3 张确实在素材库里,他不知道)。
    #: 封面排在第一。由路由从 generated_assets 贴上来。
    result_asset_ids: list[str] = []
    created_at: datetime
    updated_at: datetime
    # 计费:取自本次生成记录的用量事件(source_type=generation_job)。cost_micros 为已知估算费用;
    # 有事件但无定价规则时 cost_confidence=unknown、cost_micros 为空(前端显示「未定价」)。
    cost_micros: int | None = None
    currency: str | None = None
    cost_confidence: str | None = None


class GenerationCreateResponse(BaseModel):
    generation: GenerationJobOut
    job: JobOut


class PromptOptimizeRequest(BaseModel):
    workspace_id: str
    #: 目标图像平台(provider/model)——只用来选平台提示词习惯,不是重写用的 LLM。
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1)
    #: 重写用的聊天 LLM 供应商配置;缺省用默认启用的那个(与助手/工作流同一个)。
    provider_profile_id: str | None = None
    language: str = Field(default="zh", max_length=10)


class PromptOptimizeResponse(BaseModel):
    prompt: str
    negative_prompt: str = ""
    notes: str = ""
    platform: str = ""


class GenerationSessionCreate(BaseModel):
    workspace_id: str
    title: str = Field(default="新生成", max_length=200)
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, pattern="^(image|video)$")


class GenerationSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    #: 收进哪个分组;空串或 null 表示退回未分组。
    group_id: str | None = None
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, pattern="^(image|video)$")


class GenerationSessionOut(OrmModel):
    id: str
    workspace_id: str
    # 归属(见 domain/sharing):生成记录和对话一样,默认只有自己看得见。
    owner_user_id: str | None = None
    is_mine: bool = True
    shared: bool = False
    title: str
    group_id: str | None = None
    provider_profile_id: str | None = None
    model: str | None = None
    kind: str | None = None
    created_at: datetime
    updated_at: datetime


class ScheduledTaskCreate(BaseModel):
    workspace_id: str
    project_id: str | None = None
    name: str = Field(min_length=1, max_length=180)
    kind: str = Field(min_length=1, max_length=60)
    trigger_type: str = Field(pattern="^(manual|once|interval|daily|weekly|webhook)$")
    schedule: dict = Field(default_factory=dict)
    timezone: str = Field(default="UTC", max_length=80)
    enabled: bool = True
    payload: dict = Field(default_factory=dict)


class ScheduledTaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    trigger_type: str | None = Field(default=None, pattern="^(manual|once|interval|daily|weekly|webhook)$")
    schedule: dict | None = None
    timezone: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None
    payload: dict | None = None


class ScheduledTaskOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None
    name: str
    kind: str
    trigger_type: str
    schedule: dict
    timezone: str
    enabled: bool
    payload: dict
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # 归属(见 domain/sharing):是不是我的、在不在这个工作区里。定时任务默认共享,但仍有主人 ——
    # 事后要知道这段自动化是谁挂上去的。
    owner_user_id: str | None = None
    is_mine: bool = True
    shared: bool = True


class ScheduledTaskRunOut(OrmModel):
    id: str
    scheduled_task_id: str
    job_id: str | None
    status: str
    result: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunScheduledTaskResponse(BaseModel):
    task: ScheduledTaskOut
    run: ScheduledTaskRunOut
    job: JobOut


class PluginFieldOut(BaseModel):
    """一个配置项或凭据项。凭据只是 secret=True 的配置 —— 差别在控件和回显,不在语义。"""

    key: str
    label: str
    type: str = "string"  # string | enum | number | boolean
    help: str = ""
    required: bool = True
    secret: bool = False
    options: list[dict] = Field(default_factory=list)
    default: str = ""


class PluginToolStateOut(BaseModel):
    name: str
    label: str = ""
    description: str = ""
    read_only: bool = False
    input_schema: dict = Field(default_factory=dict)
    #: 暴不暴露给智能体与工作流。默认关 —— 一个 MCP 端点可能报几十个工具。
    exposed: bool = False


class PluginInstanceOut(BaseModel):
    id: str
    package_id: str
    name: str
    enabled: bool
    config: dict = Field(default_factory=dict)
    #: 为什么还不能用(未启用 / 缺配置 / 缺凭据 / 未授权)。空串 = 可用。
    blocked_reason: str = ""
    tools: list[PluginToolStateOut] = Field(default_factory=list)


class PluginPackageOut(BaseModel):
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
    instances: list[PluginInstanceOut] = Field(default_factory=list)


class AgentQuestionOption(BaseModel):
    label: str
    description: str = ""


class AgentQuestionItem(BaseModel):
    header: str = ""
    question: str
    multi_select: bool = False
    options: list[AgentQuestionOption] = Field(default_factory=list)


class AgentQuestionCreate(BaseModel):
    workspace_id: str
    session_id: str
    #: 形状由 domain/agent/questions.normalize 校 —— 校验和展示用同一份规则,
    #: 在这里再写一遍 pydantic 约束会变成第二个答案。
    questions: list[dict] = Field(default_factory=list)


class AgentQuestionAnswer(BaseModel):
    #: {问题正文: [选中的 label]}。单选也是列表(长度 1)—— 两种形状分开的话消费端要解析两遍。
    answers: dict[str, list[str]] = Field(default_factory=dict)


class AgentQuestionOut(OrmModel):
    id: str
    workspace_id: str
    session_id: str
    questions: list[AgentQuestionItem] = Field(default_factory=list)
    answers: dict[str, list[str]] = Field(default_factory=dict)
    status: str
    created_at: datetime
    answered_at: datetime | None = None


class PluginMarketEntry(BaseModel):
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


class PluginInstallRequest(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    #: 覆盖已装的同 id 包。要单独同意 —— 那个目录里可能已经有用户填过的东西,
    #: 而且新版本可能声明了完全不同的权限。
    overwrite: bool = False


class PluginInstallPreview(BaseModel):
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


class PluginInstanceCreate(BaseModel):
    name: str = ""
    config: dict = Field(default_factory=dict)


class PluginInstanceUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None


class PluginCapabilityUpdate(BaseModel):
    #: 工具名 → 暴不暴露。
    tools: dict[str, bool] = Field(default_factory=dict)


class PluginEnableRequest(BaseModel):
    enabled: bool


class PluginPermissionGrantOut(OrmModel):
    instance_id: str
    permission: str
    granted: bool
    created_at: datetime
    updated_at: datetime


class PluginPermissionGrantUpdate(BaseModel):
    grants: dict[str, bool] = Field(default_factory=dict)


class PluginCredentialOut(BaseModel):
    """插件声明的一项凭据 + 当前状态。secret 项的 value 是掩码,不是原值。"""

    key: str
    label: str
    help: str = ""
    secret: bool = True
    required: bool = True
    filled: bool = False
    value: str = ""


class PluginCredentialUpdate(BaseModel):
    #: 键 → 值。掩码原样回传表示"这项没改";空串表示清空。
    values: dict[str, str] = Field(default_factory=dict)


class PluginToolOut(BaseModel):
    """一个**已暴露**的工具。智能体工具表与工作流节点面板读的就是这个。"""

    instance_id: str
    instance_name: str
    package_id: str
    name: str
    label: str = ""
    description: str = ""
    read_only: bool = False
    input_schema: dict = Field(default_factory=dict)


class PluginInvokeRequest(BaseModel):
    input: dict = Field(default_factory=dict)


class PluginInvocationOut(OrmModel):
    id: str
    instance_id: str
    tool_name: str
    status: str
    input: dict
    output: dict
    error: str | None
    created_at: datetime


class WorkflowCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=2000)
    graph: dict | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    graph: dict | None = None


class WorkflowImportRequest(BaseModel):
    """导入工作流:data 是导出文件的完整 JSON(format/version/name/graph 信封)。"""

    workspace_id: str
    data: dict


class WorkflowOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    description: str
    graph: dict
    created_at: datetime
    updated_at: datetime


class BoardOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    canvas: dict
    created_at: datetime
    updated_at: datetime


class BoardCreate(BaseModel):
    workspace_id: str
    name: str = ""
    canvas: dict | None = None


class BoardUpdate(BaseModel):
    workspace_id: str
    #: 两者都可以单独传 —— 自动保存只发 canvas,重命名只发 name。None = 这次不改它,
    #: 而不是"清空它"。
    name: str | None = None
    canvas: dict | None = None


class BoardGenerate(BaseModel):
    workspace_id: str
    #: 前端先编好 id —— 占位项和回执要指同一个东西,由前端定名字省掉一次往返。
    item_id: str
    kind: str = "image"
    prompt: str
    x: float = 0
    y: float = 0
    provider: str = ""
    model: str = ""
    parameters: dict = Field(default_factory=dict)
    source_assets: list[SourceAssetRef] = Field(default_factory=list)
    #: 用户可再次编辑的原始表单。prompt 是用户写的那份，不含调用供应商时临时追加的图例。
    form: dict = Field(default_factory=dict)


class VideoToGifRequest(BaseModel):
    """Options for creating a new GIF asset from a video asset."""

    fps: int = Field(default=12, ge=1, le=30)
    width: int = Field(default=720, ge=64, le=1920)
    start: float = Field(default=0, ge=0)
    duration: float | None = Field(default=None, gt=0)


class BoardWrite(BaseModel):
    """让 AI 往画板上的一张便签里写字。

    和 BoardGenerate **不是一条路**:出图出片要几十秒,所以那边先摆占位、起任务、回执填回来;
    写字几秒就回,同步返回反而更直接 —— 为它铺一套任务/回执,用户看到的只是一个多余的转圈。
    """

    workspace_id: str
    item_id: str
    prompt: str
    #: 留空就用这个人在 chat 能力上的默认模型。
    provider_profile_id: str = ""
    model: str = ""
    #: 让模型**看着**写:上游连过来的图片、正文里 @ 到的图片。多模态模型才吃得下,
    #: 不认的会当作没有(而不是报错)——一张图带不动整次请求。
    source_assets: list[str] = Field(default_factory=list)
    #: 上游便签给的材料。**和「要求」分开** —— 揉成一段的话,模型分不清哪句是素材、哪句是指令。
    context: list[str] = Field(default_factory=list)


class BoardSpeak(BaseModel):
    """把一段文字念成音频,产出落回画板上那一格。

    和写文案**不是一条路**:写字几秒就回所以同步;念出来要起合成任务(可能还在另一台机器上跑),
    所以走和出图出片同一套 —— 先摆占位、起任务、回执把产出填回来。
    """

    workspace_id: str
    item_id: str
    text: str
    #: 用哪个音色。留空时由 start_synthesis 按这个人的默认走。
    voice_id: str = ""
    x: float = 0
    y: float = 0


class BoardTrim(BaseModel):
    """把一段视频/音频截出起止,产出落回画板上那一格。"""

    workspace_id: str
    #: 产出落到哪一格。
    item_id: str
    #: 截哪一份素材。
    asset_id: str
    start: float = 0
    end: float
    #: 去掉声音 —— 做无声底片时常用。
    mute: bool = False
    x: float = 0
    y: float = 0


class AssetFrameRequest(BaseModel):
    """从一段视频里取某一时刻的一帧,存成一份新素材。"""

    at: float = 0
    #: 落到哪个项目下。留空跟随原素材。
    project_id: str | None = None


class SequenceFrameRequest(BaseModel):
    """把时间线在某一时刻的合成画面存成一份新素材。"""

    at: float = 0


class WorkflowRunRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class WorkflowNodeTypeOut(BaseModel):
    type: str
    label: str
    description: str
    category: str = ""  # 面板分组;空=通用组
    config: dict
    outputs: list[str]
    #: 插件节点带来源插件名(内置节点为空)。面板据此在同名工具之间区分是谁提供的。
    plugin_name: str = ""


class WorkflowAiEditRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    graph: dict | None = None
    profile_id: str | None = None


class WorkflowAiEditResponse(BaseModel):
    graph: dict
    summary: str = ""


class AgentSessionCreate(BaseModel):
    workspace_id: str
    project_id: str | None = None
    title: str = Field(default="新对话", max_length=200)
    adapter: str | None = Field(default=None, pattern="^pi$")
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)


class SessionGroupCreate(BaseModel):
    workspace_id: str
    #: 挂在哪一种会话上。两边各自一套,见 db/models.SESSION_GROUP_KINDS。
    kind: str = Field(default="agent", pattern="^(agent|generation)$")
    name: str = Field(min_length=1, max_length=80)


class SessionGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = None


class SessionGroupOut(OrmModel):
    id: str
    workspace_id: str
    kind: str
    owner_user_id: str | None = None
    name: str
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class AgentSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    #: 视频分析方式偏好:auto / native / frames。
    analysis_video_mode: str | None = None
    thinking_level: str | None = None
    #: 权限模式:manual / auto / bypass。切到 bypass 另需 admin(见路由)。
    permission_mode: str | None = None
    #: 「本会话始终允许」的工具名单。整份替换 —— 它就是用户在卡上点出来的那份清单。
    auto_allow_tools: list[str] | None = None
    #: 收进哪个分组。**空串 = 移出分组**(与 provider_profile_id 同一套约定):这套 schema 用
    #: None 表示"这次没改",所以"改成没有"必须另有说法。
    group_id: str | None = Field(default=None, max_length=64)


class AgentSessionOut(OrmModel):
    id: str
    workspace_id: str
    # 归属(见 domain/sharing):对话默认只有自己看得见,主人可以把某一次拿出来给同事看。
    owner_user_id: str | None = None
    is_mine: bool = True
    shared: bool = False
    project_id: str | None
    group_id: str | None = None
    title: str
    origin: str
    adapter: str
    permission_mode: str = "manual"
    mode_set_by: str | None = None
    auto_allow_tools: list[str] = []
    provider_profile_id: str | None = None
    model: str | None = None
    analysis_video_mode: str = "auto"
    thinking_level: str = "off"
    status: str
    #: 当前上下文水位。**每次请求现算**,而不是等某一轮回报 —— 打开旧会话、刚换过模型、
    #: 上一轮失败了,这些时候都没有新的一轮可以带回这个数,而"还能聊多久"这个问题恰恰在
    #: 开口之前就要有答案。窗口取当前模型的,换模型即变。
    context: AgentContextOut | None = None
    #: 当前任务计划 `[{"step","status"}]`;还没有计划时为 None(界面据此整块不显示)。
    plan: list[dict] | None = None
    created_at: datetime
    updated_at: datetime


class AgentPlanUpdate(BaseModel):
    steps: list = Field(default_factory=list)


class AgentMemoryOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    content: str
    #: agent = 智能体自己记的;user = 用户在设置里写的。
    source: str = "agent"
    created_at: datetime
    updated_at: datetime


class AgentMemoryCreate(BaseModel):
    workspace_id: str
    project_id: str | None = None
    content: str = Field(min_length=1, max_length=500)
    source: str = "user"


class AgentMemoryUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class AgentMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    context: str | None = Field(default=None, max_length=4000)
    #: 发起方是另一个智能体会话时带上它的 id(notify_agent_session)。结构化而不是靠文案前缀:
    #: 标题自动命名要跳过它,前端要给它画来源徽章 —— 两件事都不该建立在字符串匹配上。
    origin_session_id: str | None = Field(default=None, max_length=64)


class AgentMessageOut(OrmModel):
    id: str
    session_id: str
    role: str
    content: str
    payload: dict
    error: str | None
    created_at: datetime


class FeishuBotCreate(BaseModel):
    workspace_id: str
    name: str = Field(default="Open Studio 助手", max_length=160)
    app_id: str = Field(min_length=1, max_length=120)
    app_secret: str = Field(min_length=1, max_length=200)
    capability: str = Field(default="editor", pattern="^(readonly|editor|full)$")


class FeishuBotUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    capability: str | None = Field(default=None, pattern="^(readonly|editor|full)$")
    enabled: bool | None = None


class FeishuBotOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    app_id: str
    capability: str
    enabled: bool
    status: str
    status_detail: str
    created_at: datetime


class FeishuOnboardingOut(BaseModel):
    phase: str
    qr_url: str | None = None
    user_code: str | None = None
    error: str | None = None
    app_id: str | None = None


class FeishuBindCodeOut(BaseModel):
    code: str
    expires_at: datetime


class FeishuBindingOut(BaseModel):
    open_id: str
    user_id: str
    username: str


class ConfirmationCreate(BaseModel):
    workspace_id: str
    tool: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)
    requested_by: str = Field(default="external-agent", max_length=120)
    #: **没有 session_id**:确认卡归属哪次对话由调用方的凭据决定(见 routes/confirmations),
    #: 不由请求体声明 —— 声明就可以被伪造。留一个"填了也不生效"的字段,下一个人会以为它生效。


class ConfirmationOut(OrmModel):
    id: str
    workspace_id: str
    session_id: str | None
    tool: str
    permission: str
    summary: str
    payload: dict
    status: str
    result: dict
    error: str | None
    requested_by: str
    decision_mode: str = "manual"
    decided_by: str | None = None
    created_at: datetime
    resolved_at: datetime | None


class AgentSkillOut(BaseModel):
    id: str
    name: str
    description: str
    source: str
    tools: list = Field(default_factory=list)
    permissions: list = Field(default_factory=list)


# ---------- 知识库(Dify 式 dataset) ----------










class AgentManifestOut(BaseModel):
    app: str
    version: str
    openapi_url: str
    skills: list[AgentSkillOut]


class DailyActivityOut(BaseModel):
    """一天的任务活动(首页活动图的一根柱)。date 为 YYYY-MM-DD(UTC)。"""

    date: str
    succeeded: int
    failed: int


class DailyPublishOut(BaseModel):
    """一天的发布活动(首页发布图的一根柱)。date 为 YYYY-MM-DD(UTC)。"""

    date: str
    succeeded: int
    failed: int
    active: int
    blocked: int


class DailyUsageOut(BaseModel):
    """一天的供应商费用/用量。cost_micros 是已知估算费用,unknown 是未定价事件数。"""

    date: str
    cost_micros: int
    events: int
    unknown: int


class DailyUsageTokensOut(BaseModel):
    """一天的 AI token 用量。total_tokens 允许供应商只返回总量,不拆输入/输出。"""

    date: str
    input_tokens: int
    output_tokens: int
    #: 缓存读/写单列 —— 它们与 input 不相交,单价也差一个数量级。并进"其他"的话,
    #: "这个月省下多少"在界面上就看不见了。
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int


class WorkspaceSummaryOut(BaseModel):
    """首页仪表数字。一次请求给全一屏,避免首页发 N 个列表请求做 .length 聚合。"""

    project_count: int
    asset_count: int
    sequence_count: int
    workflow_count: int
    running_jobs: int
    week_jobs_succeeded: int
    week_jobs_failed: int
    publish_accounts: int
    week_published: int
    # 图表数据:近 14 天逐日任务活动(旧→新,缺日补零)与素材类型构成
    daily: list[DailyActivityOut]
    asset_kinds: dict[str, int]
    # 发布图表:近 14 天发布任务状态(旧→新,缺日补零)与按平台聚合的发布任务数
    publish_daily: list[DailyPublishOut]
    publish_platforms: dict[str, int]
    # 供应商费用/用量:近 14 天聚合;没有价格规则时 cost 为 0,unknown 计数仍保留审计线索
    usage_cost_micros: int = 0
    usage_currency: str = "USD"
    usage_event_count: int = 0
    usage_unknown_cost_events: int = 0
    #: 没能定价的「供应商 + 模型 + 能力」及其次数。界面据此说清**缺哪个模型的价**,
    #: 而不是笼统一句「暂无价格规则」——后者在用户配了规则、只是没配这个模型时是错的。
    usage_unpriced: list[dict] = Field(default_factory=list)
    usage_duration_seconds: float = 0
    usage_token_count: int = 0
    usage_cache_read_tokens: int = 0
    usage_cache_write_tokens: int = 0
    #: cacheRead / 提示词总量(input + cacheRead + cacheWrite)。0..1。
    usage_cache_hit_ratio: float = 0.0
    usage_daily: list[DailyUsageOut] = Field(default_factory=list)
    usage_token_daily: list[DailyUsageTokensOut] = Field(default_factory=list)
    usage_by_capability: dict[str, int] = Field(default_factory=dict)
    usage_by_provider: dict[str, int] = Field(default_factory=dict)
