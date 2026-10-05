"""字幕配音:把选中的字幕条逐条合成,落到一条专门的「配音」轨。

**为什么单独开一条轨**:原声和用户自己摆的素材一个字都不动 —— 配音是新加的一层,不满意整条
删掉就回到原样。混进现有音频轨的话,「撤销这次配音」就变成了逐段找、逐段删。

**为什么不自己跑合成、而是排一个个 tts 子任务**:合成跑在哪台机器是**部署的决定**
(jobs.execution_mode —— 这个应用支持服务端不在本机)。这台机器可能根本没装克隆引擎,绕过
调度直接跑,在分布式部署下就是必然失败。排子任务则两种模式都对:本机模式立刻起线程,外部
worker 模式由那台装了引擎的机器认领。

**时长匹配用的是片段自己的 speed,不是把音频重新编码**:渲染时 atempo 会按它变速(见
media/tempo.atempo_filters)。所以这一步无损、可撤销、事后还能在检查器里手动微调 ——
而重新编码一遍的话,想改回去就只剩重做。
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.core.i18n import DEFAULT_LOCALE, LocalizedError, t
from app.db.models import Asset, Clip, Job, Sequence, Track
from app.domain.assets.intermediates import DUB_LINE
from app.domain.assets.media_info import patch_media_info
from app.domain.jobs import JobError, blame, cancel_job_tree, create_job, dispatch_job, emit_job_event, finish_job, say
from app.domain.sequences.operations import AddTrack, InsertClip, add_track, insert_clip
from app.domain.voices.original_audio import (
    DEFAULT_ORIGINAL_AUDIO,
    OriginalAudioError,
    apply_original_audio,
    ensure_original_audio_mode,
)

logger = logging.getLogger(__name__)

#: 单条合成等多久算超时。克隆引擎在慢机器上一条能跑几分钟,这里给得比它宽 —— 超时不是"合成慢",
#: 是"这条任务再也不会回来了"。
_CHILD_TIMEOUT_SECONDS = 20 * 60
_POLL_SECONDS = 0.5

#: 「把每句配音压进原字幕的长度」默认开不开。**剪辑台、智能体、工作流、MCP 的默认值都从这里取** ——
#: 此前剪辑台默认关、另外三处默认开:同一条时间线从两个入口配,一个对得上画面、一个一路念过下一句。
#: 开:变速夹在 0.9–1.5 倍(见下),念出来仍是人话;不想变速的人在入口上关掉它。
DEFAULT_MATCH_DURATION = True

#: 配音「压回原长度」时变速的范围。夹住而不是报错:一条字幕的文本长到要 3 倍速才塞得进去,那是文本和时长
#: 本身不匹配,不该让整批配音失败。
#:
#: **不是片段变速的合法区间(0.25–4)。** 此前夹的就是那个区间:译文长一倍就 2 倍速念、短一半就 0.5 倍速拖着念,
#: 说话声早就不像人了。念快到 1.5 倍、念慢到 0.9 倍还听得过去;再长的先占用到下一句开始之前的空当(见 _speed_for)。
_MIN_SPEED = 0.9
_MAX_SPEED = 1.5


#: 配好的那段音频上记着「这是哪一句、用哪把嗓子念的」:{"text": 念的字, "voice": voice_identity(...)}。
#: 改口型的块缓存按它认句子(见 workflows/executors/dub_lipsync),不按音频字节 —— 同一句话、同一把嗓子
#: 重新合成一遍,字节每次都可能不一样,按字节认的话整图重跑时每一块都认不出来、再买一次。
DUB_LINE_KEY = "dub_line"
#: 合成参数里决定「是哪把嗓子、念多快」的那几项。连接(provider_profile_id)、工作区这些不算 —— 换个人跑、
#: 用他自己的连接调同一个音色,念出来还是同一把嗓子。
_VOICE_FIELDS = ("engine", "voice_id", "engine_voice", "engine_model", "clone_engine", "clone_model", "speed")


def voice_identity(synthesis: dict) -> str:
    """一组合成参数说的是哪把嗓子(见 DUB_LINE_KEY)。"""
    return "|".join(f"{field}={synthesis[field]}" for field in _VOICE_FIELDS if synthesis.get(field) not in (None, ""))


class DubError(LocalizedError, RuntimeError):
    """字幕配音的领域错误。带文案 key(`dubErr_*`),按读的人的语言翻(见 core/i18n)。"""


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


def dub_targets(db: Session, sequence_id: str, clip_ids: list[str], track_id: str = "") -> list[str]:
    """「这次配哪几条」—— 剪辑台、智能体、工作流三个入口共用的那一条规则。

    - 点名了条目:就是这些;给了 `track_id` 时只取那条轨上的。
    - 没点名:整条字幕轨(见 subtitle_clip_ids)。

    条目跨了两条字幕轨由 start_subtitle_dub 拒绝(双语分两条轨时两种语言会被一起念出来)。
    """
    if not clip_ids:
        return subtitle_clip_ids(db, sequence_id, track_id)
    if not track_id:
        return list(clip_ids)
    return [clip_id for clip_id in clip_ids if (clip := db.get(Clip, clip_id)) is not None and clip.track_id == track_id]


def subtitle_clip_ids(db: Session, sequence_id: str, track_id: str = "") -> list[str]:
    """「要配的那批」的默认答案:一条字幕轨上的全部字幕条,按时间顺序。

    剪辑台上这批是用户框选出来的,所以接口收的是一列 id。但别的入口没有选区 —— 智能体那边
    "把这个视频配上音"说的就是整条轨,让模型先跑一遍检视、把几十个 id 抄回来只是仪式,而且
    抄漏一条就是少配一句。规则放在这儿而不是某个入口里:两边说的是同一件事。
    """
    tracks = [
        track
        for track in db.scalars(select(Track).where(Track.sequence_id == sequence_id))
        if track.kind == "subtitle" and (not track_id or track.id == track_id)
    ]
    if track_id and not tracks:
        raise DubError("dubErr_subtitleTrackNotFound")
    if not tracks:
        raise DubError("dubErr_noSubtitleTrack")
    if not track_id and len(tracks) > 1:
        # 多条字幕轨时不替用户挑:双语视频常见的形态就是原文一条、译文一条,挑错了配出来的是另一种语言。
        raise DubError("dubErr_multipleSubtitleTracks")
    clips = [clip for clip in db.scalars(select(Clip).where(Clip.track_id == tracks[0].id))]
    return [clip.id for clip in sorted(clips, key=lambda clip: clip.timeline_start)]


def start_subtitle_dub(
    db: Session,
    *,
    sequence_id: str,
    clip_ids: list[str],
    match_duration: bool,
    created_by: str | None,
    synthesis: dict,
    line: str = "all",
    original_audio: str = DEFAULT_ORIGINAL_AUDIO,
) -> Job:
    """给这些字幕条排一次配音。`synthesis` 原样转交 voices.start_synthesis(音色/引擎那一套);
    `original_audio` 是配好之后原声怎么办(见 voices/original_audio)。"""
    try:
        ensure_original_audio_mode(original_audio, owner_user_id=created_by)
    except OriginalAudioError as exc:
        # 传 key 和参数而不是 str(exc):后者会把句子冻成此刻的语言。
        raise DubError(exc.key, **exc.params) from exc
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise DubError("dubErr_sequenceNotFound")
    clips = _subtitle_clips(db, sequence_id, clip_ids, line)
    if not clips:
        raise DubError("dubErr_nothingToDub")
    if len({clip.track_id for clip in clips}) > 1:
        # **一次只配一条字幕轨。** 双语视频常见的形态是原文一条、译文一条:两条一起配,同一秒上一句念原文、
        # 一句念译文。剪辑台此前把所有字幕轨的条目一股脑交下来,而后端照单全收(探针 P2)。
        raise DubError("dubErr_clipsAcrossSubtitleTracks")

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
            "original_audio": original_audio,
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
                raise DubError("dubErr_childMissing")
            if child.status == "succeeded":
                asset_id = (child.result or {}).get("asset_id")
                if not asset_id:
                    raise DubError("dubErr_childNoAudio")
                return str(asset_id)
            if child.status == "failed":
                # 子任务的失败原因带 key 就接着带 key 走;不带 key 的是一句现成的话(第三方原文)。
                if child.error_key:
                    raise DubError(child.error_key, **(child.error_params or {}))
                raise DubError(child.error or "dubErr_childFailed")
        time.sleep(_POLL_SECONDS)
    #: 不等了就把它取消掉:它还排着或还在跑,不取消的话它照样合成完(照样计费)、落一段没人用的音频,
    #: 而这一句已经按失败记了。
    with unit_of_work() as db:
        child = db.get(Job, job_id)
        if child is not None:
            cancel_job_tree(db, child)
    raise DubError("dubErr_childTimeout")


def _speed_for(audio_seconds: float, slot_seconds: float, room_seconds: float | None = None) -> float | None:
    """这段配音用多少倍速播放。

    先按「正好占满这条字幕」算(倍速 = 音频时长 / 段落时长,音频 6 秒塞进 3 秒就是 2 倍速),夹在
    _MIN_SPEED–_MAX_SPEED 里。要快过 _MAX_SPEED 才塞得进时,**先占用到下一句开始之前的空当**
    (`room_seconds`,见 _room_for:同一条字幕轨上的下一条,后面没有字幕了就到原片结束):能在空当里念完就不必念那么快,
    还是放不下就按 _MAX_SPEED 念,尾巴压到下一句上(这样的条数和秒数在结果里报出来,见 _run_dub)。占空当时不放慢
    (不低于原速)。不知道空当(None)就只按这条字幕自己的长度算。

    两个时长里任何一个不是正数,就没有倍速可言 —— 返回 None,让调用方保持原速,而不是拿一个算出来的 0 或 inf 去写库。
    """
    if audio_seconds <= 0 or slot_seconds <= 0:
        return None
    wanted = audio_seconds / slot_seconds
    if wanted <= _MAX_SPEED:
        return max(_MIN_SPEED, wanted)
    return min(_MAX_SPEED, max(1.0, audio_seconds / max(room_seconds or 0.0, slot_seconds)))


def _room_for(db: Session, clip: Clip | None) -> float | None:
    """这条字幕的配音念不完时,最多能占用到哪(从这条开始算的秒数)。

    **按整条字幕轨算,不按这一批。** 剪辑台上只配选中的那几句时,没选的那几句照样在轨上、照样有人念(或者原声在说);
    只看这一批的话,选中的最后一句会以为后面全是空的,一路念到别人那句上。此前就是这样,而且「后面没有了」
    时直接原速念完 —— 可能一路念过片尾。

    后面没有字幕了:到原片(时间线上除字幕轨、配音轨之外的内容)结束为止。
    """
    from app.domain.sequences.append import track_end

    if clip is None:
        return None
    following = [one.timeline_start for one in db.scalars(select(Clip).where(Clip.track_id == clip.track_id))
                 if one.timeline_start > clip.timeline_start + 1e-6]
    if following:
        return min(following) - clip.timeline_start
    sequence = db.get(Sequence, clip.sequence_id)
    end = max((track_end(track) for track in (sequence.tracks if sequence else [])
               if track.kind != "subtitle" and track.role != "dub"), default=0.0)
    return max(0.0, end - clip.timeline_start)


#: 念出界不到这么多不算压到下一句(浮点和取整的误差)。
_OVERLAP_TOLERANCE = 0.05


def _dub_tracks(db: Session, sequence_id: str) -> list[Track]:
    """这条时间线上的配音轨(认 role,不认名字 —— 见 _dub_track)。"""
    return [track for track in db.scalars(select(Track).where(Track.sequence_id == sequence_id))
            if track.kind == "audio" and track.role == "dub"]


def _line_identity(text: str, synthesis: dict) -> dict[str, str]:
    """一段配音「是哪一句、哪把嗓子念的」(见 DUB_LINE_KEY)。"""
    return {"text": text, "voice": voice_identity(synthesis)}


def _existing_dubs(db: Session, sequence_id: str, start: float, end: float) -> list[tuple[Clip, dict]]:
    """配音轨上**属于这一句**的那几段配音:起点落在这条字幕的时间窗里、素材上记着 DUB_LINE_KEY。

    按起点认、不按「有没有重叠」认:上一句 1.5 倍速也念不完时,它的尾巴会压进这一句的时间窗
    (见 _speed_for),那是上一句的配音 —— 重配这一句时把它删了,上一句就哑了。
    用户自己放到配音轨上的音频(素材上没有 DUB_LINE_KEY)一律不算:那不是配音这件事产出的。
    """
    found: list[tuple[Clip, dict]] = []
    for track in _dub_tracks(db, sequence_id):
        for clip in sorted(track.clips or [], key=lambda one: one.timeline_start):
            if not (start - _OVERLAP_TOLERANCE <= clip.timeline_start < end):
                continue
            asset = db.get(Asset, clip.asset_id) if clip.asset_id else None
            identity = (asset.media_info or {}).get(DUB_LINE_KEY) if asset is not None else None
            if isinstance(identity, dict):
                found.append((clip, identity))
    return found


def _run_dub(job_id: str) -> None:
    from app.domain.sequences.grouping import OperationGroup
    from app.domain.sequences.operations import DeleteClip, delete_clip

    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = job.payload or {}
        sequence_id = str(payload.get("sequence_id") or "")
        clip_ids = list(payload.get("clip_ids") or [])
        match_duration = bool(payload.get("match_duration"))
        line = str(payload.get("line") or "all")
        synthesis = dict(payload.get("synthesis") or {})
        original_audio = str(payload.get("original_audio") or "keep")
        # 现在取出来:commit 之后这些属性会过期,而 job 出了这个 with 就是 detached 的 ——
        # 到下一个 session 里再读 job.created_by 会去刷一个已经关掉的连接。
        created_by = job.created_by
        #: 每条字幕念不完时最多能占用到哪(见 _room_for)。按任务开始这一刻的时间线算。
        rooms = [_room_for(db, db.get(Clip, cid)) for cid in clip_ids]
        # 状态一律经 finish_job 写:排队时就被取消的,不能在这里被写回 running。
        if not finish_job(db, job, status="running"):
            return
        emit_job_event(db, job.id, "job.running", {})

    from app.domain.voices.voices import start_synthesis

    #: **整次配音在撤销栈上是一步。** 建轨、每句的插入与调速、删掉被重配替换的旧配音、原声处理,
    #: 全部记进这一组(见 sequences/grouping)—— 此前一句 3 步,1000 句是两千多次 ⌘Z。
    group = OperationGroup(sequence_id, label="subtitle_dub", actor_id=created_by)
    done = 0
    failed = 0
    #: 同一句、同一把嗓子、同样的文本已经配过的:不再合成(那是一次付费调用),也不再叠一段。
    #: 中途断了的配音再跑一遍,就只补缺的那几句。
    skipped = 0
    #: 1.5 倍、占满空当还是念不完,压到下一句(或念过片尾)的条数和秒数 —— 如实报出来,不静默叠着念。
    #: 不顺延后一句:顺延会把后面每一句都推离它自己的字幕和画面,错得更多、也更难找。
    overlaps = 0
    overlap_seconds = 0.0
    track_id = ""
    total = len(clip_ids)
    try:
        for index, clip_id in enumerate(clip_ids):
            # 每一句各自一个事务:配好的那几句不因为后面哪一句出错而跟着没了。
            with unit_of_work() as db:
                clip = db.get(Clip, clip_id)
                if clip is None:
                    failed += 1
                    continue
                text = dub_text(clip.text_override or "", line)
                slot_seconds = max(0.0, (clip.src_out - clip.src_in) / (clip.speed or 1.0))
                timeline_start = clip.timeline_start
                slot_end = timeline_start + max(slot_seconds, _OVERLAP_TOLERANCE)
                existing = _existing_dubs(db, sequence_id, timeline_start, slot_end)
                if any(identity == _line_identity(text, synthesis) for _, identity in existing):
                    skipped += 1
                    track_id = track_id or existing[0][0].track_id
                    job = db.get(Job, job_id)
                    if not finish_job(db, job, status="running", progress=(index + 1) / max(1, total)):
                        return
                    say(job, "jobMsg_dubRunning", done=done + skipped, total=total)
                    continue
                sequence = db.get(Sequence, sequence_id)
                try:
                    child = start_synthesis(
                        db,
                        text=text,
                        project_id=sequence.project_id if sequence else None,
                        created_by=created_by,
                        #: 每一句都是这次配音的零件:时间线、配音轨用它,素材库不列(见 domain/assets/intermediates)。
                        intermediate=DUB_LINE,
                        **synthesis,
                    )
                except JobError:
                    # 这次配音已经收尾(用户取消,或外面那条工作流取消后级联下来):总线不再让它
                    # 派下一句。每一句都是一次付费合成,到此为止。这一句什么都不留。
                    db.rollback()
                    return
                child_id = child.id

            try:
                asset_id = _await_child(child_id)
            except DubError as exc:
                # 一条失败不该拖垮整批:已经配好的那些留在轨上,失败的条数最后报出来。
                # 这一句原来的配音(换嗓子之前那段)也留着 —— 新的没配成,不能先把旧的删了。
                failed += 1
                logger.warning("字幕配音:第 %s 条失败:%s", index + 1, str(exc)[:200])
                continue

            with unit_of_work() as db, group.collect(db):
                asset = db.get(Asset, asset_id)
                audio_seconds = float((asset.media_info or {}).get("duration") or 0.0) if asset else 0.0
                if audio_seconds <= 0:
                    failed += 1
                    continue
                # **重配是替换,不是叠加。** 这一句原来的配音(换了嗓子、改了字之后再配一次)先整段删掉 ——
                # 放下即覆盖(sequences/coverage)只裁掉新这段盖住的那一截:新配的比旧的短时,旧配音的尾巴
                # 还留在轨上接着念。只删属于这一句的(见 _existing_dubs),而且到新的这段真配好了才删。
                for stale, _identity in _existing_dubs(db, sequence_id, timeline_start, slot_end):
                    delete_clip(db, sequence_id, DeleteClip(clip_id=stale.id, actor_id=created_by))
                patch_media_info(db, asset_id, {DUB_LINE_KEY: _line_identity(text, synthesis)})
                # 落哪条轨:**已有配音轨就用它**,没有才新建。每配一次多一条轨的话,改几句台词
                # 重配几段,时间线上就摞起一叠只有一两段音频的轨。
                #
                # 而且只在**第一条音频真的要落地的这一刻**才建。建在合成之前的话,一次全军覆没的
                # 配音会留下一条空轨 —— 空轨看起来和「配音没生成」一模一样,用户先怀疑的是功能坏了,
                # 不是那次失败(这条 bug 就是这么被报上来的)。
                if not track_id:
                    track_id = _dub_track(db, sequence_id, created_by)
                speed = _speed_for(audio_seconds, slot_seconds, rooms[index]) if match_duration else None
                # 倍速随插入一起给:同一条配音轨上不叠两段(覆盖),先按 1 倍放下的话,多出来的那截
                # 会先把下一句已有的配音裁掉,再改速也找不回来。
                insert_clip(
                    db,
                    sequence_id,
                    InsertClip(
                        track_id=track_id,
                        asset_id=asset_id,
                        timeline_start=timeline_start,
                        src_in=0.0,
                        src_out=audio_seconds,
                        speed=speed or 1.0,
                        actor_id=created_by,
                    ),
                )
                if rooms[index] is not None:
                    over = audio_seconds / (speed or 1.0) - max(rooms[index], slot_seconds)
                    if over > _OVERLAP_TOLERANCE:
                        overlaps += 1
                        overlap_seconds += over
                done += 1
                job = db.get(Job, job_id)
                if not finish_job(db, job, status="running", progress=(index + 1) / max(1, total)):
                    return
                say(job, "jobMsg_dubRunning", done=done + skipped, total=total)

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if done == 0 and skipped == 0:
                #: 失败原因和任务消息同一条规矩:落库存 key,出口按读的人的语言翻。
                if finish_job(
                    db, job, status="failed",
                    error_key="jobErr_noDubSucceeded", error=t("jobErr_noDubSucceeded", DEFAULT_LOCALE),
                ):
                    say(job, "jobMsg_dubFailed")
                    emit_job_event(db, job.id, "job.failed", {})
                return
            # 先确认没被取消 —— 取消了的配音不该再去动原片的音轨。
            if not finish_job(db, job, status="running"):
                return

        # 原声的处理放在**任务里**、成功之前:分离要跑一阵,而任务说"完成"时成片应当已经是
        # 最终的样子。它自己管会话(分离要先拿渲染名额、再开会话,见 original_audio),
        # 改时间线的那几步记进同一组,和配音一起一步撤销。
        applied = apply_original_audio(sequence_id, track_id, original_audio, actor_id=created_by, group=group)

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            # 部分失败也是成功的一种:配好的那些是真的配好了。但**不能都说成「完成」** ——
            # 「10 条里成了 9 条」说成「配音完成」,用户要到时间线上一段段找才发现少了一条。
            result = {"track_id": track_id, "done": done, "failed": failed, "skipped": skipped,
                      "original_audio": applied, "overlaps": overlaps, "overlap_seconds": round(overlap_seconds, 1)}
            if finish_job(db, job, status="succeeded", progress=1.0, result=result):
                seconds = f"{overlap_seconds:.1f}"
                if failed and overlaps:
                    say(job, "jobMsg_dubPartialOverlap", done=done, failed=failed, overlaps=overlaps, seconds=seconds)
                elif failed:
                    say(job, "jobMsg_dubPartial", done=done, failed=failed)
                elif overlaps:
                    say(job, "jobMsg_dubDoneOverlap", done=done, overlaps=overlaps, seconds=seconds)
                elif skipped:
                    say(job, "jobMsg_dubDoneSkipped", done=done, skipped=skipped)
                else:
                    say(job, "jobMsg_dubDone", done=done)
                emit_job_event(db, job.id, "job.succeeded", {"track_id": track_id})
    except Exception as exc:  # noqa: BLE001 — 任何意外都要落进任务行,否则会话永远停在 running
        logger.exception("字幕配音任务 %s 失败", job_id)
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_dubFailed")
                emit_job_event(db, job.id, "job.failed", {})


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
    return track.id


