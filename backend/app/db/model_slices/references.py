from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RecordReference(Base):
    """JSON 里点名的别的记录:画布上的素材格、工作流节点里的资产、生成请求里的资产……

    **派生数据**,不是事实本身:事实在各自的 JSON 里,这一张由 db/references 在每次 flush 时跟着写
    (启动时按抽取规则的版本号整张重建)。目标**不设外键** —— 被点名的东西删了,引用照样在,
    这张表正是用来回答「谁还指着它」的。读的一方总要回到来源表确认来源还在(来源被级联删掉时
    这里会留下几行过期的,无害)。
    """

    __tablename__ = "record_references"

    source_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: 怎么用到的(画板:`cell` 是一格就是它,`mention` 是提示词里 @ 了它;工作流:`node`)。
    how: Mapped[str] = mapped_column(String(16), primary_key=True, default="")
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (Index("ix_record_references_target", "target_kind", "target_id"),)


class RecordReferenceIndex(Base):
    """引用表按哪一版抽取规则建的。规则一改(db/references.EXTRACTOR_VERSION),启动时整张重建。"""

    __tablename__ = "record_reference_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

