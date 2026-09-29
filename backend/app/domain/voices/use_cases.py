"""音色与语音合成的闸:取音色顺带过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

音色归工作区。看(列表、试听参考音频)只要是成员;建、改、删、合成都要 `ai` —— 合成要花钱、克隆要用别人的
声音,和生成页同一道闸。形状和 permissions.require_asset 一样:接口与智能体工具从这里拿音色。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Asset, Job, User, Voice
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm, require_sequence_access
from app.domain.voices import voices


def readable(db: Session, user: User, voice_id: str) -> Voice:
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise NotVisible("routeErr_voiceNotFound")
    ensure_workspace_access(db, user, voice.workspace_id)
    return voice


def usable(db: Session, user: User, voice_id: str) -> Voice:
    """他能用(改、删、拿去合成)的那个音色。"""
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise NotVisible("routeErr_voiceNotFound")
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    return voice


def source_asset(db: Session, user: User, asset_id: str) -> Asset:
    """从一段素材里取某个说话人建音色:素材所在的工作区要 `ai`。"""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotVisible("routeErr_assetNotFound")
    ensure_workspace_perm(db, user, asset.workspace_id, "ai")
    return asset


def ensure_can_list(db: Session, user: User, workspace_id: str) -> None:
    ensure_workspace_access(db, user, workspace_id)


def ensure_can_speak(db: Session, user: User, workspace_id: str) -> None:
    """在这个工作区里建音色、合成、做播客。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")


def dub_subtitles(
    db: Session,
    user: User,
    sequence_id: str,
    *,
    clip_ids: list[str],
    match_duration: bool,
    line: str,
    original_audio: str,
    engine: str,
    voice_id: str | None,
    engine_voice: str,
    speed: float,
    **options: object,
) -> Job:
    """给时间线上选中的字幕条配音:要 `edit`(改这条时间线)也要 `ai`(花钱)。

    `options` 是引擎那一套附加项(见 synthesis_params)。
    """
    from app.domain.voices.engine_catalog import synthesis_params
    from app.domain.voices.speech import CLONE_ENGINE
    from app.domain.voices.subtitle_dub import start_subtitle_dub

    sequence = require_sequence_access(db, user, sequence_id, perm="edit")
    ensure_workspace_perm(db, user, sequence.workspace_id, "ai")
    clone = (engine or CLONE_ENGINE) == CLONE_ENGINE
    synthesis = synthesis_params(
        db,
        engine=engine,
        voice=(voice_id or "") if clone else engine_voice,
        speed=speed,
        user_id=user.id,
        workspace_id=sequence.workspace_id,
        **options,
    )
    return start_subtitle_dub(
        db,
        sequence_id=sequence_id,
        clip_ids=list(clip_ids),
        match_duration=match_duration,
        line=line,
        created_by=user.id,
        synthesis=synthesis,
        original_audio=original_audio,
    )
