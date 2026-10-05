"""素材库里的文件行:素材本身,以及调色 LUT 和字体这两类随工作区走的资源。

它们共用一套「文件落盘 + 行记位置」的形状(media/paths 决定 file_key 怎么算),
删行时文件要显式清(CASCADE 管不到磁盘)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, validates
from app.core.collation import name_sort_key
from app.core.db import Base
from app.db.model_base import new_id, now

class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("idx_assets_workspace_created", "workspace_id", "created_at"),
        #: 素材库的列表按「工作区 + 是不是中间产物」筛、按导入时间排(见 domain/assets/listing)。
        Index("idx_assets_workspace_intermediate_created", "workspace_id", "intermediate", "created_at"),
        #: 同上,按名称排(排序键 + id,见 name_sort_key)。
        Index("idx_assets_workspace_intermediate_name", "workspace_id", "intermediate", "name_sort_key", "id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="imported")
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    #: 按名称排序用的键:汉字换成拼音、不分大小写和重音……,和此前前端的中文排序同一个顺序(见 core/collation)。
    #: **只在下面 `_name_sort_key` 那一处算**:新建、改名、导入都是给 `name` 赋值,赋值时它跟着变,调用方不用记得填。
    #: 绕过 ORM 直接 `UPDATE assets SET name` 会让它变旧 —— 别那么写名字。
    name_sort_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    file_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    media_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: 这份素材是从哪几份、经过什么操作做出来的:`[{asset_id, op}]`(见 domain/assets/lineage)。导入的是空的。
    derived_from: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: 含 AI 生成 / 合成的内容:自己是 AI 做的,或任一出处含 AI。登记时定下(继承),导出按它加标识。
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: 中间产物:某道工序逐条做出来的零件是哪一种(逐句配音的一句……,取值见 domain/assets/intermediates),
    #: 素材库默认不列;空串 = 素材库里的正常素材。登记时由做它的那道工序说。
    intermediate: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    @validates("name")
    def _name_sort_key(self, _field: str, name: str) -> str:
        self.name_sort_key = name_sort_key(name)
        return name


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


class Font(Base):
    """A subtitle font file uploaded per workspace. Referenced from sequence.subtitle_style
    by id; the preview loads it over HTTP as an @font-face and export points libass at its
    directory, so preview and burn-in resolve the same family."""

    __tablename__ = "fonts"
    __table_args__ = (Index("idx_fonts_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    # Read out of the font's own name table, so it matches what libass will look up by family.
    family: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    file_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
