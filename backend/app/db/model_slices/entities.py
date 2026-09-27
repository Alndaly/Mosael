"""资产库(ADR 0027):人物、场景、道具 —— 「一个有名字的东西」,参考图是素材库里的素材。

表名是 `entities` 不是 `assets`:`assets` 已经是素材表(一张图、一段视频),界面上这一种叫「资产」。

资产**归工作区,不挂项目**:同一个角色常常跨项目用,归类靠标签。参考图不复制文件,只引用素材行
(`entity_references`);删素材时引用行随外键一起走,资产少一张参考图,并在 `lost_references` 上记一笔
「少了哪一张」,详情页据此提示(见 domain/entities 的 forget_asset)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (Index("idx_entities_workspace_kind", "workspace_id", "kind", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: `character` / `location` / `prop`(见 domain/entities/catalog.KINDS)。
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 变体的母体。变体只有一层 —— 「张三 · 冬装」下面不再挂「张三 · 冬装 · 雪地」。
    #: 母体删掉时外键兜底把变体一起带走;界面和接口在那之前会先问(见 domain/entities.delete_entity)。
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: 给人看的一段描述。
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 给模型看的一段提示词描述:外貌、服装、材质……生成时 `@` 到它就拼进提示词。
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 封面。素材删了就空着,界面退回第一张参考图。
    cover_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    #: 按种类的专有字段(人物的音色、人偶颜色、真人与授权声明;场景的 3D 场景、时间;道具的 3D 模型)。
    #: 形状由 domain/entities/catalog 的 normalize_attributes 管。
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: 随素材一起删掉的那几张参考图:`[{name, role, at}]`。只为了在详情页上说一声「少了哪一张」,
    #: 用户看过之后可以清掉。
    lost_references: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class EntityReference(Base):
    """一张参考图:哪个资产、哪份素材、什么角度 / 用途、排第几。同一份素材在一个资产里只出现一次。"""

    __tablename__ = "entity_references"

    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True, index=True)
    #: 角度 / 用途,词表见 domain/entities/catalog.ROLES。
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
