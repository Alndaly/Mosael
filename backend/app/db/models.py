"""ORM 的**唯一装配入口**(棘轮:tests/test_domain_assembly_entries.py)。

模型按领域切在 `app/db/model_slices/` 下,这里只把它们收到一处:调用方一律
`from app.db.models import X`,继续切文件不会扩散到全仓(见 docs/ARCHITECTURE.md
「文件布局可以按领域切片,但切片不是公共 Interface」)。

这个文件里**不定义任何东西** —— 它一旦开始长自己的类或常量,切片就又变回了半个入口。
import 顺序不重要:外键按表名解析,SQLAlchemy 在 configure 时才连起来。
棘轮:tests/test_domain_assembly_entries.py。
"""

from __future__ import annotations

#: 建行要用的两样,和模型一起从这个入口出去 —— 调用方不必知道它们住在 model_base 里。
from app.core.db import Base  # noqa: F401
from app.db.model_base import new_id, now  # noqa: F401

from app.db.model_slices.jobs import Job, TaskEvent  # noqa: E402,F401
from app.db.model_slices.notifications import Notification  # noqa: E402,F401
from app.db.model_slices.scheduler import ScheduledTask, ScheduledTaskRun  # noqa: E402,F401
from app.db.model_slices.workflows import Workflow, WorkflowRevision  # noqa: E402,F401
from app.db.model_slices.boards import Board  # noqa: E402,F401
from app.db.model_slices.notes import Note, NoteRevision  # noqa: E402,F401
from app.db.model_slices.collaboration import ActivityEvent, Comment, CommentMention, Review  # noqa: E402,F401
from app.db.model_slices.publish import PublishAccount, PublishTask  # noqa: E402,F401
from app.db.model_slices.browser import BrowserAction, BrowserProfile, BrowserSession  # noqa: E402,F401
from app.db.model_slices.scenes import Scene3D, Scene3DRevision, Scene3DModel  # noqa: E402,F401
from app.db.model_slices.identity import AuthSession, OAuthIdentity, RegistrationInvite, User, Workspace, WorkspaceInvitation, WorkspaceMember  # noqa: E402,F401
from app.db.model_slices.sharing import ResourceShare  # noqa: E402,F401
from app.db.model_slices.projects import Project  # noqa: E402,F401
from app.db.model_slices.media import Asset, Font, Lut  # noqa: E402,F401
from app.db.model_slices.transcripts import ClipTranscriptRef, Transcript, TranscriptSegment, TranscriptToken  # noqa: E402,F401
from app.db.model_slices.sequences import Clip, Sequence, SequenceOperation, SequenceRevision, Track  # noqa: E402,F401
from app.db.model_slices.voices import AgentVoicePref, Voice  # noqa: E402,F401
from app.db.model_slices.providers import GenerationCapabilityDeclaration, GenerationCapabilityProfile, ProviderCredential, ProviderDefault, ProviderModel, ProviderProfile  # noqa: E402,F401
from app.db.model_slices.usage import ProviderPricingRule, ProviderUsageEvent  # noqa: E402,F401
from app.db.model_slices.runtime_config import AiRuntimeConfig, DeploymentConfig, NetworkConfig, TtsConfig  # noqa: E402,F401
from app.db.model_slices.generation import GeneratedAsset, GenerationJob, GenerationSession  # noqa: E402,F401
from app.db.model_slices.agent import SESSION_GROUP_KINDS, AgentMemory, AgentMessage, AgentQuestion, AgentSession, SessionGroup, ToolConfirmation  # noqa: E402,F401
from app.db.model_slices.feishu import FeishuBindCode, FeishuBinding, FeishuBot  # noqa: E402,F401
from app.db.model_slices.plugins import PluginCapability, PluginCredential, PluginInstance, PluginInvocation, PluginPackage, PluginPermissionGrant  # noqa: E402,F401
