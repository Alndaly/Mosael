"""转写:一段音视频说了什么,以及它和时间线片段的关联。

三层(整篇 / 句 / 词)分开存是因为字幕要按句显示、搜索要按词定位,而重排一次只动最上面那层。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.db.model_base import new_id, now

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
