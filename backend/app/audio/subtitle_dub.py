"""字幕配音:把选中的字幕条逐条合成,落到一条专门的「配音」轨。

**为什么单独开一条轨**:原声和用户自己摆的素材一个字都不动 —— 配音是新加的一层,不满意整条
删掉就回到原样。混进现有音频轨的话,「撤销这次配音」就变成了逐段找、逐段删。

**为什么不自己跑合成、而是排一个个 tts 子任务**:合成跑在哪台机器是**部署的决定**
(jobs.execution_mode —— 这个应用支持服务端不在本机)。这台机器可能根本没装克隆引擎,绕过
调度直接跑,在分布式部署下就是必然失败。排子任务则两种模式都对:本机模式立刻起线程,外部
worker 模式由那台装了引擎的机器认领。

**时长匹配用的是片段自己的 speed,不是把音频重新编码**:渲染时 atempo 会按它变速(见
media/render_executor._atempo_chain)。所以这一步无损、可撤销、事后还能在检查器里手动微调 ——
而重新编码一遍的话,想改回去就只剩重做。
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Job, Sequence, Track
from app.domain.jobs import create_job, dispatch_job, emit_job_event, say
from app.domain.sequences.operations import AddTrack, InsertClip, SetClipSpeed, add_track, insert_clip, set_clip_speed

logger = logging.getLogger(__name__)

#: 单条合成等多久算超时。克隆引擎在慢机器上一条能跑几分钟,这里给得比它宽 —— 超时不是"合成慢",
#: 是"这条任务再也不会回来了"。
_CHILD_TIMEOUT_SECONDS = 20 * 60
_POLL_SECONDS = 0.5

#: 片段变速的合法区间(与 operations.set_clip_speed 一致)。夹住而不是报错:一条字幕的文本
#: 长到要 5 倍速才塞得进去,那是文本和时长本身不匹配,不该让整批配音失败。
_MIN_SPEED = 0.25
_MAX_SPEED = 4.0


class DubError(RuntimeError):
    pass


def dub_text(text: str, line: str = "all") -> str:
    """这一条字幕里**真正要念出来的**那部分。

    双语字幕是「原文\n译文」两行(翻译功能勾了「保留原文」就是这个形状)。整段丢给合成,
    结果是先念一遍日文再念一遍中文 —— 一条 3 秒的字幕配出 12 秒的音,而且没人想听那个。
    所以「念哪一行」必须是个能选的东西,默认全念(单语字幕就该全念,那是绝大多数情况)。
    """
    lines = [part.strip() for part in (text or "").splitlines() if part.strip()]
    if not lines:
        return ""
    if line == "first":
        return lines[0]
    if line == "last":
        return lines[-1]
    return "\n".join(lines)


def _subtitle_clips(db: Session, sequence_id: str, clip_ids: list[str], line: str = "all") -> list[Clip]:
    """按时间顺序返回要配音的字幕条。

    **只认念得出东西的** —— 空字幕合成出来是一段静音,它不会报错,只会安静地占住时间线上一格。
    判据用的是 `dub_text` 之后的文本:选了「只念第二行」而某条只有一行时,那条就是没得念,
    按整段判会把它当成有文本,然后配出一段和别的行对不上的音。
    """
    clips = [clip for clip in (db.get(Clip, cid) for cid in clip_ids) if clip is not None]
    chosen = [
        clip
        for clip in clips
        if clip.sequence_id == sequence_id and dub_text(clip.text_override or "", line)
    ]
    return sorted(chosen, key=lambda clip: clip.timeline_start)


def start_subtitle_dub(
    db: Session,
    *,
    sequence_id: str,
    clip_ids: list[str],
    match_duration: bool,
    created_by: str | None,
    synthesis: dict,
    line: str = "all",
) -> Job:
    """给这些字幕条排一次配音。`synthesis` 原样转交 voices.start_synthesis(音色/引擎那一套)。"""
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise DubError("时间线不存在")
    clips = _subtitle_clips(db, sequence_id, clip_ids, line)
    if not clips:
        raise DubError("选中的字幕里没有可配音的文本")

    job = create_job(
        db,
        workspace_id=sequence.workspace_id,
        kind="subtitle_dub",
        created_by=created_by,
        payload={
            "subject": sequence.name,
            "sequence_id": sequence_id,
            "clip_ids": [clip.id for clip in clips],
            "match_duration": match_duration,
            "line": line,
            "synthesis": synthesis,
        },
        message="jobMsg_dubRunning",
        message_params={"done": 0, "total": len(clips)},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _run_dub(job_id))
    return job


def _await_child(job_id: str) -> str:
    """等一条合成任务出结果,返回 asset_id。

    轮询而不是等事件:这个 worker 本来就是后台线程,而合成可能由**另一台机器**上的外部 worker
    执行 —— 跨进程的完成通知这里收不到,库里的状态是唯一两边都看得见的东西。
    """
    deadline = time.monotonic() + _CHILD_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            child = db.get(Job, job_id)
            if child is None:
                raise DubError("合成任务不见了")
            if child.status == "succeeded":
                asset_id = (child.result or {}).get("asset_id")
                if not asset_id:
                    raise DubError("合成任务报成功却没有产出音频")
                return str(asset_id)
            if child.status == "failed":
                raise DubError(child.error or "合成失败")
        time.sleep(_POLL_SECONDS)
    raise DubError("合成任务超时")


def _speed_for(audio_seconds: float, slot_seconds: float) -> float | None:
    """让这段音频正好占满字幕段落所需的播放倍速。

    倍速 = 音频时长 / 段落时长:音频 6 秒要塞进 3 秒的段落,就是 2 倍速。两个数里任何一个不是
    正数,就没有倍速可言 —— 返回 None,让调用方保持原速,而不是拿一个算出来的 0 或 inf 去写库。
    """
    if audio_seconds <= 0 or slot_seconds <= 0:
        return None
    return max(_MIN_SPEED, min(_MAX_SPEED, audio_seconds / slot_seconds))


def _run_dub(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = job.payload or {}
        sequence_id = str(payload.get("sequence_id") or "")
        clip_ids = list(payload.get("clip_ids") or [])
        match_duration = bool(payload.get("match_duration"))
        line = str(payload.get("line") or "all")
        synthesis = dict(payload.get("synthesis") or {})
        # 现在取出来:commit 之后这些属性会过期,而 job 出了这个 with 就是 detached 的 ——
        # 到下一个 session 里再读 job.created_by 会去刷一个已经关掉的连接。
        created_by = job.created_by
        job.status = "running"
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

    from app.audio.voices import start_synthesis

    done = 0
    failed = 0
    track_id = ""
    total = len(clip_ids)
    try:
        for index, clip_id in enumerate(clip_ids):
            with SessionLocal() as db:
                clip = db.get(Clip, clip_id)
                if clip is None:
                    failed += 1
                    continue
                text = dub_text(clip.text_override or "", line)
                slot_seconds = max(0.0, (clip.src_out - clip.src_in) / (clip.speed or 1.0))
                timeline_start = clip.timeline_start
                sequence = db.get(Sequence, sequence_id)
                child = start_synthesis(
                    db,
                    text=text,
                    project_id=sequence.project_id if sequence else None,
                    created_by=created_by,
                    **synthesis,
                )
                db.commit()
                child_id = child.id

            try:
                asset_id = _await_child(child_id)
            except DubError as exc:
                # 一条失败不该拖垮整批:已经配好的那些留在轨上,失败的条数最后报出来。
                failed += 1
                logger.warning("字幕配音:第 %s 条失败:%s", index + 1, str(exc)[:200])
                continue

            with SessionLocal() as db:
                asset = db.get(Asset, asset_id)
                audio_seconds = float((asset.media_info or {}).get("duration") or 0.0) if asset else 0.0
                if audio_seconds <= 0:
                    failed += 1
                    continue
                # 落哪条轨:**已有配音轨就用它**,没有才新建。每配一次多一条轨的话,改几句台词
                # 重配几段,时间线上就摞起一叠只有一两段音频的轨。
                #
                # 而且只在**第一条音频真的要落地的这一刻**才建。建在合成之前的话,一次全军覆没的
                # 配音会留下一条空轨 —— 空轨看起来和「配音没生成」一模一样,用户先怀疑的是功能坏了,
                # 不是那次失败(这条 bug 就是这么被报上来的)。
                if not track_id:
                    track_id = _dub_track(db, sequence_id, created_by)
                sequence = insert_clip(
                    db,
                    sequence_id,
                    InsertClip(
                        track_id=track_id,
                        asset_id=asset_id,
                        timeline_start=timeline_start,
                        src_in=0.0,
                        src_out=audio_seconds,
                    ),
                )
                if match_duration:
                    speed = _speed_for(audio_seconds, slot_seconds)
                    if speed is not None:
                        new_clip = _clip_at(db, track_id, timeline_start)
                        if new_clip is not None:
                            set_clip_speed(db, sequence_id, SetClipSpeed(clip_id=new_clip.id, speed=speed))
                done += 1
                job = db.get(Job, job_id)
                job.progress = (index + 1) / max(1, total)
                say(job, "jobMsg_dubRunning", done=done, total=total)
                db.commit()

        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if done == 0:
                job.status = "failed"
                say(job, "jobMsg_dubFailed")
                job.error = "没有一条配音成功"
                emit_job_event(db, job.id, "job.failed", {})
            else:
                job.status = "succeeded"
                job.progress = 1.0
                # 部分失败也是成功的一种:配好的那些是真的配好了。但**不能都说成「完成」** ——
                # 「10 条里成了 9 条」说成「配音完成」,用户要到时间线上一段段找才发现少了一条。
                if failed:
                    say(job, "jobMsg_dubPartial", done=done, failed=failed)
                else:
                    say(job, "jobMsg_dubDone", done=done)
                job.result = {"track_id": track_id, "done": done, "failed": failed}
                emit_job_event(db, job.id, "job.succeeded", {"track_id": track_id})
            db.commit()
    except Exception as exc:  # noqa: BLE001 — 任何意外都要落进任务行,否则会话永远停在 running
        logger.exception("字幕配音任务 %s 失败", job_id)
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                say(job, "jobMsg_dubFailed")
                job.error = str(exc)[:600]
                emit_job_event(db, job.id, "job.failed", {})
                db.commit()


def _dub_track(db: Session, sequence_id: str, created_by: str | None) -> str:
    """这条时间线的配音轨,没有就建一条。

    认的是 `Track.role == "dub"`,**不是名字** —— 名字是给人看的,用户随时会把它改成「旁白」
    「解说」;按名字认的话,改完名再配一次就又多一条轨。
    """
    tracks = list(db.scalars(select(Track).where(Track.sequence_id == sequence_id)))
    existing = [track for track in tracks if track.kind == "audio" and track.role == "dub"]
    if existing:
        # 有多条(历史数据、或用户自己复制过)时用最上面那条,至少是稳定的选择。
        return min(existing, key=lambda track: track.position).id
    add_track(db, sequence_id, AddTrack(kind="audio", actor_id=created_by))
    db.flush()
    fresh = [
        track
        for track in db.scalars(select(Track).where(Track.sequence_id == sequence_id))
        if track.kind == "audio"
    ]
    track = max(fresh, key=lambda track: track.position)
    track.role = "dub"
    db.commit()
    return track.id


def _clip_at(db: Session, track_id: str, timeline_start: float) -> Clip | None:
    """刚插进去的那一段。按落点找 —— insert_clip 返回的是整条时间线,不是片段。"""
    for clip in db.scalars(select(Clip).where(Clip.track_id == track_id)):
        if abs(clip.timeline_start - timeline_start) < 1e-6:
            return clip
    return None
