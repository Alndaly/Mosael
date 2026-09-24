"""请求/响应体的**唯一装配入口**(棘轮:tests/test_domain_assembly_entries.py)。

schema 按领域切在这个包下的各个文件里,这里只把它们收到一处:路由一律
`from app.api.schemas import X`,继续切文件不会扩散到全仓(见 docs/ARCHITECTURE.md
「文件布局可以按领域切片,但切片不是公共 Interface」)。

这个文件里**不定义任何东西** —— 它一旦开始长自己的类,切片就又变回了半个入口。
"""

from __future__ import annotations

from app.api.schemas.base import ApiModel, CostAmountOut, OrmModel  # noqa: F401
from app.api.schemas.agent import AgentCompactOut, AgentContextOut, AgentContextPart, AgentManifestOut, AgentMemoryCreate, AgentMemoryOut, AgentMemoryUpdate, AgentMessageCreate, AgentMessageOut, AgentPendingView, AgentPlanUpdate, AgentQuestionAnswer, AgentQuestionCreate, AgentQuestionItem, AgentQuestionOption, AgentQuestionOut, AgentReferenceIn, AgentSessionCreate, AgentSessionOut, AgentSessionUpdate, AgentSkillOut, AgentStreamEvent, ConfirmationCreate, ConfirmationOut, SessionGroupCreate, SessionGroupOut, SessionGroupUpdate  # noqa: F401
from app.api.schemas.boards import BoardCreate, BoardGenerate, BoardOut, BoardSpeak, BoardTrim, BoardUpdate, BoardWrite  # noqa: F401
from app.api.schemas.browser import BrowserProfileCreate, BrowserProfileOpened, BrowserProfileOut, BrowserProfileUpdate  # noqa: F401
from app.api.schemas.collaboration import ActivityOut, ActorOut, CanvasCommentAnchor, CommentAnchorUpdate, CommentContentUpdate, CommentCreate, CommentOut  # noqa: F401
from app.api.schemas.dashboard import AdminOverviewOut, DailyActivityOut, DailyPublishOut, DailyUsageOut, DailyUsageTokensOut, DaySeriesPoint, UnpricedUsageOut, UserSpendPoint, WorkspaceSummaryOut  # noqa: F401
from app.api.schemas.feishu import FeishuBindCodeOut, FeishuBindingOut, FeishuBotCreate, FeishuBotOut, FeishuBotUpdate, FeishuOnboardingOut  # noqa: F401
from app.api.schemas.generation import GenerationCreate, GenerationCreateResponse, GenerationJobOut, GenerationModelOut, GenerationOptionOut, GenerationSessionCreate, GenerationSessionOut, GenerationSessionUpdate, PromptOptimizeRequest, PromptOptimizeResponse, SourceAssetRef  # noqa: F401
from app.api.schemas.identity import AdminUserOut, AuthCredentials, AuthOut, BootstrapOut, DeploymentAdminUpdate, InvitationListOut, InvitationOut, InviteCreate, InviteMemberRequest, MembersOut, PasswordUpdate, RegisterCredentials, RenameRequest, SetRoleRequest, UserOut, UserProfileUpdate, WorkspaceCreate, WorkspaceMemberOut, WorkspaceOut  # noqa: F401
from app.api.schemas.jobs import JobKindCatalogOut, JobKindOut, JobOut, TaskEventOut  # noqa: F401
from app.api.schemas.media import AnalyzeAssetRequest, AnalyzeAssetResponse, AssetCreate, AssetFrameRequest, AssetOut, AssetUpdate, DenoiseAssetRequest, FontOut, LocalImportRequest, LutOut, LutUpdate, RemoteEntryOut, SequenceFrameRequest, UrlImportItem, UrlImportRequest, UrlProbeRequest, UrlProbeResponse, UrlSupportResponse, VideoToGifRequest  # noqa: F401
from app.api.schemas.notes import NoteAppend, NoteCreate, NoteOut, NoteReferenceOut, NoteRestore, NoteUpdate  # noqa: F401
from app.api.schemas.notifications import NotificationListOut, NotificationOut, NotifyRequest  # noqa: F401
from app.api.schemas.plugins import AssetLinkStorageOption, AssetLinkStorageOut, AssetLinkStorageUpdate, PluginCapabilityUpdate, PluginCredentialOut, PluginCredentialUpdate, PluginEnableRequest, PluginFieldOut, PluginInstallPreview, PluginInstallRequest, PluginInstanceCreate, PluginInstanceOut, PluginInstanceUpdate, PluginInvocationOut, PluginInvokeRequest, PluginMarketEntry, PluginOAuthCode, PluginPackageOut, PluginPermissionGrantOut, PluginPermissionGrantUpdate, PluginToolOut, PluginToolStateOut  # noqa: F401
from app.api.schemas.projects import ProjectCreate, ProjectOut, ProjectWithStatsOut  # noqa: F401
from app.api.schemas.providers import CapabilityModelOut, CapabilityProfileFieldOut, CapabilityProfileSchemaOut, GenerationCapabilityProfileCreate, GenerationCapabilityProfileOut, GenerationCapabilityProfileUpdate, OAuthAnswerIn, OAuthLoginOut, OAuthPromptOut, PricingPrefillOut, ProviderCredentialIn, ProviderCredentialOut, ProviderDefaultOut, ProviderDefaultUpdate, ProviderHealthOut, ProviderModelOut, ProviderModelUpdate, ProviderPricingRuleCreate, ProviderPricingRuleOut, ProviderPricingRuleUpdate, ProviderProfileCreate, ProviderProfileOut, ProviderProfileUpdate, ProviderQuotaMetricOut, ProviderQuotaOut, ProviderUsageEventOut, VendorFieldOut, VendorPresetOut  # noqa: F401
from app.api.schemas.publish import PublishAccountCreate, PublishAccountOut, PublishAccountUpdate, PublishCopyRequest, PublishCopyResponse, PublishCreate, PublishOptionChoice, PublishOptionSpec, PublishPlatformOut, PublishTaskOut, PublishedPostOut  # noqa: F401
from app.api.schemas.runtime_config import AiRuntimeConfigOut, AiRuntimeConfigUpdate, AsrModelOut, DenoiseEngineOut, InstallSourceOut, InstallSourceUpdate, NetworkConfigOut, NetworkConfigUpdate, SeparationEngineOut, TtsConfigOut, TtsConfigUpdate, TtsEngineChoiceOut, TtsEngineOut  # noqa: F401
from app.api.schemas.scenes import SceneCreate, SceneOperations, SceneOut, SceneReferenceOut, SceneReferenceRequest, SceneUpdate  # noqa: F401
from app.api.schemas.scheduler import RunScheduledTaskResponse, ScheduledTaskCreate, ScheduledTaskOut, ScheduledTaskRunOut, ScheduledTaskUpdate  # noqa: F401
from app.api.schemas.sequences import AddTrackRequest, ClipIdsRequest, ClipMoveEntry, ClipOut, ClipPointSplitsRequest, ClipRangeCutsRequest, ClipTextEntry, CutClipRangeRequest, CutClipRangesBatchRequest, CutClipRangesRequest, ExportRequest, GenerateSubtitlesRequest, InsertClipRequest, InsertTextClipRequest, MoveClipRequest, MoveClipsBatchRequest, MoveTrackRequest, SequenceCreate, SequenceOut, SetClipEffectsRequest, SetClipGainRequest, SetClipSpeedRequest, SetClipTextRequest, SetClipTextsRequest, SetClipTransformRequest, SetSequenceReframeRequest, SetSubtitleStyleRequest, SetTrackStateRequest, SplitClipPointsBatchRequest, SplitClipPointsRequest, SplitClipRequest, SubtitleCueInput, TrackOut, TranslateRequest, TranslateResponse, TrimClipRequest  # noqa: F401
from app.api.schemas.transcripts import TranscriptAttachRequest, TranscriptOut, TranscriptSegmentIn, TranscriptSegmentOut, TranscriptTokenIn, TranscriptTokenOut  # noqa: F401
from app.api.schemas.voices import AgentSpeechRequest, AgentVoiceOut, AgentVoiceUpdate, EngineSynthesizeRequest, PodcastRequest, SubtitleDubRequest, SynthesizeRequest, TtsVoiceOut, VoiceFromSpeakerRequest, VoiceOut, VoiceUpdate  # noqa: F401
from app.api.schemas.workflows import WorkflowAiEditRequest, WorkflowAiEditResponse, WorkflowCreate, WorkflowFieldOptionOut, WorkflowImportRequest, WorkflowNodeTypeOut, WorkflowOut, WorkflowRevisionDetailOut, WorkflowRevisionOut, WorkflowRunRequest, WorkflowTemplateOut, WorkflowUpdate  # noqa: F401
