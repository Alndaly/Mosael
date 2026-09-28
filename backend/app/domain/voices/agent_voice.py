"""语音对话用哪个音色 —— **每人一份**。

和配音的 TTS 默认分开,理由在 db.models.AgentVoicePref 上写着:配音要质量,对话要延迟,
同一个默认同时服务两件事必然在某一边是错的。

立场照搬 provider_defaults:**没有部署兜底,没设就说没设**。语音回复按字符计费,替他挑一个
他没选过的音色去念,和替他挑一个模型去回答是同一类错误。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import AgentVoicePref
from app.domain.voices import voices as voices_domain


class AgentVoiceUnavailable(LocalizedError, RuntimeError):
    """这会儿念不了:还没选好音色,或者「让它出声」关着。**这不是故障** —— 界面据此指路去设置,
    而不是报错。两种情形用同一个类型、不同的文案 key:调用方的处置一样(409 + 那句话)。"""


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


def require_ready(db: Session, user_id: str) -> AgentVoicePref:
    """引擎和音色都选好了的那份配置 —— **不问开关**。试听只要这个:配置的时候听一下效果,
    本来就发生在打开之前。没设过就说没设,不替他挑一个。"""
    row = get_row(db, user_id)
    if row is None or not row.engine or not row.engine_voice:
        raise AgentVoiceUnavailable("voiceErr_agentVoiceNotConfigured")
    return row


def require_enabled(db: Session, user_id: str) -> AgentVoicePref:
    """对话里真要出声用的:选好了,**而且**「让它出声」开着。关着就是只用文字,那是他的选择。"""
    row = require_ready(db, user_id)
    if not row.enabled:
        raise AgentVoiceUnavailable("voiceErr_agentVoiceDisabled")
    return row


def speak(db: Session, row: AgentVoicePref, *, text: str, workspace_id: str, out_dir: Path, source_type: str) -> Path:
    """用这份配置念一句,落到 `out_dir`。对话发声和试听都走这里 —— 试听听到的,就是以后念给他的
    那个声音;两处各拼一遍参数的话,少带一样(语速、资源族、模型)试听就和真用对不上。"""
    return voices_domain.speak_to_file(
        db,
        text=text,
        engine=row.engine,
        engine_voice=row.engine_voice,
        speed=row.speed,
        workspace_id=workspace_id,
        user_id=row.owner_user_id,
        voice_resource=row.engine_voice_resource,
        provider_profile_id=row.provider_profile_id,
        model_override=row.engine_model,
        out_dir=out_dir,
        # 记账挂在这个人身上:不是 job,是他的一次发声。**照样要记** —— 各家 TTS 按字符计费。
        source_type=source_type,
        source_id=row.owner_user_id,
    )
