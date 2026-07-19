from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthCredentials(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=4, max_length=200)


class UserOut(OrmModel):
    id: str
    username: str


class AuthOut(BaseModel):
    token: str
    user: UserOut


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
    role: str
    perms: dict[str, bool]  # effective perms (role defaults + overrides)
    is_self: bool = False


class MembersOut(BaseModel):
    members: list[WorkspaceMemberOut]
    my_role: str
    perm_keys: list[str]  # every togglable perm, for the override UI
    role_defaults: dict[str, dict[str, bool]]  # role → its default perm set


class AddMemberRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    # Required only when creating a brand-new account; ignored when adding an existing user.
    password: str = Field(default="", max_length=200)
    role: str = Field(default="editor", pattern="^(admin|editor|viewer)$")


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


class MoveClipRequest(BaseModel):
    timeline_start: float
    track_id: str | None = None
    ripple: bool = False


class TrimClipRequest(BaseModel):
    timeline_start: float
    src_in: float
    src_out: float


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


class SetClipTransformRequest(BaseModel):
    transform: dict = Field(default_factory=dict)  # {scale,x,y,rotation,opacity};后端按范围钳制


class InsertTextClipRequest(BaseModel):
    track_id: str
    text: str = Field(min_length=1, max_length=500)
    timeline_start: float = 0.0
    duration: float = Field(default=2.0, gt=0)


class SetClipTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


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


class AnalyzeAssetResponse(BaseModel):
    answer: str
    provider: str
    model: str
    frames: int


class ProviderProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    vendor: str = Field(min_length=1, max_length=60)
    api_key: str = Field(min_length=1, max_length=500)
    base_url: str = Field(default="", max_length=300)
    default_model: str = Field(default="", max_length=120)


class ProviderProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: str | None = Field(default=None, min_length=1, max_length=500)
    base_url: str | None = Field(default=None, max_length=300)
    default_model: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None


class ProviderProfileOut(OrmModel):
    id: str
    name: str
    vendor: str
    base_url: str
    default_model: str
    enabled: bool
    created_at: datetime
    key_hint: str = ""


class ProviderDefaultOut(BaseModel):
    capability: str
    provider_profile_id: str | None = None
    model: str = ""


class ProviderDefaultUpdate(BaseModel):
    provider_profile_id: str | None = None
    model: str = Field(default="", max_length=120)


class KbEmbeddingConfigOut(BaseModel):
    provider_profile_id: str | None = None
    model: str = ""
    dim: int = 0
    enabled: bool = False


class KbEmbeddingConfigUpdate(BaseModel):
    provider_profile_id: str | None = None
    model: str = Field(min_length=1, max_length=120)
    dim: int = Field(ge=1, le=8192)


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
    base_url: str = ""
    default_model: str = ""
    capabilities: str = ""


class CredentialSetRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    secret: str = Field(min_length=1, max_length=500)


class CredentialStatusOut(BaseModel):
    provider: str
    configured: bool
    hint: str = ""


class GenerationModelOut(OrmModel):
    id: str
    provider: str
    kind: str
    model: str
    enabled: bool
    capabilities: dict


class GenerationCreate(BaseModel):
    workspace_id: str
    project_id: str | None = None
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(image|video)$")
    prompt: str = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)
    source_asset_ids: list[str] = Field(default_factory=list)


class GenerationJobOut(OrmModel):
    id: str
    workspace_id: str
    job_id: str
    provider: str
    model: str
    kind: str
    request: dict
    result_asset_id: str | None


class GenerationCreateResponse(BaseModel):
    generation: GenerationJobOut
    job: JobOut


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
    config: dict
    outputs: list[str]


class WorkflowAiEditRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    graph: dict | None = None
    profile_id: str | None = None


class WorkflowAiEditResponse(BaseModel):
    graph: dict
    summary: str = ""


class BatchCreate(BaseModel):
    workspace_id: str
    workflow_id: str
    name: str = Field(min_length=1, max_length=180)
    params_list: list[dict] = Field(min_length=1, max_length=200)


class BatchItemOut(BaseModel):
    index: int
    params: dict
    job_id: str | None
    status: str
    progress: float
    error: str | None


class BatchOut(BaseModel):
    id: str
    workspace_id: str
    workflow_id: str
    name: str
    status: str
    progress: float
    job_id: str | None
    created_at: datetime
    items: list[BatchItemOut] = Field(default_factory=list)


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
    adapter: str | None = Field(default=None, pattern="^(claude|opencode|pi)$")
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)


class AgentSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)


class AgentSessionOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None
    title: str
    origin: str
    adapter: str
    provider_profile_id: str | None = None
    model: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class AgentMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


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


class PromptSkillOut(BaseModel):
    """文件型智能体技能(skills/<id>/SKILL.md);body 仅在单独获取时返回。"""

    id: str
    name: str
    description: str = ""
    source: str = "user"
    body: str | None = None


class AgentManifestOut(BaseModel):
    app: str
    version: str
    openapi_url: str
    skills: list[AgentSkillOut]
