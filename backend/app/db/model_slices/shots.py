"""视频的镜头表(ADR 0061)。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class ShotBreakdown(Base):
    """一份视频的镜头表:刀口、逐镜的时间和动静(代码量的),景别、运镜、画面描述(模型判的)。

    **是素材的派生物,一份视频一份**:重拆就覆盖(镜头表说的是「这条视频长什么样」,不是一次次的对话记录)。
    帧和联系表落在素材目录的 `shots/` 下,素材删了行跟着删(外键级联)、目录随素材目录一起走。
    """

    __tablename__ = "shot_breakdowns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, unique=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 判画面用哪种语言写(zh / en):拆的人当时的界面语言。
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="zh")
    #: 量刀口用的参数:`threshold`、`min_shot`。
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: 探测得来的:`duration`、`fps`、`width`、`height`、`has_audio`。
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: 检测到的刀口 `[{time, score}]`(并碎片之前的原样)。
    cuts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 逐镜。字段见 domain/shots(detect.build_shots 量的、describe.reconcile 判的)。
    shots: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 联系表 `[{index, first, last, a, b}]`。
    sheets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 谁判的画面:`{provider, model, batches, judged_batches, error}`;一镜都没判过是空的。
    describe: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: 对账和节奏的提示 `[{shot, kind, field, value}]`,界面按 kind 翻成一句话。
    hints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
