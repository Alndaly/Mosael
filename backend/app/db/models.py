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
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
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


class Plugin(Base):
    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


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
