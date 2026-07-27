from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthCredentials(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=4, max_length=200)


class RegisterCredentials(AuthCredentials):
    display_name: str = Field(default="", max_length=120)


class UserOut(OrmModel):
    id: str
    username: str
    display_name: str
    signature: str
    #: 空 = 未设置头像;非空时前端以 /api/auth/users/{id}/avatar?v=<key> 取图并借 key 破缓存。
    avatar_key: str = ""


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
    perms: dict[str, bool]  # effective perms (role defaults + overrides)
    is_self: bool = False


class MembersOut(BaseModel):
    members: list[WorkspaceMemberOut]
    my_role: str
    perm_keys: list[str]  # every togglable perm, for the override UI
    role_defaults: dict[str, dict[str, bool]]  # role → its default perm set


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


class SetMemberPermsRequest(BaseModel):
    perms: dict[str, bool]


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


class TaskEventOut(OrmModel):
    id: str
    job_id: str
    type: str
    payload: dict
    created_at: datetime


class JobOut(OrmModel):
    id: str
    workspace_id: str
    kind: str
    parent_job_id: str | None = None
    status: str
    progress: float
    message: str
    payload: dict
    result: dict
    error: str | None
    created_at: datetime
    updated_at: datetime


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


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread: int


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


class ProviderProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    vendor: str = Field(min_length=1, max_length=60)
    #: Adapter-specific form values, keyed by VendorFieldOut.key.
    config: dict[str, str] = Field(default_factory=dict)
    #: 档案级能力覆盖(None=沿用 vendor 默认)。用于把只做对话的通用端点取消 image/video 等。
    capability_ids: list[str] | None = None
    #: 服务端从既有档案复制 secret 字段(如同一把方舟 Key 配到另一能力的独立档案),
    #: 密钥全程不出后端、不下发前端。仅在本档案未显式提供该字段时生效。
    copy_credentials_from: str | None = None


class ProviderProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    #: Adapter-specific form values, keyed by VendorFieldOut.key.
    config: dict[str, str] | None = None
    #: 档案级能力覆盖;传 [] 清空(=显式声明"无能力"),传 null / 不传则不改动。
    capability_ids: list[str] | None = None
    enabled: bool | None = None


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
    default_model: str
    enabled: bool
    created_at: datetime
    key_hint: str = ""
    #: Non-secret extras come back verbatim; secret ones only as "…abcd", never in full —
    #: same rule as api_key/key_hint.
    extra: dict[str, str] = Field(default_factory=dict)
    #: Masked, adapter-shaped config for the settings form; secret fields are hints only.
    config: dict[str, str] = Field(default_factory=dict)

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


class KbEmbeddingConfigOut(BaseModel):
    provider_profile_id: str | None = None
    model: str = ""
    dim: int = 0
    enabled: bool = False


class KbEmbeddingConfigUpdate(BaseModel):
    provider_profile_id: str | None = None
    model: str = Field(min_length=1, max_length=120)
    dim: int = Field(ge=1, le=8192)


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


class TtsEngineOut(BaseModel):
    id: str
    label: str
    detail: str
    status: str
    downloaded_bytes: int = 0
    total_bytes: int = 0
    expected_bytes: int = 0
    speed_bps: float = 0.0
    eta_seconds: float | None = None
    message: str = ""
    # Fish Speech only: the source checkout is separate from the weights, so surface it
    # on its own (weights can be "installed" while the source is still missing).
    needs_source: bool = False
    source_ready: bool = False
    source_dir: str = ""


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None


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
    note: str = ""


class VoiceFromSpeakerRequest(BaseModel):
    asset_id: str
    speaker: str | None = None
    name: str = ""


class TtsConfigOut(BaseModel):
    engine: str
    python_path: str = ""
    source: str = "hf-mirror"
    fish_repo_dir: str = ""  # Fish Speech source checkout
    fish_model_dir: str = ""  # Fish Speech weights dir (contains codec.pth)
    worker_ready: bool = False  # an interpreter with the engine installed was found
    worker_python: str = ""  # the resolved interpreter path (for display)


class TtsConfigUpdate(BaseModel):
    engine: str = Field(pattern="^(f5-tts|fish-speech)$")
    python_path: str = ""
    source: str = Field(default="hf-mirror", pattern="^(hf|hf-mirror|modelscope)$")
    fish_repo_dir: str = ""
    fish_model_dir: str = ""


class AsrModelOut(BaseModel):
    id: str
    engine: str
    label: str
    detail: str
    status: str  # "installed" | "missing" | "downloading" | "failed"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    expected_bytes: int = 0
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


class GenerationModelOut(OrmModel):
    id: str
    provider: str
    kind: str
    model: str
    enabled: bool
    capabilities: dict
    adapter_available: bool


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
    source_asset_ids: list[str] = Field(default_factory=list)


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
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, pattern="^(image|video)$")


class GenerationSessionOut(OrmModel):
    id: str
    workspace_id: str
    title: str
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


class PluginOut(OrmModel):
    id: str
    name: str
    version: str
    enabled: bool
    manifest: dict


class PluginEnableRequest(BaseModel):
    enabled: bool


class PluginPermissionGrantOut(OrmModel):
    plugin_id: str
    permission: str
    granted: bool
    created_at: datetime
    updated_at: datetime


class PluginPermissionGrantUpdate(BaseModel):
    grants: dict[str, bool] = Field(default_factory=dict)


class PluginToolOut(BaseModel):
    plugin_id: str
    plugin_name: str
    tool_name: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)
    permissions: list = Field(default_factory=list)
    skills: list = Field(default_factory=list)


class PluginInvokeRequest(BaseModel):
    input: dict = Field(default_factory=dict)


class PluginInvocationOut(OrmModel):
    id: str
    plugin_id: str
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


class WorkflowRunRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class WorkflowNodeTypeOut(BaseModel):
    type: str
    label: str
    description: str
    category: str = ""  # 面板分组;空=通用组
    config: dict
    outputs: list[str]


class WorkflowAiEditRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    graph: dict | None = None
    profile_id: str | None = None


class WorkflowAiEditResponse(BaseModel):
    graph: dict
    summary: str = ""


class BrowserProfileOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    partition: str
    proxy: str | None = None
    enabled: bool
    last_used_at: datetime | None = None
    created_at: datetime
    # 若被发布账号绑定,回其平台/账号 id + 登录态(浏览器池页据此标注「发布账号」并显示登录状态、
    # 复用登录/复检动作);通用档案这些为 None。
    platform: str | None = None
    bound_account_id: str | None = None
    binding_status: str | None = None
    last_checked_at: datetime | None = None
    last_error: str | None = None


class BrowserProfileCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=160)
    proxy: str | None = None


class BrowserProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    proxy: str | None = None
    enabled: bool | None = None


class PublishPlatformOut(BaseModel):
    platform: str
    label: str
    description: str
    config: dict
    executor: str = "local"
    title_max: int = 300
    short_title: bool = False


class PublishAccountCreate(BaseModel):
    workspace_id: str
    platform: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    config: dict = Field(default_factory=dict)
    proxy: str | None = Field(default=None, max_length=300)


class PublishAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    config: dict | None = None
    enabled: bool | None = None
    # 空串 = 清除代理走直连;None = 不改。
    proxy: str | None = Field(default=None, max_length=300)


class PublishAccountOut(OrmModel):
    id: str
    workspace_id: str
    platform: str
    name: str
    config: dict
    enabled: bool
    proxy: str | None = None
    binding_status: str = "unknown"
    last_error: str | None = None
    last_checked_at: datetime | None = None
    profile_name: str | None = None
    created_at: datetime


class PublishCreate(BaseModel):
    workspace_id: str
    account_id: str
    asset_id: str
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=24)
    short_title: str = Field(default="", max_length=80)


class PublishTaskOut(BaseModel):
    id: str
    workspace_id: str
    account_id: str
    account_name: str
    platform: str
    asset_id: str
    asset_name: str
    title: str
    description: str
    tags: list[str]
    status: str
    error: str | None
    result: dict
    job_id: str | None
    created_at: datetime


class PublishCopyRequest(BaseModel):
    workspace_id: str
    asset_id: str | None = None
    brief: str = Field(default="", max_length=2000)
    profile_id: str | None = None


class PublishCopyResponse(BaseModel):
    title: str
    description: str
    tags: list[str]


class AgentSessionCreate(BaseModel):
    workspace_id: str
    project_id: str | None = None
    title: str = Field(default="新对话", max_length=200)
    adapter: str | None = Field(default=None, pattern="^(claude|pi)$")
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)


class AgentSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    #: 视频分析方式偏好:auto / native / frames。
    analysis_video_mode: str | None = None


class AgentSessionOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None
    title: str
    origin: str
    adapter: str
    provider_profile_id: str | None = None
    model: str | None = None
    analysis_video_mode: str = "auto"
    status: str
    created_at: datetime
    updated_at: datetime


class AgentMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    context: str | None = Field(default=None, max_length=4000)


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
    name: str = Field(default="Mibu 助手", max_length=160)
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


class ConfirmationOut(OrmModel):
    id: str
    workspace_id: str
    tool: str
    permission: str
    summary: str
    payload: dict
    status: str
    result: dict
    error: str | None
    requested_by: str
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


class KbDatasetCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class KbDatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    retrieval_mode: str | None = Field(default=None, pattern="^(fts|hybrid)$")
    top_k: int | None = Field(default=None, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    chunk_size: int | None = Field(default=None, ge=100, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1000)
    graph_enabled: bool | None = None


class KbDatasetOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    description: str
    retrieval_mode: str
    top_k: int
    score_threshold: float | None = None
    chunk_size: int
    chunk_overlap: int
    graph_enabled: bool
    created_at: datetime
    updated_at: datetime
    document_count: int = 0  # 列表附带,计算得出


class KbDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=400_000)
    source_type: str = Field(default="note", pattern="^(note|file|url)$")
    source_ref: str = Field(default="", max_length=600)
    tags: list[str] = Field(default_factory=list, max_length=24)


class KbDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, max_length=400_000)
    tags: list[str] | None = Field(default=None, max_length=24)


class KbUrlImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=600)


class KbDocumentOut(OrmModel):
    id: str
    workspace_id: str
    dataset_id: str
    title: str
    source_type: str
    source_ref: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    status: str
    error: str = ""
    chunk_count: int = 0
    char_count: int = 0
    created_at: datetime
    updated_at: datetime
    content: str | None = None  # 列表不带正文,详情才带


class KbChunkOut(OrmModel):
    id: str
    chunk_index: int
    text: str
    char_count: int = 0


class KbRetrievalTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0, le=1)


class KbGraphNode(BaseModel):
    id: str
    label: str
    kind: str  # document|entity
    ref: str | None = None  # document 节点的真实文档 id
    entity_type: str | None = None


class KbGraphEdge(BaseModel):
    source: str
    target: str
    weight: int = 1


class KbGraphOut(BaseModel):
    enabled: bool
    nodes: list[KbGraphNode] = Field(default_factory=list)
    edges: list[KbGraphEdge] = Field(default_factory=list)


class KbStatusOut(BaseModel):
    convert_engine: str
    vector_enabled: bool
    graph_enabled: bool
    embedding_model: str = ""


class KbSearchResultOut(BaseModel):
    document_id: str
    title: str
    source_type: str
    tags: list[str] = Field(default_factory=list)
    chunk_index: int
    snippet: str
    score: float = 0.0
    from_graph: bool = False


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
    total_tokens: int


class WorkspaceSummaryOut(BaseModel):
    """首页仪表数字。一次请求给全一屏,避免首页发 N 个列表请求做 .length 聚合。"""

    project_count: int
    asset_count: int
    sequence_count: int
    workflow_count: int
    kb_document_count: int
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
    usage_duration_seconds: float = 0
    usage_token_count: int = 0
    usage_daily: list[DailyUsageOut] = Field(default_factory=list)
    usage_token_daily: list[DailyUsageTokensOut] = Field(default_factory=list)
    usage_by_capability: dict[str, int] = Field(default_factory=dict)
    usage_by_provider: dict[str, int] = Field(default_factory=dict)
