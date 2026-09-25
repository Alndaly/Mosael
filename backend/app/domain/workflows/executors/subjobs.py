"""子任务型节点:复用既有 job 执行器(转写/导出/生成/配音/发布),轮询其终态。

领域模块在这里以「适配器调用」出现:每个执行器只调对应领域的启动函数 + wait_for_job,
不掺杂领域内部逻辑——这是工作流引擎与各领域之间的接缝。
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, Transcript
from app.domain.sequences.errors import SequenceDomainError
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import RunScope, register
from app.domain.jobs import current_actor
from app.domain.workflows.executors.common import id_list, provided, text_lines, truthy, wait_for_job

logger = logging.getLogger(__name__)


def _compact_timed_text(segments: list[dict[str, Any]]) -> str:
    """把完整逐字稿编码成适合 LLM 的紧凑 JSON。

    段落正文不能省：ASR token 常省略标点，偶尔还会缺少段尾。真正冗余的是每个字都重复一次
    ``start/end/text`` 字段名，以及每段都写空 speaker。token 改成按文档声明列顺序的短数组，
    仍保留每个词的精确起止时间和正文，供自动裁切安全定位。
    """
    compact: list[dict[str, Any]] = []
    for segment in segments:
        row: dict[str, Any] = {
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
        }
        if segment.get("speaker"):
            row["speaker"] = segment["speaker"]
        tokens = segment.get("tokens")
        if isinstance(tokens, list) and tokens:
            row["tokens"] = [[token["start"], token["end"], token["text"]] for token in tokens]
        compact.append(row)
    return json.dumps(
        {"token_columns": ["start", "end", "text"], "segments": compact},
        ensure_ascii=False,
        separators=(",", ":"),
    )


@register("transcribe_asset")
def transcribe_asset(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.voices.transcription import start_transcription

    # 收进工作区:转写结果会**返回到工作流输出里**,不挡等于让别的工作区的内容流出来。
    asset_id = _asset_in(db, scope, str(config.get("asset_id", "")).strip()).id
    child = start_transcription(
        db,
        asset_id,
        created_by=current_actor(db),
        engine=str(config.get("engine") or "auto"),
    )
    wait_for_job(child.id, release=db)
    transcript = db.scalars(
        select(Transcript).where(Transcript.asset_id == asset_id).order_by(Transcript.created_at.desc())
    ).first()
    if transcript is None:
        raise WorkflowDomainError("wfErr_transcriptMissing")
    db.refresh(transcript)
    segments = [
        {
            "start": segment.start_time,
            "end": segment.end_time,
            "text": segment.text,
            "speaker": segment.speaker or "",
            "tokens": [
                {"start": token.start_time, "end": token.end_time, "text": token.text}
                for token in segment.tokens
            ],
        }
        for segment in transcript.segments
    ]
    text = "\n".join(segment["text"] for segment in segments)
    # JSON 而不是 Python repr:模板把它嵌进 LLM 提示词时仍是一份机器可读、时间精确的逐字稿。
    timed_text = _compact_timed_text(segments)
    duration = max((float(segment["end"]) for segment in segments), default=0.0)
    return {
        "text": text,
        "timed_text": timed_text,
        "segments": segments,
        "language": transcript.language,
        "transcript_id": transcript.id,
        "duration": duration,
    }


@register("export_sequence")
def export_sequence(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.render import start_export

    # start_export 会把渲染任务建在**序列所属的那个工作区**(workspace_id=sequence.workspace_id),
    # 所以不挡的话,A 工作区的工作流能在 B 工作区里起一个渲染任务并拿到产出的 asset_id。
    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    child = start_export(db, sequence.id, created_by=current_actor(db))
    final = wait_for_job(child.id, release=db)
    asset_id = str((final.result or {}).get("asset_id", ""))
    return {"asset_id": asset_id}


@register("ai_generate")
def ai_generate(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import GenerationDomainError, keep_source_group, parse_source_assets
    from app.domain.generation.runner import start_generation_thread

    kind = str(config.get("kind", "image")).strip() or "image"
    # 声明里模型是必填的;错误(包括"没有可用模型")按工作流错误报出来。
    try:
        generation, child = create_generation_job(
            db,
            workspace_id=scope.workspace_id,
            session_id=None,
            project_id=None,
            created_by=current_actor(db),
            provider=str(config.get("provider", "")),
            provider_profile_id=str(config.get("provider_profile_id") or "").strip() or None,
            model=str(config.get("model", "")),
            kind=kind,
            prompt=str(config.get("prompt", "")),
            negative_prompt=str(config.get("negative_prompt", "")),
            parameters=provided(dict(config.get("parameters") or {})),
            source_assets=keep_source_group(
                parse_source_assets(config.get("source_assets"), kind=kind),
                str(config.get("source_group") or "all").strip(),
            ),
        )
    except GenerationDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    db.commit()
    start_generation_thread(generation.id)
    wait_for_job(child.id, release=db)
    db.refresh(generation)
    db.refresh(child)
    #: asset_id 是**封面**(下游多数节点只接一份),asset_ids 是全部 —— 生成一次可能出多张
    #: (图像接口的 n),只往下游传第一张的话,其余的在工作流里就没人看得见了。
    asset_ids = [str(one) for one in ((child.result or {}).get("asset_ids") or []) if one]
    return {
        "asset_id": generation.result_asset_id or "",
        "asset_ids": asset_ids,
        "generation_id": generation.id,
    }


@register("video_to_gif")
def video_to_gif(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.assets.video_gif import VideoGifError, start_video_to_gif

    asset = db.get(Asset, str(config.get("asset_id") or ""))
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_gifAssetNotInWorkspace")
    try:
        child = start_video_to_gif(
            db,
            asset=asset,
            created_by=current_actor(db),
            fps=int(config.get("fps") or 12),
            width=int(config.get("width") or 720),
            start=float(config.get("start") or 0),
            duration=float(config["duration"]) if config.get("duration") not in (None, "") else None,
        )
    except VideoGifError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    final = wait_for_job(child.id, release=db)
    return {
        "asset_id": str((final.result or {}).get("asset_id") or ""),
        "source_asset_id": asset.id,
    }


def _speech_params(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """「引擎 + 音色」两格 → 合成要的那组参数(见 voices.engine_catalog.synthesis_params)。

    音色的报错原样转述(带着它的 key):此前在前面拼一截「语音合成」/「字幕配音」,那截是
    写死的中文,而原因在落库那一刻就被翻成了字 —— 英文界面里读到的是两段中文。"""
    from app.domain.voices.engine_catalog import synthesis_params
    from app.domain.voices.voices import VoiceError

    try:
        return synthesis_params(
            db,
            engine=str(config.get("engine") or ""),
            voice=str(config.get("voice") or ""),
            speed=float(config.get("speed") or 1.0),
            user_id=current_actor(db),
            workspace_id=scope.workspace_id,
        )
    except VoiceError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


@register("synthesize_speech")
def synthesize_speech(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把文本念出来。音色是一格,引擎决定它指什么(见 `_speech_params`)。"""
    from app.domain.voices.voices import start_synthesis

    child = start_synthesis(
        db,
        text=str(config.get("text", "")),
        project_id=None,
        created_by=current_actor(db),
        **_speech_params(db, scope, config),
    )
    final = wait_for_job(child.id, release=db)
    return {"asset_id": str((final.result or {}).get("asset_id", ""))}


@register("publish")
def publish(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import Asset, PublishAccount
    from app.domain.publish import start_publish

    account = db.get(PublishAccount, str(config.get("account_id", "")))
    if account is None or account.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_publishAccountMissing")
    asset = db.get(Asset, str(config.get("asset_id", "")))
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_publishAssetMissing")
    # 用的是**这次运行**的授权:操作人(手动运行是点运行的人,定时任务 / webhook 是任务主人,
    # 见 scheduler.operations._open_run),加上被执行那一版图的担保人(见 workflows.authority)。
    # 别人的私有账号、同事改过而主人没认可的那一版,都在 start_publish 里被拒。
    from app.domain.workflows.authority import current_authority

    task = start_publish(
        db,
        workspace_id=scope.workspace_id,
        account=account,
        asset=asset,
        title=str(config.get("title", "")),
        description=str(config.get("description", "")),
        actor=current_authority(db),
        tags=[],
    )
    final = wait_for_job(task.job_id or "", release=db)
    result = final.result or {}
    post = result.get("post") if isinstance(result.get("post"), dict) else {}
    return {"post_id": str(post.get("post_id") or ""), "post_url": str(post.get("url") or ""), "result": result}



@register("edit_timeline")
def edit_timeline(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一组操作应用到时间线上。

    智能体早就能做这件事(edit_timeline 工具),而工作流只能「导出序列」—— 于是「生成素材
    → 编排 → 导出」这条最常见的链路,中间那步在画布上做不了,必须切去对话里或者手动摆。

    操作的种类和智能体那边**是同一份**(domain/sequences/operations.EDIT_OP_KINDS)——
    不是抄一遍,是同一个清单。
    """
    from app.domain.sequences.operations import apply_edit_operations

    # **过 _sequence_in,和这一族的其它节点一样。** 此前这里只判了非空就把 id 交下去,而
    # apply_edit_operations 没有工作区的概念 —— 于是 A 工作区的工作流能改 B 工作区的时间线。
    # sequence_id 常常来自上游节点,而上游拿得到任何地方的 id。
    #
    # 智能体走同一个算子却不受影响:它在确认卡**建立时**就查过归属(见 agent/confirmations
    # 的 _validate_payload)。漏的只有这一条路。
    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    sequence_id = sequence.id
    operations = config.get("operations")
    if isinstance(operations, str):
        # 上游节点常常给一段 JSON 文本(比如 code 节点算出来的),接住它省得再加一个解析节点。
        try:
            operations = json.loads(operations)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError("wfErr_operationsNotJson", params={"reason": exc}) from exc
    if not isinstance(operations, list) or not operations:
        raise WorkflowDomainError("wfErr_operationsEmpty")
    try:
        applied = apply_edit_operations(db, sequence_id, operations)
    except SequenceDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    db.commit()
    sequence = db.get(Sequence, sequence_id)
    return {"applied": applied, "sequence_id": sequence_id, "revision": sequence.revision if sequence else 0}


@register("inspect_sequence")
def inspect_sequence(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """看一眼时间线现在长什么样 —— 编排之前得先知道有哪些轨道、片段排到了第几秒。

    智能体有对应的工具;工作流此前只能盲改。
    """
    sequence_id = str(config.get("sequence_id", "")).strip()
    if not sequence_id:
        raise WorkflowDomainError("wfErr_inspectNeedsSequence")
    sequence = db.get(Sequence, sequence_id)
    if sequence is None or sequence.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_sequenceNotInWorkspace")
    tracks = [
        {
            "id": track.id,
            "kind": track.kind,
            "clips": [
                {
                    "id": clip.id,
                    "asset_id": clip.asset_id,
                    "timeline_start": clip.timeline_start,
                    "src_in": clip.src_in,
                    "src_out": clip.src_out,
                    "speed": clip.speed or 1.0,
                }
                for clip in (track.clips or [])
            ],
        }
        for track in (sequence.tracks or [])
    ]
    duration = max(
        (clip["timeline_start"] + (clip["src_out"] - clip["src_in"]) / clip["speed"] for track in tracks for clip in track["clips"]),
        default=0.0,
    )
    # 顺手把第一条视频/音频轨的 id 摆出来 —— 下游「接素材」想指定轨道时,不用自己去
    # tracks 里翻。绝大多数时间线各只有一条。
    def first(kind: str) -> str:
        return next((one["id"] for one in tracks if one["kind"] == kind), "")

    return {
        "sequence_id": sequence.id,
        "revision": sequence.revision,
        "tracks": tracks,
        "duration": duration,
        "video_track_id": first("video"),
        "audio_track_id": first("audio"),
    }


def _asset_in(db: Session, scope: RunScope, asset_id: str) -> Asset:
    """取这份素材,并确认它属于这次运行所在的工作区。和 _sequence_in 成对。

    asset_id 同样常常来自上游节点。少了这一条,A 工作区的工作流能转写 B 工作区的素材
    ——而转写结果是**要返回到工作流输出里**的,那是把别人的内容读出来。
    """
    if not asset_id:
        raise WorkflowDomainError("wfErr_assetIdMissing")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_assetNotInWorkspace")
    return asset


def _sequence_in(db: Session, scope: RunScope, sequence_id: str) -> Sequence:
    """取这条序列,并确认它属于这次运行所在的工作区。

    sequence_id 常常来自上游节点,而上游可能拿到任何地方的 id —— 这一条挡的是
    「用 A 工作区的工作流去改 B 工作区的时间线」。
    """
    if not sequence_id:
        raise WorkflowDomainError("wfErr_sequenceIdMissing")
    sequence = db.get(Sequence, sequence_id)
    if sequence is None or sequence.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_sequenceNotInWorkspace")
    return sequence


#: 图片进时间线时的默认定格时长。图片没有 duration,不给个默认值的话 src_out 是 0,
#: 整段会被判为空而拒掉 —— 而"把一张图接到时间线上"是很常见的用法。
STILL_SECONDS = 5.0

#: 素材种类 → 该进哪种轨道。没列的(图片)按视频走 —— 图片在时间线上就是一段定格视频。
_TRACK_FOR_ASSET = {"audio": "audio"}


@register("timeline_append")
def timeline_append(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一份素材接到轨道上 —— 默认接在末尾,也可以放在指定的那一秒。

    **这是编排里占九成的动作**,所以它是一个有真表单的节点,而不是让人手写一条
    `{"kind": "insert_clip", "timeline_start": …}` —— 那个 timeline_start 还得自己算,
    而"接到末尾"本来就该由机器算。
    """
    from app.domain.sequences.operations import InsertClip, SetClipSpeed, insert_clip, set_clip_speed, timeline_span

    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    asset_id = str(config.get("asset_id", "")).strip()
    if not asset_id:
        raise WorkflowDomainError("wfErr_assetIdMissing")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_assetNotInWorkspace")

    tracks = list(sequence.tracks or [])
    track_id = str(config.get("track_id", "")).strip()
    if track_id:
        track = next((one for one in tracks if one.id == track_id), None)
        if track is None:
            raise WorkflowDomainError("wfErr_trackNotOnSequence")
    else:
        # 留空就挑第一条同类轨道 —— 绝大多数时间线只有一条视频轨和一条音频轨,
        # 逼用户先跑一个「看一眼时间线」把 id 取出来是纯仪式。
        want = _TRACK_FOR_ASSET.get(asset.kind, "video")
        track = next((one for one in tracks if one.kind == want), None)
        if track is None:
            raise WorkflowDomainError("wfErr_noSuchTrackKind", params={"kind": want})

    # 截取范围:留空就是整段素材。
    src_in = float(config.get("start") or 0.0)
    src_out = config.get("end")
    # 时长在 media_info 里,不是独立列(见 domain/assets/importer 的探测)。
    # 图片没有 duration —— 给它一个默认的定格时长,否则 src_out 会是 0、整段被判为空。
    probed = (asset.media_info or {}).get("duration")
    fallback = float(probed) if probed else (STILL_SECONDS if asset.kind == "image" else 0.0)
    src_out = float(src_out) if src_out not in (None, "") else fallback
    if src_out <= src_in:
        raise WorkflowDomainError("wfErr_trimRange")

    # 落点:给了 `at` 就放在那一秒(口播要对齐它那一镜的画面,而不是接在上一段口播后面);
    # 没给就接到末尾 —— 这条轨道上最后一个片段的终点,空轨道就是 0。
    at = config.get("at")
    if at not in (None, ""):
        timeline_start = float(at)
        if timeline_start < 0:
            raise WorkflowDomainError("wfErr_startNegative")
    else:
        timeline_start = max(
            (clip.timeline_start + timeline_span(clip) for clip in (track.clips or [])),
            default=0.0,
        )
    clip = insert_clip(
        db,
        sequence.id,
        InsertClip(
            track_id=track.id,
            asset_id=asset.id,
            timeline_start=timeline_start,
            src_in=src_in,
            src_out=src_out,
        ),
    )
    span = src_out - src_in
    speed = _fit_speed(span, config.get("max_duration"))
    if speed is not None:
        db.refresh(sequence)  # 版本号以库里为准:并行分支可能刚改过这条时间线
        set_clip_speed(db, sequence.id, SetClipSpeed(clip_id=clip.id, speed=speed))
        span = span / speed
    return {
        "clip_id": clip.id,
        "timeline_start": timeline_start,
        "timeline_end": timeline_start + span,
        "sequence_id": sequence.id,
    }


#: 为了塞进 max_duration 最多加速到多少。再快就听不清了 —— 宁可让它超出去,也不交一段
#: 听不懂的口播(超出多少,调用方从 timeline_end 看得到)。
MAX_FIT_SPEEDUP = 1.5


def _fit_speed(span: float, max_duration: Any) -> float | None:
    """片段比 max_duration 长时该用的倍速;不需要变就是 None。**只加速,不减速** ——
    一段话比它的位置短是正常的,拉慢了反而拖沓。"""
    if max_duration in (None, ""):
        return None
    limit = float(max_duration)
    if limit <= 0 or span <= limit:
        return None
    return round(min(MAX_FIT_SPEEDUP, span / limit), 3)


@register("timeline_add_track")
def timeline_add_track(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.sequences.operations import AddTrack, add_track

    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    kind = str(config.get("kind", "video")).strip() or "video"
    before = {one.id for one in (sequence.tracks or [])}
    add_track(db, sequence.id, AddTrack(kind=kind))
    db.commit()
    db.refresh(sequence)
    created = next((one.id for one in (sequence.tracks or []) if one.id not in before), "")
    return {"track_id": created, "sequence_id": sequence.id}


@register("timeline_clear")
def timeline_clear(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """删掉所有片段,轨道留着。

    留着轨道是有意的:重跑一条工作流时,下游的「接素材」还指望那几条轨道在。
    """
    from app.domain.sequences.operations import DeleteClip, delete_clip

    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    clip_ids = [clip.id for track in (sequence.tracks or []) for clip in (track.clips or [])]
    for clip_id in clip_ids:
        delete_clip(db, sequence.id, DeleteClip(clip_id=clip_id))
    db.commit()
    return {"removed": len(clip_ids), "sequence_id": sequence.id}


@register("timeline_cut_ranges")
def timeline_cut_ranges(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一次删除同一片段的多个源时间范围，并把保留段首尾相接。

    不能循环调用 cut_clip_range：第一次裁切后原 clip_id 已经不存在。批量算子在删除原片段前先
    归并全部范围，因此正好承接逐字稿分析节点产出的多个停顿、口头禅和重录区间。
    """
    from app.domain.sequences.operations import CutClipRanges, cut_clip_ranges

    sequence = _sequence_in(db, scope, str(config.get("sequence_id") or "").strip())
    clip_id = str(config.get("clip_id") or "").strip()
    if not clip_id:
        raise WorkflowDomainError("wfErr_cutNeedsClip")
    clip = db.get(Clip, clip_id)
    if clip is None or clip.sequence_id != sequence.id:
        raise WorkflowDomainError("wfErr_clipNotOnSequence")
    try:
        confidence_raw = config.get("min_confidence")
        ratio_raw = config.get("max_removal_ratio")
        min_confidence = float(0 if confidence_raw in (None, "") else confidence_raw)
        max_removal_ratio = float(1 if ratio_raw in (None, "") else ratio_raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_ratioNumbers") from exc
    if not 0 <= min_confidence <= 1 or not 0 <= max_removal_ratio <= 1:
        raise WorkflowDomainError("wfErr_ratioRange")
    raw_ranges = config.get("ranges")
    if isinstance(raw_ranges, str):
        try:
            raw_ranges = json.loads(raw_ranges)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError("wfErr_rangesNotJson", params={"reason": exc}) from exc
    if not isinstance(raw_ranges, list):
        raise WorkflowDomainError("wfErr_rangesArray")

    ranges: list[tuple[float, float]] = []
    normalized: list[dict[str, Any]] = []
    for item in raw_ranges:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("src_start"))
            end = float(item.get("src_end"))
        except (TypeError, ValueError):
            continue
        try:
            confidence = float(item.get("confidence", 1))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or not math.isfinite(confidence):
            continue
        if confidence < min_confidence:
            continue
        start = max(start, clip.src_in)
        end = min(end, clip.src_out)
        if end <= start:
            continue
        ranges.append((start, end))
        normalized.append({**item, "src_start": start, "src_end": end})
    if not ranges:
        return {
            "removed": 0,
            "removed_seconds": 0.0,
            "ranges": [],
            "sequence_id": sequence.id,
            "revision": sequence.revision,
        }

    merged = _merged_ranges(ranges)
    removed_seconds = sum(end - start for start, end in merged)
    source_seconds = max(clip.src_out - clip.src_in, 0.001)
    if removed_seconds / source_seconds > max_removal_ratio + 1e-9:
        raise WorkflowDomainError(
            "wfErr_cleanupTooMuch",
            params={"seconds": f"{removed_seconds:.2f}", "ratio": f"{max_removal_ratio:.0%}"},
        )
    try:
        cut_clip_ranges(db, sequence.id, CutClipRanges(clip_id=clip_id, ranges=tuple(ranges)))
    except SequenceDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    db.refresh(sequence)
    return {
        "removed": len(ranges),
        "removed_seconds": round(removed_seconds, 3),
        "ranges": normalized,
        "sequence_id": sequence.id,
        "revision": sequence.revision,
    }


def _merged_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _yes_no(config: dict[str, Any], key: str, *, default: bool) -> bool:
    """是/否型配置。**留空不是"否"** —— 它是"没设过",该落到节点自己的默认值上。

    节点声明里的 `default` 是给表单预选用的,不会写进 config(见 WorkflowsView 的 OptionPicker),
    所以执行体得自己兜住那一档;否则"默认开"的选项对每一条没动过它的工作流都是关的。
    """
    raw = str(config.get(key, "")).strip()
    return truthy(raw) if raw else default


def _segments_in(value: Any) -> list[dict[str, Any]]:
    """上游给的逐字稿段落。接列表,也接一串 JSON —— 手填时它只能是文本。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError("wfErr_segmentsNotJson", params={"reason": exc}) from exc
    if not isinstance(value, list):
        raise WorkflowDomainError("wfErr_segmentsArray")
    return [item for item in value if isinstance(item, dict)]


def _field(item: dict[str, Any], path: str) -> Any:
    """按点号路径取嵌套字段(`append.timeline_start`),取不到就是空串 —— 与模板插值同一个约定。"""
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part, "")
    return current


def _subtitle_track(db: Session, sequence: Sequence, track_id: str) -> str:
    """字幕落到哪条轨:指定了就用它,没指定就用第一条字幕轨,一条都没有就新建。

    「没有就新建」不是省事,是这个节点在工作流里的常态 —— 上游 project_sequence_create 建出来的
    新时间线只有视频轨和音频轨,而逼用户先接一个「加轨道」节点,只是把机器能算的事推给人。
    """
    from app.domain.sequences.operations import AddTrack, add_track

    tracks = list(sequence.tracks or [])
    if track_id:
        track = next((one for one in tracks if one.id == track_id), None)
        if track is None:
            raise WorkflowDomainError("wfErr_trackNotOnSequence")
        if track.kind != "subtitle":
            raise WorkflowDomainError("wfErr_subtitlesOnSubtitleTrack")
        return track.id
    existing = [one for one in tracks if one.kind == "subtitle"]
    if existing:
        return min(existing, key=lambda one: one.position).id
    before = {one.id for one in tracks}
    add_track(db, sequence.id, AddTrack(kind="subtitle"))
    db.commit()
    db.refresh(sequence)
    created = next((one.id for one in (sequence.tracks or []) if one.id not in before), "")
    if not created:
        raise WorkflowDomainError("wfErr_subtitleTrackFailed")
    return created


@register("generate_subtitles")
def generate_subtitles(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把逐字稿段落批量插成时间线上的字幕条。

    **时间码来自 segments,文本可以来自别处**:这正是"翻译后配字幕"需要的形状 —— 译文是逐条
    重写的,而每一条该出现在第几秒完全由原始段落决定。两者分成两个入参而不是让上游拼出一份
    新段落数组,是因为模板插值产出的是字符串:把译文塞回 JSON 里,遇到带引号的台词就散架。

    条数对不上直接报错,不截断。少一条就意味着从那一条起**每一句字幕都配错了时间**,而截断后
    的成片看起来是完整的 —— 那种错要等到有人从头看一遍才发现。
    """
    from app.domain.sequences.operations import GenerateSubtitles
    from app.domain.sequences.operations import generate_subtitles as generate

    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    segments = _segments_in(config.get("segments"))
    allow_empty = _yes_no(config, "allow_empty", default=False)
    nothing = {"track_id": "", "clip_ids": [], "count": 0, "sequence_id": sequence.id}
    if not segments:
        if allow_empty:
            return nothing
        raise WorkflowDomainError("wfErr_noSegments")
    lines = text_lines(config.get("texts"))
    if lines and len(lines) != len(segments):
        raise WorkflowDomainError("wfErr_linesSegmentsMismatch", params={"lines": len(lines), "segments": len(segments)})
    keep_original = _yes_no(config, "keep_original", default=False)
    try:
        offset = float(config.get("offset") or 0.0)
    except (TypeError, ValueError):
        raise WorkflowDomainError("wfErr_offsetSeconds") from None

    start_field = str(config.get("start_field") or "start").strip()
    end_field = str(config.get("end_field") or "end").strip()
    text_field = str(config.get("text_field") or "text").strip()
    cues: list[tuple[str, float, float]] = []
    for index, segment in enumerate(segments):
        try:
            start = float(_field(segment, start_field) or 0.0)
            end = float(_field(segment, end_field) or 0.0)
        except (TypeError, ValueError):
            raise WorkflowDomainError("wfErr_segmentTimecode", params={"index": index + 1}) from None
        original = str(_field(segment, text_field) or "").strip()
        text = lines[index].strip() if lines else original
        if keep_original and lines and original and original != text:
            # 原文在上、译文在下 —— 和「字幕配音」的 line=last 正好配套:看两行,只念译文。
            text = f"{original}\n{text}"
        if text and end > start:
            cues.append((text, start + offset, end - start))
    if not cues:
        if allow_empty:
            # 提前返回:连字幕轨都不建 —— 一条空轨挂在时间线上只会让人以为字幕丢了。
            return nothing
        raise WorkflowDomainError("wfErr_noUsableSegments")

    track_id = _subtitle_track(db, sequence, str(config.get("track_id", "")).strip())
    before = {clip.id for track in (sequence.tracks or []) for clip in (track.clips or [])}
    try:
        generate(db, sequence.id, GenerateSubtitles(track_id=track_id, cues=tuple(cues)))
    except SequenceDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    db.refresh(sequence)
    # 新插进去的那些。按落点排序 —— 下游要按时间顺序配音,而库里的返回顺序没有这个保证。
    created = sorted(
        (clip for track in (sequence.tracks or []) for clip in (track.clips or []) if clip.id not in before),
        key=lambda clip: clip.timeline_start,
    )
    return {
        "track_id": track_id,
        "clip_ids": [clip.id for clip in created],
        "count": len(created),
        "sequence_id": sequence.id,
    }


@register("dub_subtitles")
def dub_subtitles(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """给这些字幕条配音,落到一条专门的配音轨。

    和「语音合成」的分工:那个念一段文本、交出一份音频素材,由谁摆到哪一秒是下游的事;这个念
    的是**已经在时间线上、各自带着时间码**的一批字幕,所以它自己知道每一条该落在第几秒,也
    因此才谈得上「把配音压进原段落的长度」—— match_duration 改的是片段的 speed,渲染时由
    atempo 变速(见 media/render_executor),无损、可撤销、事后还能在检查器里手动微调。
    """
    from app.core.i18n import get_current_locale, t
    from app.domain.voices.original_audio import DEFAULT_ORIGINAL_AUDIO
    from app.domain.voices.subtitle_dub import DubError, start_subtitle_dub

    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    clip_ids = id_list(config.get("clip_ids"))
    if not clip_ids:
        # **空进空出。**「该不该为空」是上游说了算的:「生成字幕」默认 0 条就报错,选了
        # allow_empty(整片可能没有口播)才交出 0 条。此前这里再报一次「没有要配音的字幕条」,
        # 于是上游明说可以为空的那条流程,在下一步照样失败。什么都没配,原声就原样留着。
        return {
            "track_id": "",
            "done": 0,
            "failed": 0,
            "original_audio": "keep",
            "original_audio_note": t("dubOriginalAudio_keep", get_current_locale()),
        }

    synthesis = _speech_params(db, scope, config)
    try:
        job = start_subtitle_dub(
            db,
            sequence_id=sequence.id,
            clip_ids=clip_ids,
            match_duration=_yes_no(config, "match_duration", default=True),
            line=str(config.get("line") or "all"),
            created_by=current_actor(db),
            synthesis=synthesis,
            original_audio=str(config.get("original_audio") or DEFAULT_ORIGINAL_AUDIO).strip().lower(),
        )
    except DubError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    final = wait_for_job(job.id, release=db)
    result = final.result or {}
    #: **实际**对原声做了什么(配音任务收尾时处理,见 voices/original_audio)。历史任务可能留有
    #: mute_fallback；新任务对用户明确选择的 separate 不再静默降级。
    applied = str(result.get("original_audio") or "keep")
    return {
        "track_id": str(result.get("track_id") or ""),
        "done": int(result.get("done") or 0),
        "failed": int(result.get("failed") or 0),
        "original_audio": applied,
        "original_audio_note": t(f"dubOriginalAudio_{applied}", get_current_locale()),
    }


@register("separate_audio")
def separate_audio_node(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一份素材拆成人声 + 背景音两份新素材。

    **节点不认识任何引擎** —— 它只跟 domain.separation 说话,由注册表决定这次用哪个
    Adapter(ADR-0016)。所以加一个引擎不用改这里。

    **排成子任务再等它**,和转写、导出同一条路:此前在节点线程里直接跑模型,绕开了界面那条
    路占的 RENDER_SLOTS(循环里并行几个就一起把模型拉进内存),等待期间也一直攥着引擎的
    连接预算(见 wait_for_job)。
    """
    from app.ai.providers.contracts.separation import SeparationError
    from app.domain.separation import start_separation_job

    #: **收进工作区**,不是直接 db.get —— asset_id 常常来自上游节点,少了这一条,
    #: A 工作区的工作流能拆 B 工作区的素材,而产出的两份 stem 是要返回到工作流输出里的。
    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    try:
        child = start_separation_job(
            db, asset=asset, created_by=current_actor(db), engine=str(config.get("engine") or "")
        )
    except SeparationError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    result = wait_for_job(child.id, release=db).result or {}
    return {
        "vocals_asset_id": str(result.get("vocals_asset_id") or ""),
        "background_asset_id": str(result.get("background_asset_id") or ""),
        "engine": str(result.get("engine") or ""),
    }


@register("denoise_audio")
def denoise_audio_node(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """降噪,产出一份新素材。节点不认识任何引擎,只跟 domain.denoise 说话(ADR-0017)。

    排成子任务再等它,理由同分离节点。
    """
    from app.ai.providers.contracts.denoise import DenoiseError
    from app.domain.denoise import start_denoise_job

    # 收进工作区(同分离节点):asset_id 常常来自上游,不能让一个工作区的流程动另一个工作区的素材。
    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    try:
        child = start_denoise_job(
            db,
            asset=asset,
            created_by=current_actor(db),
            engine=str(config.get("engine") or ""),
            strength=str(config.get("strength") or ""),
        )
    except DenoiseError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    result = wait_for_job(child.id, release=db).result or {}
    return {"asset_id": str(result.get("asset_id") or ""), "engine": str(result.get("engine") or "")}


@register("asset")
def asset_node(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """指向一份素材,把它的 id 交给下游。

    **它不做任何事**,存在的意义是让「这条流程从这份素材开始」在画布上有一个说法 ——
    否则下游节点的 asset_id 只能手填一个 32 位十六进制,而那个 id 从哪来、指的是哪个文件,
    图上完全看不出来。

    拖一个文件到画布上就会得到它(文件先进素材库,再落成这个节点)。
    """
    asset_id = str(config.get("asset_id", "")).strip()
    if not asset_id:
        raise WorkflowDomainError("wfErr_assetNodeEmpty")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_assetNotInWorkspace")
    media_info = asset.media_info or {}

    def number(name: str) -> float | None:
        """素材自己的那个数;**不知道就是 None**。

        此前缺了就交 1920×1080、30fps、0 秒 —— 音频本来就没有画面尺寸,探测失败的视频什么都
        没有,而下游拿着编出来的数建项目、放时间线(0 秒的结尾点直接把片段放没了)。缺省是
        下游各自的事:建项目有它的画布缺省,放上时间线会去读素材真实的时长。
        """
        value = media_info.get(name)
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    width, height = number("width"), number("height")
    return {
        "asset_id": asset.id,
        "name": asset.name,
        "kind": asset.kind,
        "duration": number("duration"),
        "width": int(width) if width is not None else None,
        "height": int(height) if height is not None else None,
        "fps": number("fps"),
    }
