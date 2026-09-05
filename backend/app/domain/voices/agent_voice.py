"""语音对话用哪个音色 —— **每人一份**。

和配音的 TTS 默认分开,理由在 db.models.AgentVoicePref 上写着:配音要质量,对话要延迟,
同一个默认同时服务两件事必然在某一边是错的。

立场照搬 provider_defaults:**没有部署兜底,没设就说没设**。语音回复按字符计费,替他挑一个
他没选过的音色去念,和替他挑一个模型去回答是同一类错误。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AgentVoicePref


class AgentVoiceNotConfigured(RuntimeError):
    """还没选过对话音色。**这不是故障** —— 界面据此提示去设置里选一个,而不是报错。"""


def get_row(db: Session, user_id: str) -> AgentVoicePref | None:
    """只查**这个人**那一行。查不到就是没设过。"""
    return db.get(AgentVoicePref, user_id)


def upsert(
    db: Session,
    user_id: str,
    *,
    engine: str,
    engine_voice: str = "",
    engine_voice_resource: str = "",
    engine_model: str = "",
    provider_profile_id: str | None = None,
    voice_id: str | None = None,
    speed: float = 1.0,
    enabled: bool = True,
) -> AgentVoicePref:
    """建行/改行。**行创建只发生在这里**(数据归属,见 domain/ownership)。"""
    row = db.get(AgentVoicePref, user_id)
    if row is None:
        row = AgentVoicePref(owner_user_id=user_id)
        db.add(row)
    row.engine = engine.strip()
    row.engine_voice = engine_voice.strip()
    row.engine_voice_resource = engine_voice_resource.strip()
    row.engine_model = engine_model.strip()
    row.provider_profile_id = provider_profile_id or None
    row.voice_id = voice_id or None
    # 语速给个可用区间:各家引擎对超出范围的值反应不一,有的直接拒、有的悄悄夹取。
    row.speed = min(max(float(speed), 0.5), 2.0)
    row.enabled = bool(enabled)
    db.commit()
    db.refresh(row)
    return row


def require(db: Session, user_id: str) -> AgentVoicePref:
    """拿这个人的对话音色,没设过就说没设 —— 不替他挑一个。"""
    row = get_row(db, user_id)
    if row is None or not row.enabled or not row.engine:
        raise AgentVoiceNotConfigured(
            "还没有选语音对话的音色 —— 到设置的「语音对话」里选一个。"
            "它和配音的默认音色是分开的:配音要质量,对话要快。"
        )
    return row
