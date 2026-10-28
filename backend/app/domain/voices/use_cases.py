"""音色与语音合成的闸:取音色顺带过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

音色归工作区。看(列表、试听参考音频)只要是成员;建、改、删、合成都要 `ai` —— 合成要花钱、克隆要用别人的
声音,和生成页同一道闸。形状和 permissions.require_asset 一样:接口与智能体工具从这里拿音色。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Asset, Job, User, Voice
from app.domain.permissions import (
    NotVisible,
    ensure_workspace_access,
    ensure_workspace_perm,
    require_asset,
    require_sequence_access,
)
from app.domain.voices import transcription, voices, errors, agent_voice, engine_catalog, remote, subtitle_dub
from app.domain.voices.engine_catalog import speaking_engines as listed
from app.domain.voices.voice_ref import VoiceRef
from app.domain.voices.subtitle_dub import dub_targets


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

    ensure_can_list(db, user, workspace_id)
    return listed(db, user.id, workspace_id)


def choose_agent_voice(
    db: Session,
    user: User,
    *,
    voice: VoiceRef | None,
    workspace_id: str = "",
    speed: float,
    enabled: bool,
    asr_engine: str = "",
    speak_early: bool = True,
):
    """设**我自己**的对话音色,以及说话输入用哪一家(只有这一档,没有部署默认)。`voice` 为 `None` = 不选了。

    存之前照音色目录校验并补齐(`engine_catalog.check_voice`:引擎认得、音色属于它、模型对得上,火山的资源族由目录带上)。
    点了配音库里的一把嗓子(只有能复刻的远端引擎这样点,ADR 0037)时,还要问清楚:我能用这把嗓子、它声明过是谁的、
    我这个账号同意过上传 —— 没同意就 409,设置页弹确认框;不然要等到对话里第一次开口才失败。

    说话输入那一格不在这里验就绪:验它要起子进程探测本机引擎,而这是每次保存都会走的路。界面上只列已经就绪的;
    哪天真用不了,听写那一刻由 capabilities.pick 带着原因拒绝(见 routes/asr 与 domain/voices/transcription)。
    """

    if voice is not None:
        if voice.cloned_voice:
            if not remote.clones_remotely(voice.engine):
                raise errors.VoiceError("voiceErr_remoteCloneUnsupported", engine=voice.engine)
            cloned = usable(db, user, voice.cloned_voice)
            remote.check_voice(db, voice, workspace_id=cloned.workspace_id, user_id=user.id)
            workspace_id = cloned.workspace_id
        voice = engine_catalog.check_voice(db, voice, user_id=user.id, workspace_id=workspace_id)
    return agent_voice.upsert(
        db, user.id, voice=voice, speed=speed, enabled=enabled, asr_engine=asr_engine, speak_early=speak_early,
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
    voice: VoiceRef | None,
    speed: float,
) -> Job:
    """给时间线上选中的字幕条配音:要 `edit`(改这条时间线)也要 `ai`(花钱)。`voice` 为 `None` = 用默认那一把。"""

    sequence = require_sequence_access(db, user, sequence_id, perm="edit")
    ensure_workspace_perm(db, user, sequence.workspace_id, "ai")
    chosen = engine_catalog.voice_for_synthesis(db, voice, user_id=user.id, workspace_id=sequence.workspace_id)
    return subtitle_dub.start_subtitle_dub(
        db,
        sequence_id=sequence_id,
        clip_ids=dub_targets(db, sequence_id, list(clip_ids), track_id),
        match_duration=match_duration,
        line=line,
        created_by=user.id,
        voice=chosen,
        speed=speed,
        original_audio=original_audio,
    )


def start_transcription(db: Session, user: User, asset_id: str, *, language: str = "", engine: str = "") -> Job:
    """给一份素材排转写。闸是素材的 `ai` 那一档(转写可能用云端引擎、花钱)。

    入口住在配音域而不是素材域:素材是最底下的一层,认识转写的话两个包就成了环(见 tests/test_import_layering)。
    """
    require_asset(db, user, asset_id, perm="ai")
    return transcription.start_transcription(db, asset_id, created_by=user.id, language=language, engine=engine)
