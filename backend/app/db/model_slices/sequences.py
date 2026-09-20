"""时间线:序列、轨、片段,以及每一次编辑和它的逆操作(撤销)。

sequence_operations 存的是**操作**而不是快照:撤销要的是逆操作,而回到某一版另有 revisions。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.db.model_base import new_id, now

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
    # 改画幅:{fill_mode: cover|contain|blur, scale, x, y};空 = 默认 cover 无平移缩放
    reframe: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    subtitle_style: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    #: 跨切片的关系按注册表里的类名解析,不 import ——  真去 import 就是 sequences ⇄ projects 的循环。
    project: Mapped["Project"] = relationship(back_populates="sequences")  # noqa: F821
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
    solo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duck: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 有其它音频时压低本轨
    #: 这条轨**是干什么的**,空 = 一条普通轨。目前只有 "dub"(字幕配音落地的地方)。
    #: 不靠名字认:名字是给人看的、可以随便改,而"再配一次要放回同一条轨"必须认得准。
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="")

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
    #: 素材被删掉之后留下的**脱机占位**:`{asset_id, name, kind, duration}`。素材还在时恒为 None。
    #:
    #: 为什么要留一份快照而不是让 asset_id 悬空:`asset_id` 上的外键是 RESTRICT,悬空根本存不下;
    #: 而单把 asset_id 置空的话,这一段就和「文字片段」(同样没有 asset_id)长得一模一样 ——
    #: 界面分不出"这里本来有东西、现在没了"和"这里本来就是一行字"。名字也要一起留:脱机占位
    #: 上写不出原来是哪个文件的话,用户没法把它对回去。
    offline_asset: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=None)
    effects: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 片段变换(缩放/位移/旋转/透明度);空 = 恒等。{scale,x,y,rotation,opacity}
    transform: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    track: Mapped[Track] = relationship(back_populates="clips")
    #: 只为读**素材类型**用(界面要判断"这一段转不转得了")。同一条序列里同一个素材反复出现,
    #: 身份映射会把它们收敛成一次查询,所以这里不值得为它加急切加载。
    asset: Mapped["Asset | None"] = relationship(lazy="selectin")  # noqa: F821 —— 同上,媒体切片里的类

    @property
    def asset_kind(self) -> str:
        """这一段的媒体类型。脱机片段回报**它原来的**类型 —— 轨道还是那条轨道。"""
        if self.asset is not None:
            return self.asset.kind
        if self.offline_asset:
            return str(self.offline_asset.get("kind") or "")
        return ""

    @property
    def offline(self) -> bool:
        """素材已被删除。和"这是一行文字"不是一回事 —— 两者的 asset_id 都是空。"""
        return bool(self.offline_asset)


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
