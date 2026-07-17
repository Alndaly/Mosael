from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("idx_auth_sessions_user", "user_id"),)

    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("idx_projects_workspace_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    active_sequence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    sequences: Mapped[list["Sequence"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (Index("idx_assets_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="imported")
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    file_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    media_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Lut(Base):
    """A 3D color lookup table (.cube), uploaded per workspace and burned in with
    ffmpeg lut3d at export. Referenced from clip.effects.color.lut by id."""

    __tablename__ = "luts"
    __table_args__ = (Index("idx_luts_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    file_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class GeneratedAsset(Base):
    __tablename__ = "generated_assets"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (Index("idx_transcripts_asset", "asset_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    language: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="imported")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", order_by="TranscriptSegment.start_time"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (Index("idx_transcript_segments_transcript_start", "transcript_id", "start_time"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaker: Mapped[str | None] = mapped_column(String(80), nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")
    tokens: Mapped[list["TranscriptToken"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan", order_by="TranscriptToken.token_index"
    )


class TranscriptToken(Base):
    __tablename__ = "transcript_tokens"
    __table_args__ = (Index("idx_transcript_tokens_segment_index", "segment_id", "token_index"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    segment_id: Mapped[str] = mapped_column(ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False)
    token_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(String(120), nullable=False)

    segment: Mapped[TranscriptSegment] = relationship(back_populates="tokens")


class ClipTranscriptRef(Base):
    __tablename__ = "clip_transcript_refs"
    __table_args__ = (Index("idx_clip_transcript_refs_clip", "clip_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=True)


class Sequence(Base):
    __tablename__ = "sequences"
    __table_args__ = (Index("idx_sequences_project_updated", "project_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1920)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1080)
    fps: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    project: Mapped[Project] = relationship(back_populates="sequences")
    tracks: Mapped[list["Track"]] = relationship(back_populates="sequence", cascade="all, delete-orphan", order_by="Track.position")


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (Index("idx_tracks_sequence_position", "sequence_id", "position"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sequence: Mapped[Sequence] = relationship(back_populates="tracks")
    clips: Mapped[list["Clip"]] = relationship(back_populates="track", cascade="all, delete-orphan", order_by="Clip.timeline_start")


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (Index("idx_clips_sequence_track_start", "sequence_id", "track_id", "timeline_start"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    timeline_start: Mapped[float] = mapped_column(Float, nullable=False)
    src_in: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    src_out: Mapped[float] = mapped_column(Float, nullable=False)
    speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    gain: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    linked_clip_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    effects: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    track: Mapped[Track] = relationship(back_populates="clips")


class SequenceOperation(Base):
    __tablename__ = "sequence_operations"
    __table_args__ = (Index("idx_sequence_operations_sequence_created", "sequence_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    revision_before: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_after: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reverted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    undo_of: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class SequenceRevision(Base):
    __tablename__ = "sequence_revisions"
    __table_args__ = (Index("idx_sequence_revisions_sequence_revision", "sequence_id", "revision"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    render_plan_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("idx_jobs_workspace_status_updated", "workspace_id", "status", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (Index("idx_task_events_job_created", "job_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class Notification(Base):
    """站内通知:按用户投递,type 预留 team(协作申请)等扩展。"""

    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False, default="system")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ScheduledTaskRun(Base):
    __tablename__ = "scheduled_task_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    scheduled_task_id: Mapped[str] = mapped_column(ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Workflow(Base):
    """可视化工作流(Coze/Dify 式):graph 存节点+连线的 JSON,
    定时任务与智能体都以 workflow 为执行单元。"""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class BatchRun(Base):
    """批量执行:同一工作流 × N 组参数(计划 §13/批量混剪)。
    父 job 聚合进度,每组参数一个子 workflow job。"""

    __tablename__ = "batch_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    params_list: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    item_job_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class PublishAccount(Base):
    """发布目标账号(计划 §6.9 publish_accounts):platform 决定适配器,
    config 是该平台的连接配置(目录路径 / webhook URL / 未来的 OAuth)。"""

    __tablename__ = "publish_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 该账号内嵌视图走的代理(矩阵防关联):http(s)://[user:pass@]host:port 或 socks5://host:port。
    # 空 = 直连。执行器把它喂给该账号 session 分区的 setProxy。
    proxy: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # 浏览器平台的登录态(老版 BINDING_STATUSES):unknown/checking/bound/login_required/...
    binding_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 登录检测时执行器回写的平台侧昵称(矩阵运营:一眼分清哪个号)。
    profile_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class PublishTask(Base):
    """一次发布(计划 §6.9 publish_tasks):成片素材 + 文案元数据 + 目标账号,
    执行状态挂在任务总线 job 上。"""

    __tablename__ = "publish_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("publish_accounts.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # 视频号等平台的短标题;浏览器平台任务的富状态(老版 TASK_STATUSES 词汇)。
    short_title: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderProfile(Base):
    """A user-configured AI provider account. Multiple profiles per vendor
    are allowed (e.g. two OpenAI-compatible endpoints with different keys)."""

    __tablename__ = "provider_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor: Mapped[str] = mapped_column(String(60), nullable=False)  # alibaba|bytedance|openai|moonshot|minimax|openai-compatible|...
    base_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)
    default_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Credential(Base):
    __tablename__ = "credentials"

    provider: Mapped[str] = mapped_column(String(80), primary_key=True)
    secret: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class GenerationModel(Base):
    __tablename__ = "generation_models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (Index("idx_agent_sessions_ws_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新对话")
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="ui")  # ui | feishu
    external_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    adapter: Mapped[str] = mapped_column(String(40), nullable=False, default="claude")
    adapter_session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="idle")  # idle | running
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="AgentMessage.created_at"
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (Index("idx_agent_messages_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    session: Mapped[AgentSession] = relationship(back_populates="messages")


class FeishuBot(Base):
    __tablename__ = "feishu_bots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="Mibu 助手")
    app_id: Mapped[str] = mapped_column(String(120), nullable=False)
    app_secret: Mapped[str] = mapped_column(String(200), nullable=False)
    capability: Mapped[str] = mapped_column(String(24), nullable=False, default="editor")  # readonly|editor|full
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="offline")  # offline|connecting|online|error
    status_detail: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ToolConfirmation(Base):
    __tablename__ = "tool_confirmations"
    __table_args__ = (Index("idx_tool_confirmations_ws_status", "workspace_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    permission: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False, default="external-agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Plugin(Base):
    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PluginPermissionGrant(Base):
    __tablename__ = "plugin_permission_grants"

    plugin_id: Mapped[str] = mapped_column(ForeignKey("plugins.id", ondelete="CASCADE"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(120), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginInvocation(Base):
    __tablename__ = "plugin_invocations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    plugin_id: Mapped[str] = mapped_column(ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class KbDocument(Base):
    """知识库文档(计划 §6.9):正文 markdown 直接入库,检索走 kb_chunks 的 FTS。"""

    __tablename__ = "kb_documents"
    __table_args__ = (Index("idx_kb_documents_workspace_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="note")  # note|file|url
    source_ref: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")  # ready|error
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    chunks: Mapped[list["KbChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="KbChunk.chunk_index"
    )


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (Index("idx_kb_chunks_document", "document_id", "chunk_index"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped[KbDocument] = relationship(back_populates="chunks")
