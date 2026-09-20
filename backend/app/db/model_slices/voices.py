"""音色:工作区里的克隆音色,以及智能体朗读用哪一个。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.db.model_base import new_id, now

class Voice(Base):
    """A cloned voice = a short reference clip + its transcript. Zero-shot TTS
    engines (F5-TTS / Fish Speech) synthesize new speech in this voice from the
    (reference audio + reference text + target text) triple. Workspace-scoped."""

    __tablename__ = "voices"
    __table_args__ = (Index("idx_voices_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reference_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")  # upload | speaker
    source_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_speaker: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class AgentVoicePref(Base):
    """这个人在**语音对话**里用哪个音色。

    **和配音的 TTS 默认是两件事,所以是两行配置。** 配音要的是质量:本地零样本引擎、克隆
    出来的音色,首次加载十几分钟也认了,因为那段音频要进成片。对话要的是延迟:说完一句
    等一分钟就没法叫对话了。同一个默认同时服务这两件事,必然在某一边是错的。

    立场照搬 ProviderDefault:**每人一份,没有部署兜底,没设就说没设**。语音回复是会花钱的
    (各家 TTS 按字符计费),替他挑一个他没选过的音色去念,和替他挑一个模型去回答一样不行。

    `owner_user_id` 用空串而不是 NULL 作主键默认值 —— SQLite 允许主键列为 NULL,那会让同
    一个人重复插入而不报错(同 ProviderDefault)。
    """

    __tablename__ = "agent_voice_prefs"

    owner_user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    #: 引擎 id(edge / openai / volcano / bailian / clone…)。空 = 没设过。
    engine: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    #: 引擎自己的音色 id。克隆引擎用 voice_id 那一列。
    engine_voice: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    engine_voice_resource: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: 手动指定的模型;留空按连接下的 tts 模型解析(见 voices.speak_to_file)。
    engine_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    provider_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 克隆引擎时指向 voices 表的那一行。
    voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 语速。对话里通常比配音快一点,所以它也跟着这份配置走。
    speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: 关掉就不念 —— 有人只要说话输入,不要它出声。
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
