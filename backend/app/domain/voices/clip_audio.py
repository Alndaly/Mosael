"""剪辑台上对一个片段做声音处理 —— 降噪、只留人声、拆成人声和背景音 —— **做完直接换到时间线上**。

此前这三件事只能在素材库里做:产出一份新素材,用户再自己去时间线上找到原来那段、删掉、把新的拖进来、
对齐位置 —— 而删掉的那一段上做过的剪切、调速、调色、关键帧全没了。现在:

- **降噪**:降出来的是同一段内容(视频就是换了音轨的同一段视频),时间一一对应 → 这条时间线上用着这份素材的
  所有片段换成它(替换媒体,见 sequences/media_swap),其余一样不动。
- **只留人声**(人声增强):拆出人声。音频片段直接换成人声;视频片段画面不动,人声放到音频轨上、源片段静音
  (分离音频,和配音的「只去人声」同一个做法)。
- **拆成人声和背景音**:两份都放到音频轨上、源片段静音,之后各自调音量。

都是剪辑操作,记成撤销栈上的一步(操作组);原素材一个字节不动。分离和降噪一样「这台机器要忙很久」,
先拿渲染名额(RENDER_SLOTS)再开会话。拆过的素材按素材缓存(见 original_audio._cached_background 同一个认法)。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Clip, Job, Sequence, Track
from app.domain.assets.lineage import SEPARATE, made_from
from app.domain.jobs import RENDER_SLOTS, create_job, dispatch_job, emit_job_event, finish_job, run_job_guarded, say

logger = logging.getLogger(__name__)

#: 片段上能做的声音处理。
CLIP_AUDIO_ACTIONS = ("denoise", "isolate_voice", "separate")


class ClipAudioError(LocalizedError, RuntimeError):
    """做不了。带文案 key(`clipAudioErr_*`)。"""


def start_clip_audio_job(db: Session, *, sequence_id: str, clip_id: str, action: str, created_by: str | None) -> Job:
    """排一次片段声音处理。能当场判的(动作认不认得、片段有没有声音、引擎在不在)排队之前就判掉。"""
    from app.domain.assets.denoise import DENOISABLE_KINDS, ready_adapter
    from app.domain.assets.separation import available

    if action not in CLIP_AUDIO_ACTIONS:
        raise ClipAudioError("clipAudioErr_action", actions=" / ".join(CLIP_AUDIO_ACTIONS))
    clip = db.get(Clip, clip_id)
    if clip is None or clip.sequence_id != sequence_id:
        raise ClipAudioError("clipAudioErr_clipNotFound")
    asset = db.get(Asset, clip.asset_id) if clip.asset_id else None
    if asset is None or asset.kind not in DENOISABLE_KINDS or not asset.file_key:
        raise ClipAudioError("clipAudioErr_noSound")
    if action == "denoise":
        ready_adapter(db, created_by, "")
    elif not available(db, created_by):
        raise ClipAudioError("dubErr_separationUnavailable")
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="clip_audio",
        created_by=created_by,
        payload={"sequence_id": sequence_id, "clip_id": clip_id, "action": action, "subject": asset.name},
        message="jobMsg_clipAudioQueued",
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _run(job_id))
    return job


def _run(job_id: str) -> None:
    with RENDER_SLOTS:
        run_job_guarded(job_id, lambda: _body(job_id), what="片段声音处理")


def _cached_stems(db: Session, asset: Asset) -> dict[str, str]:
    """这份素材整段拆过的人声 / 背景音(只认整段拆的:片段要的是和原素材时间一一对应的那份)。"""
    rows = db.scalars(
        select(Asset)
        .where(
            Asset.workspace_id == asset.workspace_id,
            made_from(asset.id, SEPARATE),
        )
        .order_by(Asset.created_at.desc())
    )
    stems: dict[str, str] = {}
    for row in rows:
        info = row.media_info or {}
        if row.file_key and info.get("source_range") is None:
            stems.setdefault(str(info.get("stem")), row.id)
    return stems


def _body(job_id: str) -> None:
    from app.domain.assets.denoise import denoise_asset
    from app.domain.assets.separation import separate_asset

    # 三段各自一个事务:「在跑」先落库、放掉写锁(处理一跑就是几分钟);产出的素材落库;再放上时间线。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = job.payload or {}
        sequence_id, clip_id, action = str(payload["sequence_id"]), str(payload["clip_id"]), str(payload["action"])
        created_by = job.created_by
        clip = db.get(Clip, clip_id)
        if clip is None or not clip.asset_id:
            raise ClipAudioError("clipAudioErr_clipNotFound")
        source_asset_id = clip.asset_id
        if not finish_job(db, job, status="running", progress=0.1):
            return
        say(job, "jobMsg_clipAudioRunning")
        emit_job_event(db, job.id, "job.running", {})

    with unit_of_work() as db:
        asset = db.get(Asset, source_asset_id)
        if asset is None:
            raise ClipAudioError("clipAudioErr_clipNotFound")
        made: dict[str, str] = {}
        if action == "denoise":
            denoised, _engine = denoise_asset(db, asset, owner_user_id=created_by)
            made["denoised"] = denoised.id
        else:
            made = _cached_stems(db, asset)
            if not {"vocals", "background"} <= set(made):
                stems = separate_asset(db, asset, owner_user_id=created_by)
                made = {"vocals": stems.vocals.id, "background": stems.background.id}

    with unit_of_work() as db:
        changed = _place(db, sequence_id, clip_id, source_asset_id, action, made, created_by)
        job = db.get(Job, job_id)
        result = {"action": action, "assets": made, "clips": changed}
        if finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, f"jobMsg_clipAudioDone_{action}", n=changed)
            emit_job_event(db, job.id, "job.succeeded", dict(result))


def _place(
    db: Session, sequence_id: str, clip_id: str, source_asset_id: str, action: str, made: dict[str, str],
    actor_id: str | None,
) -> int:
    """产出放到时间线上(一步撤销)。返回动了几个片段。"""
    from app.domain.sequences.grouping import OperationGroup
    from app.domain.sequences.media_swap import ReplaceClipMedia, clips_using, replace_clip_media
    from app.domain.sequences.operations import DetachClipAudio, detach_clip_audio

    sequence = db.get(Sequence, sequence_id)
    clip = db.get(Clip, clip_id)
    if sequence is None:
        raise ClipAudioError("clipAudioErr_clipNotFound")
    with OperationGroup(sequence_id, label=f"clip_audio_{action}", actor_id=actor_id).collect(db):
        if action == "denoise":
            # 降出来的是同一段内容:这条时间线上用着原素材的片段一起换(同一份素材剪成好几段是常态)。
            targets = clips_using(sequence, source_asset_id)
            if targets:
                replace_clip_media(db, sequence_id, ReplaceClipMedia(clip_ids=tuple(targets), asset_id=made["denoised"],
                                                                     actor_id=actor_id))
            return len(targets)
        if clip is None:
            raise ClipAudioError("clipAudioErr_clipNotFound")
        track = db.get(Track, clip.track_id)
        if action == "isolate_voice" and track is not None and track.kind == "audio":
            replace_clip_media(db, sequence_id, ReplaceClipMedia(clip_ids=(clip.id,), asset_id=made["vocals"],
                                                                 actor_id=actor_id))
            return 1
        stems = ("vocals",) if action == "isolate_voice" else ("vocals", "background")
        for stem in stems:
            detach_clip_audio(db, sequence_id, DetachClipAudio(clip_id=clip.id, audio_asset_id=made[stem], actor_id=actor_id))
        return 1
