"""领域错误 → HTTP 状态码:**只在这一张表里翻**。

领域层抛的是领域错误(带文案 key,见 `core/i18n.LocalizedError`),不认识 HTTP —— 同一个用例还会被
智能体工具(`mcp_server._use_case`)、工作流执行器、飞书回调这些非 HTTP 入口调用。此前每条路由各自
先 catch 领域错误、再换成一个 HTTPException,同一种错误在不同路由里翻成不同的码,漏翻的就成了 500;
智能体工具层还另有一套「把 HTTPException 拼成 `"403: …"`」的借道(`_route`,已删)。

现在:路由不再逐个 catch,错误原样冒到边界,由这张表翻一次。Starlette 按异常类的 MRO 找处理器,
所以**子类登记的码优先于基类**(例如 `HostFileNotAllowed` 是 `PermissionDenied`,走 403)。

码是 `None` 的,用错误自己声明的 `status`(那几个领域按子类区分 404 / 409 / 422 / 502)。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.ai.providers.contracts.denoise import DenoiseError
from app.ai.providers.contracts.separation import SeparationError
from app.ai.runtime.errors import RuntimeSetupError
from app.ai.sidecar.pi_client import SidecarError
from app.core.outbound_guard import AllowlistError
from app.domain.accounts import (
    AccountError,
    AccountNotFound,
    LastDeploymentAdmin,
    ResetOwnPassword,
    SignupClosed,
    UsernameTaken,
    WrongPassword,
)
from app.domain.agent.autopilot import PermissionModeError
from app.domain.agent.host import HostError
from app.domain.agent.places import PlaceError
from app.domain.agent.questions import QuestionError
from app.domain.agent.skills.catalog import SkillDomainError
from app.domain.agent.use_cases import NothingToSay, SpeechFailed, UnknownConnection
from app.domain.analysis.service import AnalysisError
from app.domain.asr import AsrModelNotInstalled, UnknownAsrModel
from app.domain.assets.deletion import AssetNotDeletable
from app.domain.assets.frames import AssetFrameError
from app.domain.assets.from_url import UrlImportError
from app.domain.assets.importer import AssetFileTypeError
from app.domain.assets.masks import MaskAssetError
from app.domain.assets.project_scope import AssetProjectError
from app.domain.assets.scrub.engine import ScrubError
from app.domain.assets.video_gif import VideoGifError
from app.domain.blender.bridge import BlenderDomainError
from app.domain.browser import BrowserDomainError
from app.domain.collaboration import CommentOwnershipError
from app.domain.denoise_defaults import DenoiseEngineNotInstalled, DenoiseEngineNotReady, UnknownDenoiseEngine
from app.domain.documents.reading import DocumentReadError
from app.domain.entities.library import EntityDomainError
from app.domain.fonts import FontError
from app.domain.generation.prompt_optimizer import PromptOptimizeError
from app.domain.generation.resolution import GenerationResolutionError
from app.domain.host_files import HostFileError
from app.domain.jobs import JobError
from app.domain.luts import LutError
from app.domain.media_tools import FfmpegPathError
from app.domain.media_tools_install import MediaToolError
from app.domain.members import MemberError
from app.domain.notes import NoteDomainError
from app.domain.notifications.use_cases import NoNotifiableMembers
from app.domain.permissions import NotVisible, PermissionDenied
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.oauth import PluginOAuthError
from app.domain.providers.choices import UnknownCapability
from app.domain.providers.connections import ConnectionConfigError
from app.domain.publish import PublishDomainError
from app.domain.publish.use_cases import NotInWorkspace
from app.domain.scenes.operations import SceneDomainError
from app.domain.scheduler.operations import SchedulerBusy
from app.domain.sequences.errors import SequenceNotFound
from app.domain.sharing import NotManageableError, NotUsableError, SharingError
from app.domain.shots.breakdowns import ShotBreakdownError
from app.domain.translate import TranslateError
from app.domain.triggers.use_cases import TriggerDomainError
from app.domain.voices.agent_voice import AgentVoiceUnavailable
from app.domain.voices.clip_audio import ClipAudioError
from app.domain.voices.defaults import UnknownVoiceEngine, VoiceEngineNotReady, VoiceMissing
from app.domain.voices.subtitle_dub import DubError
from app.domain.voices.transcription import ASRError, DictationTooLong
from app.domain.workflows.field_options import FieldOptionsError
from app.domain.workflows.revisions import WorkflowRevisionError
from app.integrations.feishu.client import FeishuError
from app.media.listening.decode import ListeningError
from app.media.still import StillError
from app.media.subtitle_files import SubtitleFileError

#: 用错误自己声明的 `status`。
OWN_STATUS = None

STATUS_BY_ERROR: dict[type[Exception], int | None] = {
    # 授权:不是成员给 404 而不是 403 —— 403 等于告诉他「这个 id 存在」。
    NotVisible: 404,
    PermissionDenied: 403,
    # 别人的档案 / 发布账号:没共享给你、或者你不是主人。
    NotUsableError: 403,
    NotManageableError: 403,
    # 请求本身说不通(路径不对、动作失败、分析不了、没有能通知的人)。
    HostFileError: 422,
    BrowserDomainError: 422,
    AnalysisError: 422,
    NoNotifiableMembers: 422,
    UnknownCapability: 404,
    # 对话正忙(在跑、在压缩)—— 现在不行,等一下可以。
    HostError: 409,
    # 翻译引擎(上游)没给结果,不是调用方的请求有错。
    TranslateError: 502,
    # 此前各路由逐个 catch 再翻成固定码的那些(全仓都翻成同一个码),收到这里。
    AssetFrameError: 400,
    MaskAssetError: 400,
    PluginDomainError: 400,
    StillError: 400,
    WrongPassword: 401,
    CommentOwnershipError: 403,
    SignupClosed: 403,
    AccountNotFound: 404,
    FieldOptionsError: 404,
    NotInWorkspace: 404,
    SequenceNotFound: 404,
    SharingError: 404,
    UnknownAsrModel: 404,
    UnknownDenoiseEngine: 404,
    UnknownVoiceEngine: 404,
    WorkflowRevisionError: 404,
    AccountError: 409,
    AgentVoiceUnavailable: 409,
    AsrModelNotInstalled: 409,
    DenoiseEngineNotInstalled: 409,
    DenoiseEngineNotReady: 409,
    JobError: 409,
    LastDeploymentAdmin: 409,
    MemberError: 409,
    ResetOwnPassword: 409,
    RuntimeSetupError: 409,
    SchedulerBusy: 409,
    UsernameTaken: 409,
    VoiceEngineNotReady: 409,
    VoiceMissing: 409,
    DictationTooLong: 413,
    ASRError: 422,
    AllowlistError: 422,
    ClipAudioError: 422,
    ConnectionConfigError: 422,
    DenoiseError: 422,
    DubError: 422,
    FeishuError: 422,
    FfmpegPathError: 422,
    FontError: 422,
    GenerationResolutionError: 422,
    ListeningError: 422,
    LutError: 422,
    MediaToolError: 422,
    NothingToSay: 422,
    PermissionModeError: 422,
    PlaceError: 422,
    PluginOAuthError: 422,
    PromptOptimizeError: 422,
    PublishDomainError: 422,
    QuestionError: 422,
    ScrubError: 422,
    SeparationError: 422,
    ShotBreakdownError: 422,
    SpeechFailed: 422,
    SubtitleFileError: 422,
    TriggerDomainError: 422,
    UnknownConnection: 422,
    UrlImportError: 422,
    VideoGifError: 422,
    SidecarError: 502,
    # 这些领域按子类声明自己的码。
    DocumentReadError: OWN_STATUS,
    NoteDomainError: OWN_STATUS,
    AssetProjectError: OWN_STATUS,
    AssetFileTypeError: OWN_STATUS,
    AssetNotDeletable: OWN_STATUS,
    SkillDomainError: OWN_STATUS,
    SceneDomainError: OWN_STATUS,
    EntityDomainError: OWN_STATUS,
    BlenderDomainError: OWN_STATUS,
}


def _responder(status: int | None) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def respond(_request: Request, exc: Exception) -> JSONResponse:
        code = status if status is not None else int(exc.status)  # type: ignore[attr-defined]  —— 这一档的错误都声明了 status
        return JSONResponse(status_code=code, content={"detail": str(exc) or "Not found"})

    return respond


def install_domain_error_handlers(app: FastAPI) -> None:
    for error_type, status in STATUS_BY_ERROR.items():
        app.add_exception_handler(error_type, _responder(status))
