"""音色:工作区里的克隆音色、它们复刻到远端引擎上的副本,以及智能体朗读用哪一个。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
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
    #: 授权声明(ADR 0028 §5):这把嗓子是谁的 —— self / authorized / fictional(entities.catalog.CONSENT_KINDS),
    #: 升级前建的音色是 `undeclared`。**没有声明的不能用于数字人**(让它说话、对口型),建新音色时必须选一项。
    #: 谁、何时声明的由服务端记。
    consent_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="undeclared")
    consent_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class VoiceEnrollment(Base):
    """一把嗓子(`Voice`)复刻到远端引擎上的**一份副本**(ADR 0037):在谁的账号里、建在哪个模型上、百炼给的音色 id。

    不把 `remote_voice_id` 直接加在 `voices` 上:一把嗓子可能在几个人的账号、几个模型上各有一份,一列装不下;
    而且那会让「这把嗓子是什么」(参考音频、文字、授权声明)和「它在哪儿有副本」搅成一件事。

    **本机的参考音频仍是唯一的来源**:副本丢了(一年没被合成用过、换了账号、换了模型)随时能从它重建,
    所以副本不需要备份,也不需要「从远端拉回来」。

    **上传的同意记在副本上**(`consented_*`):参考音频离开这台机器、进到第三方账号里,要当事人点过头。同一把嗓子、
    同一个引擎、同一个账号(连接 + 钥匙的主人)里有任何一份副本,就算点过 —— 换了模型、副本被删了按需重建,不再问。
    """

    __tablename__ = "voice_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "voice_id", "engine", "provider_profile_id", "owner_user_id", "target_model",
            name="uq_voice_enrollments_copy",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 哪把嗓子。删嗓子级联(远端那份由 voices.delete_voice 先删)。
    voice_id: Mapped[str] = mapped_column(ForeignKey("voices.id", ondelete="CASCADE"), nullable=False, index=True)
    #: 复刻在哪个引擎上(和 `ai` 层语音适配器同一个裸名;这一版只有 `alibaba-cosyvoice`)。
    engine: Mapped[str] = mapped_column(String(40), nullable=False)
    #: **在谁的账号里**:哪条连接、用的是谁的钥匙(钥匙归人,同一条连接下每个人一把)。
    provider_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 建在哪个模型上。音色绑死在建它的模型上(v3-flash 上建的发给 v2 是 400),换模型就是另一份副本。
    target_model: Mapped[str] = mapped_column(String(120), nullable=False)
    #: 远端给的音色 id;还没建出来时是空串。
    remote_voice_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: deploying / ok / failed / missing(见 domain/voices/remote)。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="deploying")
    #: 失败原因的原文(远端的原话),或一个文案 key。
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    consented_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consented_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    #: 最近一次合成用到它的时间 —— 一年没被合成用过,远端会把它删掉。
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    #: 念的是配音库里的一把嗓子时指向 voices 表的那一行:能复刻的远端引擎(CosyVoice)念它的副本(ADR 0037)。
    voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 语速。对话里通常比配音快一点,所以它也跟着这份配置走。
    speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    #: 关掉就不念 —— 有人只要说话输入,不要它出声。
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
