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


def speaking_engines(db: Session, user: User, workspace_id: str) -> list[dict]:
    """念一句话能用的引擎和各自的音色(见 engine_catalog.speaking_engines)。克隆那一项列的是这个工作区的音色库,
    所以和列音色同一道闸:是成员就看得到。"""
    from app.domain.voices.engine_catalog import speaking_engines as listed

    ensure_can_list(db, user, workspace_id)
    return listed(db, user.id, workspace_id)


def choose_agent_voice(
    db: Session,
    user: User,
    *,
    engine: str,
    engine_voice: str,
    engine_voice_resource: str,
    engine_model: str,
    provider_profile_id: str | None,
    voice_id: str | None,
    speed: float,
    enabled: bool,
):
    """设**我自己**的对话音色(只有这一档,没有部署默认)。

    点了配音库里的一把嗓子(只有能复刻的远端引擎这样点,ADR 0037)时,存之前问清楚:我能用这把嗓子、它声明过是谁的、
    我这个账号同意过上传 —— 没同意就 409,设置页弹确认框;不然要等到对话里第一次开口才失败。
    """
    from app.domain.voices import agent_voice, remote

    if voice_id:
        if not remote.clones_remotely(engine):
            raise voices.VoiceError("voiceErr_remoteCloneUnsupported", engine=engine)
        voice = usable(db, user, voice_id)
        remote.check_voice(
            db, engine=engine, voice_id=voice.id, workspace_id=voice.workspace_id, user_id=user.id,
            provider_profile_id=provider_profile_id, engine_model=engine_model,
        )
        engine_voice = engine_voice_resource = ""
    return agent_voice.upsert(
        db,
        user.id,
        engine=engine,
        engine_voice=engine_voice,
        engine_voice_resource=engine_voice_resource,
        engine_model=engine_model,
        provider_profile_id=provider_profile_id,
        voice_id=voice_id,
        speed=speed,
        enabled=enabled,
    )


def ensure_can_speak(db: Session, user: User, workspace_id: str) -> None:
    """在这个工作区里建音色、合成、做播客。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")


def dub_subtitles(
    db: Session,
    user: User,
    sequence_id: str,
    *,
    clip_ids: list[str],
    track_id: str = "",
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
    from app.domain.voices.engine_catalog import synthesis_params, voice_slot
    from app.domain.voices.subtitle_dub import dub_targets, start_subtitle_dub

    sequence = require_sequence_access(db, user, sequence_id, perm="edit")
    ensure_workspace_perm(db, user, sequence.workspace_id, "ai")
    synthesis = synthesis_params(
        db,
        engine=engine,
        voice=voice_slot(engine, voice_id=voice_id, engine_voice=engine_voice),
        speed=speed,
        user_id=user.id,
        workspace_id=sequence.workspace_id,
        **options,
    )
    return start_subtitle_dub(
        db,
        sequence_id=sequence_id,
        clip_ids=dub_targets(db, sequence_id, list(clip_ids), track_id),
        match_duration=match_duration,
        line=line,
        created_by=user.id,
        synthesis=synthesis,
        original_audio=original_audio,
    )
