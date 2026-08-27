"""子任务型节点:复用既有 job 执行器(转写/导出/生成/配音/发布),轮询其终态。

领域模块在这里以「适配器调用」出现:每个执行器只调对应领域的启动函数 + wait_for_job,
不掺杂领域内部逻辑——这是工作流引擎与各领域之间的接缝。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Sequence, Transcript, Workflow
from app.domain.sequences.errors import SequenceDomainError
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register
from app.domain.jobs import current_actor
from app.domain.workflows.executors.common import wait_for_job


@register("transcribe_asset")
def transcribe_asset(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.voices.service import start_transcription

    asset_id = str(config.get("asset_id", ""))
    child = start_transcription(db, asset_id, created_by=current_actor(db))
    wait_for_job(child.id)
    transcript = db.scalars(
        select(Transcript).where(Transcript.asset_id == asset_id).order_by(Transcript.id.desc())
    ).first()
    if transcript is None:
        raise WorkflowDomainError("转写完成但没有找到文稿")
    db.refresh(transcript)
    text = "\n".join(segment.text for segment in transcript.segments)
    return {"text": text}


@register("export_sequence")
def export_sequence(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.render import start_export

    child = start_export(db, str(config.get("sequence_id", "")), created_by=current_actor(db))
    final = wait_for_job(child.id)
    asset_id = str((final.result or {}).get("asset_id", ""))
    return {"asset_id": asset_id}


@register("ai_generate")
def ai_generate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import parse_source_assets
    from app.domain.generation.runner import start_generation_thread

    provider = str(config.get("provider", "")).strip()
    model = str(config.get("model", "")).strip()
    kind = str(config.get("kind", "image")).strip() or "image"
    if not provider or not model:
        raise WorkflowDomainError("AI 生成节点缺少真实供应商或模型")
    generation, child = create_generation_job(
        db,
        workspace_id=workflow.workspace_id,
        session_id=None,
        project_id=None,
        created_by=current_actor(db),
        provider=provider,
        model=model,
        kind=kind,
        prompt=str(config.get("prompt", "")),
        negative_prompt=str(config.get("negative_prompt", "")),
        parameters=dict(config.get("parameters") or {}),
        source_assets=parse_source_assets(config.get("source_assets"), kind=kind),
    )
    db.commit()
    start_generation_thread(generation.id)
    wait_for_job(child.id)
    db.refresh(generation)
    return {"asset_id": generation.result_asset_id or "", "generation_id": generation.id}


@register("synthesize_speech")
def synthesize_speech(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.voices.voices import start_synthesis

    child = start_synthesis(
        db,
        voice_id=str(config.get("voice_id", "")),
        text=str(config.get("text", "")),
        project_id=None,
        created_by=current_actor(db),
    )
    final = wait_for_job(child.id)
    return {"asset_id": str((final.result or {}).get("asset_id", ""))}


@register("publish")
def publish(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import Asset, PublishAccount
    from app.domain.publish import start_publish

    account = db.get(PublishAccount, str(config.get("account_id", "")))
    if account is None or account.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("发布账号不存在")
    asset = db.get(Asset, str(config.get("asset_id", "")))
    if asset is None or asset.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("发布素材不存在")
    task = start_publish(
        db,
        workspace_id=workflow.workspace_id,
        account=account,
        asset=asset,
        title=str(config.get("title", "")),
        description=str(config.get("description", "")),
        created_by=current_actor(db),
        tags=[],
    )
    final = wait_for_job(task.job_id or "")
    return {"result": final.result or {}}



@register("edit_timeline")
def edit_timeline(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """把一组操作应用到时间线上。

    智能体早就能做这件事(edit_timeline 工具),而工作流只能「导出序列」—— 于是「生成素材
    → 编排 → 导出」这条最常见的链路,中间那步在画布上做不了,必须切去对话里或者手动摆。

    操作的种类和智能体那边**是同一份**(domain/sequences/operations.EDIT_OP_KINDS)——
    不是抄一遍,是同一个清单。
    """
    from app.domain.sequences.operations import apply_edit_operations

    sequence_id = str(config.get("sequence_id", "")).strip()
    if not sequence_id:
        raise WorkflowDomainError("时间线节点缺少 sequence_id")
    operations = config.get("operations")
    if isinstance(operations, str):
        # 上游节点常常给一段 JSON 文本(比如 code 节点算出来的),接住它省得再加一个解析节点。
        try:
            operations = json.loads(operations)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError(f"operations 不是合法 JSON:{exc}") from exc
    if not isinstance(operations, list) or not operations:
        raise WorkflowDomainError("operations 要是一个非空数组")
    try:
        applied = apply_edit_operations(db, sequence_id, operations)
    except SequenceDomainError as exc:
        raise WorkflowDomainError(str(exc)) from exc
    db.commit()
    sequence = db.get(Sequence, sequence_id)
    return {"applied": applied, "sequence_id": sequence_id, "revision": sequence.revision if sequence else 0}


@register("inspect_sequence")
def inspect_sequence(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """看一眼时间线现在长什么样 —— 编排之前得先知道有哪些轨道、片段排到了第几秒。

    智能体有对应的工具;工作流此前只能盲改。
    """
    sequence_id = str(config.get("sequence_id", "")).strip()
    if not sequence_id:
        raise WorkflowDomainError("检视节点缺少 sequence_id")
    sequence = db.get(Sequence, sequence_id)
    if sequence is None or sequence.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("序列不在这个工作区里")
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
                }
                for clip in (track.clips or [])
            ],
        }
        for track in (sequence.tracks or [])
    ]
    duration = max(
        (clip["timeline_start"] + (clip["src_out"] - clip["src_in"]) for track in tracks for clip in track["clips"]),
        default=0.0,
    )
    # 顺手把第一条视频/音频轨的 id 摆出来 —— 下游「接素材」想指定轨道时,不用自己去
    # tracks 里翻。绝大多数时间线各只有一条。
    first = lambda kind: next((one["id"] for one in tracks if one["kind"] == kind), "")
    return {
        "sequence_id": sequence.id,
        "revision": sequence.revision,
        "tracks": tracks,
        "duration": duration,
        "video_track_id": first("video"),
        "audio_track_id": first("audio"),
    }


def _sequence_in(db: Session, workflow: Workflow, sequence_id: str) -> Sequence:
    """取这条序列,并确认它属于本工作流所在的工作区。

    sequence_id 常常来自上游节点,而上游可能拿到任何地方的 id —— 这一条挡的是
    「用 A 工作区的工作流去改 B 工作区的时间线」。
    """
    if not sequence_id:
        raise WorkflowDomainError("缺少 sequence_id")
    sequence = db.get(Sequence, sequence_id)
    if sequence is None or sequence.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("序列不在这个工作区里")
    return sequence


#: 图片进时间线时的默认定格时长。图片没有 duration,不给个默认值的话 src_out 是 0,
#: 整段会被判为空而拒掉 —— 而"把一张图接到时间线上"是很常见的用法。
STILL_SECONDS = 5.0

#: 素材种类 → 该进哪种轨道。没列的(图片)按视频走 —— 图片在时间线上就是一段定格视频。
_TRACK_FOR_ASSET = {"audio": "audio"}


@register("timeline_append")
def timeline_append(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """把一份素材接到轨道末尾。

    **这是编排里占九成的动作**,所以它是一个有真表单的节点,而不是让人手写一条
    `{"kind": "insert_clip", "timeline_start": …}` —— 那个 timeline_start 还得自己算,
    而"接到末尾"本来就该由机器算。
    """
    from app.domain.sequences.operations import InsertClip, insert_clip

    sequence = _sequence_in(db, workflow, str(config.get("sequence_id", "")).strip())
    asset_id = str(config.get("asset_id", "")).strip()
    if not asset_id:
        raise WorkflowDomainError("缺少 asset_id")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("素材不在这个工作区里")

    tracks = list(sequence.tracks or [])
    track_id = str(config.get("track_id", "")).strip()
    if track_id:
        track = next((one for one in tracks if one.id == track_id), None)
        if track is None:
            raise WorkflowDomainError("这条时间线上没有那条轨道")
    else:
        # 留空就挑第一条同类轨道 —— 绝大多数时间线只有一条视频轨和一条音频轨,
        # 逼用户先跑一个「看一眼时间线」把 id 取出来是纯仪式。
        want = _TRACK_FOR_ASSET.get(asset.kind, "video")
        track = next((one for one in tracks if one.kind == want), None)
        if track is None:
            raise WorkflowDomainError(f"这条时间线上没有 {want} 轨道,先加一条")

    # 截取范围:留空就是整段素材。
    src_in = float(config.get("start") or 0.0)
    src_out = config.get("end")
    # 时长在 media_info 里,不是独立列(见 domain/assets/importer 的探测)。
    # 图片没有 duration —— 给它一个默认的定格时长,否则 src_out 会是 0、整段被判为空。
    probed = (asset.media_info or {}).get("duration")
    fallback = float(probed) if probed else (STILL_SECONDS if asset.kind == "image" else 0.0)
    src_out = float(src_out) if src_out not in (None, "") else fallback
    if src_out <= src_in:
        raise WorkflowDomainError("截取的结束时间要大于开始时间")

    # 接到末尾:这条轨道上最后一个片段的终点。空轨道就是 0。
    timeline_start = max(
        (clip.timeline_start + (clip.src_out - clip.src_in) for clip in (track.clips or [])),
        default=0.0,
    )
    insert_clip(
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
    db.commit()
    db.refresh(sequence)
    clip = max((c for t in (sequence.tracks or []) for c in (t.clips or [])), key=lambda c: c.created_at, default=None)
    return {
        "clip_id": clip.id if clip else "",
        "timeline_start": timeline_start,
        "timeline_end": timeline_start + (src_out - src_in),
        "sequence_id": sequence.id,
    }


@register("timeline_add_track")
def timeline_add_track(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.sequences.operations import AddTrack, add_track

    sequence = _sequence_in(db, workflow, str(config.get("sequence_id", "")).strip())
    kind = str(config.get("kind", "video")).strip() or "video"
    before = {one.id for one in (sequence.tracks or [])}
    add_track(db, sequence.id, AddTrack(kind=kind))
    db.commit()
    db.refresh(sequence)
    created = next((one.id for one in (sequence.tracks or []) if one.id not in before), "")
    return {"track_id": created, "sequence_id": sequence.id}


@register("timeline_clear")
def timeline_clear(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """删掉所有片段,轨道留着。

    留着轨道是有意的:重跑一条工作流时,下游的「接素材」还指望那几条轨道在。
    """
    from app.domain.sequences.operations import DeleteClip, delete_clip

    sequence = _sequence_in(db, workflow, str(config.get("sequence_id", "")).strip())
    clip_ids = [clip.id for track in (sequence.tracks or []) for clip in (track.clips or [])]
    for clip_id in clip_ids:
        delete_clip(db, sequence.id, DeleteClip(clip_id=clip_id))
    db.commit()
    return {"removed": len(clip_ids), "sequence_id": sequence.id}


@register("asset")
def asset_node(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """指向一份素材,把它的 id 交给下游。

    **它不做任何事**,存在的意义是让「这条流程从这份素材开始」在画布上有一个说法 ——
    否则下游节点的 asset_id 只能手填一个 32 位十六进制,而那个 id 从哪来、指的是哪个文件,
    图上完全看不出来。

    拖一个文件到画布上就会得到它(文件先进素材库,再落成这个节点)。
    """
    asset_id = str(config.get("asset_id", "")).strip()
    if not asset_id:
        raise WorkflowDomainError("素材节点没有选素材")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("素材不在这个工作区里")
    return {
        "asset_id": asset.id,
        "name": asset.name,
        "kind": asset.kind,
        "duration": float((asset.media_info or {}).get("duration") or 0.0),
    }
