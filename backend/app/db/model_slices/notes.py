"""Workspace-owned writing, separate from canvas layout and agent preferences."""
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (Index("idx_notes_workspace_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trashed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class NoteRevision(Base):
    """笔记的一版。**不可变**:修订号同时是乐观并发的基准、来源 / 画板文档格 / 引用链接钉住的那一版。"""

    __tablename__ = "note_revisions"
    note_id: Mapped[str] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: 怎么来的(见 note_types.NoteRevisionOrigin)。
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 替谁写的。智能体改的那一版记批准它的人;说不出是谁(老数据)时为空。
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: origin 是 restore 时:从第几版恢复的。
    restored_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 归在哪一组:这一组第一版的号。连续的手动编辑合成版本记录里的一项(见 domain/notes/history)。
    group_start: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 相对这一组之前那一版:新加 / 删掉的字数(不算空白)、标题改没改。
    chars_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chars_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
