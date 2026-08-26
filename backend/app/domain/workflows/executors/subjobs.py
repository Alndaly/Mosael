"""子任务型节点:复用既有 job 执行器(转写/导出/生成/配音/发布),轮询其终态。

领域模块在这里以「适配器调用」出现:每个执行器只调对应领域的启动函数 + wait_for_job,
不掺杂领域内部逻辑——这是工作流引擎与各领域之间的接缝。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Sequence, Transcript, Workflow
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
    return {"sequence_id": sequence.id, "revision": sequence.revision, "tracks": tracks, "duration": duration}
