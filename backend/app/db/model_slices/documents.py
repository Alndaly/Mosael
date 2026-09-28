"""文档的解析结果(ADR 0031 §2)。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class AssetExtraction(Base):
    """一份文档素材的一次解析:谁解析的、结果在哪、成没成。

    **是素材的派生物,不是另一种东西**:原件在素材库,解析出的 Markdown、页面图、插图落在素材目录的
    `extracted/<这一行的 id>/` 下。同一份文档可以有几份(本地解析一份、MinerU 精解析一份),读的时候用最新成功的那份;
    素材删了跟着删(外键级联,目录随素材目录一起走)。
    """

    __tablename__ = "asset_extractions"
    __table_args__ = (Index("idx_asset_extractions_asset", "asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 哪一家解析的:`builtin:local` 或插件连接的 id(连接删了也留着这份结果,名字记在 parser_name)。
    parser: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: queued / running / succeeded / failed。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 按什么切:page / slide / sheet / section;切成几段;全文多少字。
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="page")
    sections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 每一段的标题和页面图,读的时候按段取(见 domain/documents/extraction)。
    outline: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 按页的页面图(相对解析目录),「原版」那一栏照它排。PDF / PPT 和段一一对应;Word 按章切、页面图按页,对不上。
    page_images: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 给人看的提醒(i18n key):扫描件、表格截断、没装 LibreOffice……
    notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
