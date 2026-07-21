from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import Sequence, ToolConfirmation, now
from app.domain.sequences import operations as seq_ops

"""
Confirmation kernel (plan §16.2/§17.2): mutating external-agent tools never
execute directly. They create a pending confirmation; the user approves it in
the UI, and only then does the mapped action run. Timeline edits go through
SequenceOperations, so every approved edit stays undoable.
"""


class ConfirmationError(ValueError):
    pass


# Tool registry with permission levels (plan §17.4).
TOOL_DEFS: dict[str, dict[str, str]] = {
    "edit_timeline": {"permission": "edit", "cost": "none"},
    "render_sequence": {"permission": "render-cost", "cost": "render"},
    "generate_image": {"permission": "ai-cost", "cost": "ai"},
    "generate_video": {"permission": "ai-cost", "cost": "ai"},
    "generate_audio": {"permission": "ai-cost", "cost": "ai"},
    "generate_podcast": {"permission": "ai-cost", "cost": "ai"},
    # 工作流:建/改是编辑权限;运行可能触发渲染与 AI 消耗,按最高档要求确认。
    "create_workflow": {"permission": "edit", "cost": "none"},
    "update_workflow": {"permission": "edit", "cost": "none"},
    "edit_workflow": {"permission": "edit", "cost": "none"},
    "run_workflow": {"permission": "ai-cost", "cost": "ai"},
}

EDIT_OP_KINDS = (
    "insert_clip",
    "move_clip",
    "trim_clip",
    "delete_clip",
    "cut_clip_range",
    "add_track",
    "remove_track",
    "set_clip_effects",
    "set_clip_transform",
)


def request_confirmation(
    db: Session,
    *,
    workspace_id: str,
    tool: str,
    payload: dict[str, Any],
    requested_by: str = "external-agent",
) -> ToolConfirmation:
    definition = TOOL_DEFS.get(tool)
    if definition is None:
        raise ConfirmationError(f"Unknown mutating tool: {tool}")
    _validate_payload(db, tool, workspace_id, payload)
    confirmation = ToolConfirmation(
        workspace_id=workspace_id,
        tool=tool,
        permission=definition["permission"],
        summary=_summarize(tool, payload),
        payload=payload,
        requested_by=requested_by,
    )
    db.add(confirmation)
    db.commit()
    db.refresh(confirmation)
    return confirmation


def reject_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _claim(db, confirmation, "rejected")
    confirmation.resolved_at = now()
    db.commit()
    return confirmation


def approve_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _claim(db, confirmation, "approved")
    try:
        result = _execute(db, confirmation)
        confirmation.status = "executed"
        confirmation.result = result
    except Exception as exc:
        confirmation.status = "failed"
        confirmation.error = str(exc)[:500]
    confirmation.resolved_at = now()
    db.commit()
    db.refresh(confirmation)
    return confirmation


def _claim(db: Session, confirmation: ToolConfirmation, to_status: str) -> None:
    """Take exclusive ownership of a pending confirmation, or refuse.

    Reading `confirmation.status` off the in-memory object and then assigning it is a
    check-then-act: two requests that both load the pending row both pass the check and both
    run the executor. That is a second track added, a second render queued, a second image
    billed. One conditional UPDATE lets the database pick a winner instead — the loser changes
    no rows and is told the confirmation is already settled.
    """
    result = db.execute(
        update(ToolConfirmation)
        .where(ToolConfirmation.id == confirmation.id, ToolConfirmation.status == "pending")
        .values(status=to_status)
    )
    db.commit()
    db.refresh(confirmation)
    if result.rowcount != 1:
        raise ConfirmationError(f"Confirmation is already {confirmation.status}")


def _validate_payload(db: Session, tool: str, workspace_id: str, payload: dict[str, Any]) -> None:
    if tool in ("edit_timeline", "render_sequence"):
        sequence = db.get(Sequence, str(payload.get("sequence_id", "")))
        if sequence is None or sequence.workspace_id != workspace_id:
            raise ConfirmationError("Sequence not found in this workspace")
    if tool == "edit_timeline":
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ConfirmationError("edit_timeline requires a non-empty operations list")
        for operation in operations:
            kind = operation.get("kind") if isinstance(operation, dict) else None
            if kind not in EDIT_OP_KINDS:
                raise ConfirmationError(f"Unsupported timeline operation: {kind}")
    if tool in ("generate_image", "generate_video", "generate_audio"):
        if not str(payload.get("prompt") or payload.get("text") or "").strip():
            raise ConfirmationError("Generation requires a prompt")
    if tool == "generate_podcast":
        mode = str(payload.get("mode") or "summarize")
        if mode not in {"summarize", "read", "research"}:
            raise ConfirmationError("Unsupported podcast mode")
        if mode == "research":
            required = payload.get("topic")
        else:
            required = payload.get("text") or payload.get("prompt")
        if not str(required or "").strip():
            raise ConfirmationError("Podcast generation requires text or topic")
    if tool == "create_workflow":
        from app.domain.workflows import validate_graph

        if not str(payload.get("name", "")).strip():
            raise ConfirmationError("create_workflow requires a name")
        if payload.get("graph") is not None:
            errors = validate_graph(payload["graph"], require_config=False, allow_missing_start=True)
            if errors:
                raise ConfirmationError("；".join(errors))
    if tool in ("update_workflow", "edit_workflow", "run_workflow"):
        from app.db.models import Workflow
        from app.domain.workflows import validate_graph

        workflow = db.get(Workflow, str(payload.get("workflow_id", "")))
        if workflow is None or workflow.workspace_id != workspace_id:
            raise ConfirmationError("Workflow not found in this workspace")
        if tool == "update_workflow" and payload.get("graph") is not None:
            errors = validate_graph(payload["graph"], require_config=False, allow_missing_start=True)
            if errors:
                raise ConfirmationError("；".join(errors))
        if tool == "edit_workflow":
            from app.domain.workflows import WorkflowDomainError
            from app.domain.workflows.graph_ops import GRAPH_OP_KINDS, apply_graph_ops

            operations = payload.get("operations")
            if not isinstance(operations, list) or not operations:
                raise ConfirmationError("edit_workflow requires a non-empty operations list")
            for operation in operations:
                kind = operation.get("kind") if isinstance(operation, dict) else None
                if kind not in GRAPH_OP_KINDS:
                    raise ConfirmationError(f"Unsupported workflow op: {kind}")
            # Dry-run the ops onto the current graph so malformed edits fail fast (before approval).
            try:
                preview = apply_graph_ops(workflow.graph or {}, operations)
            except WorkflowDomainError as exc:
                raise ConfirmationError(str(exc)) from exc
            errors = validate_graph(preview, require_config=False, allow_missing_start=True)
            if errors:
                raise ConfirmationError("；".join(errors))


def _summarize(tool: str, payload: dict[str, Any]) -> str:
    if tool == "edit_timeline":
        kinds = [operation.get("kind", "?") for operation in payload.get("operations", [])]
        return f"{len(kinds)} 个时间线操作: {', '.join(kinds[:6])}{'…' if len(kinds) > 6 else ''}"
    if tool == "render_sequence":
        return "导出时间线为 mp4"
    if tool == "create_workflow":
        nodes = len((payload.get("graph") or {}).get("nodes", []) or [])
        return f"创建工作流「{payload.get('name', '')}」({nodes or 1} 个节点)"
    if tool == "update_workflow":
        nodes = len((payload.get("graph") or {}).get("nodes", []) or [])
        return f"修改工作流({nodes} 个节点)" if nodes else "修改工作流"
    if tool == "edit_workflow":
        ops = [op for op in payload.get("operations", []) if isinstance(op, dict)]
        kinds = [op.get("kind", "?") for op in ops]
        # A `code` node runs arbitrary local Python when the workflow is later run, so say so
        # here rather than leaving it to be noticed in the payload.
        adds_code = any(
            op.get("kind") == "add_node" and str(op.get("node_type") or op.get("type")) == "code" for op in ops
        )
        head = f"{len(kinds)} 个工作流编辑: {', '.join(kinds[:6])}{'…' if len(kinds) > 6 else ''}"
        return head + ("  ⚠️ 含代码节点(运行时执行本地 Python)" if adds_code else "")
    if tool == "run_workflow":
        name = str(payload.get("name") or payload.get("workflow_id") or "")
        return f"运行工作流{f'「{name}」' if name else ''}(可能产生 AI/渲染消耗)"
    prompt = str(payload.get("prompt") or payload.get("text") or payload.get("topic") or "")[:80]
    if tool == "generate_image":
        return f"生成图片: {prompt}"
    if tool == "generate_video":
        return f"生成视频: {prompt}"
    if tool == "generate_audio":
        return f"生成音频: {prompt}"
    if tool == "generate_podcast":
        return f"生成播客: {prompt}"
    return f"{tool}: {prompt}"


def _execute(db: Session, confirmation: ToolConfirmation) -> dict[str, Any]:
    payload = confirmation.payload
    if confirmation.tool == "edit_timeline":
        return _execute_edit_timeline(db, payload)
    if confirmation.tool == "render_sequence":
        from app.domain.render import start_export

        job = start_export(db, str(payload["sequence_id"]))
        return {"job_id": job.id}
    if confirmation.tool in ("generate_image", "generate_video"):
        from app.domain.generation import create_generation_job, ensure_builtin_generation_models
        from app.domain.generation.runner import start_generation_thread
        from app.domain.provider_defaults import resolve_default

        ensure_builtin_generation_models(db)
        kind = "image" if confirmation.tool == "generate_image" else "video"
        provider = str(payload.get("provider", "")).strip()
        model = str(payload.get("model", "")).strip()
        if not provider or not model:
            default_profile, default_model = resolve_default(db, kind)
            if default_profile is not None and default_model:
                provider, model = default_profile.vendor, default_model
        if not provider or not model:
            raise RuntimeError("没有配置可用于生成的真实供应商和模型")
        generation, job = create_generation_job(
            db,
            workspace_id=confirmation.workspace_id,
            session_id=None,
            project_id=payload.get("project_id"),
            provider=provider,
            model=model,
            kind=kind,
            prompt=str(payload["prompt"]),
            negative_prompt=str(payload.get("negative_prompt", "")),
            parameters=dict(payload.get("parameters") or {}),
            source_asset_ids=[],
        )
        start_generation_thread(generation.id)
        return {"job_id": job.id, "generation_id": generation.id}
    if confirmation.tool == "generate_audio":
        from app.audio.voices import start_synthesis
        from app.domain.provider_defaults import resolve_default

        profile_id = str(payload.get("provider_profile_id") or "").strip()
        engine = str(payload.get("engine") or payload.get("provider") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not engine:
            default_profile, default_model = resolve_default(db, "tts")
            if default_profile is not None:
                profile_id = default_profile.id
                engine = default_profile.vendor
                model = model or default_model
        if not engine:
            raise RuntimeError("没有配置可用于语音生成的真实供应商")
        job = start_synthesis(
            db,
            text=str(payload.get("text") or payload.get("prompt") or ""),
            project_id=payload.get("project_id"),
            workspace_id=confirmation.workspace_id,
            engine=engine,
            engine_voice=str(payload.get("voice") or payload.get("engine_voice") or ""),
            engine_voice_resource=str(payload.get("voice_resource") or payload.get("engine_voice_resource") or ""),
            speed=float(payload.get("speed") or 1.0),
            provider_profile_id=profile_id or None,
            engine_model=model,
        )
        return {"job_id": job.id}
    if confirmation.tool == "generate_podcast":
        from app.audio.voices import start_podcast
        from app.domain.provider_defaults import resolve_default

        profile_id = str(payload.get("provider_profile_id") or "").strip()
        if not profile_id:
            default_profile, _default_model = resolve_default(db, "podcast")
            if default_profile is not None:
                profile_id = default_profile.id
        job = start_podcast(
            db,
            workspace_id=confirmation.workspace_id,
            project_id=payload.get("project_id"),
            text=str(payload.get("text") or payload.get("prompt") or ""),
            topic=str(payload.get("topic") or ""),
            mode=str(payload.get("mode") or "summarize"),
            speakers=list(payload.get("speakers") or []),
            speed=float(payload.get("speed") or 1.0),
            provider_profile_id=profile_id or None,
        )
        return {"job_id": job.id}
    if confirmation.tool == "create_workflow":
        from app.domain.workflows import create_workflow

        workflow = create_workflow(
            db,
            workspace_id=confirmation.workspace_id,
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            graph=payload.get("graph"),
        )
        return {"workflow_id": workflow.id}
    if confirmation.tool == "update_workflow":
        from app.db.models import Workflow
        from app.domain.workflows import update_workflow

        workflow = db.get(Workflow, str(payload["workflow_id"]))
        assert workflow is not None  # validated at request time
        update_workflow(
            db,
            workflow,
            {key: payload[key] for key in ("name", "description", "graph") if key in payload},
        )
        return {"workflow_id": workflow.id}
    if confirmation.tool == "edit_workflow":
        from app.db.models import Workflow
        from app.domain.workflows import update_workflow
        from app.domain.workflows.graph_ops import apply_graph_ops

        workflow = db.get(Workflow, str(payload["workflow_id"]))
        assert workflow is not None
        # Re-apply onto the CURRENT graph at approval time (not the request-time snapshot).
        new_graph = apply_graph_ops(workflow.graph or {}, payload["operations"])
        update_workflow(db, workflow, {"graph": new_graph})
        return {"workflow_id": workflow.id, "nodes": len(new_graph.get("nodes", []))}
    if confirmation.tool == "run_workflow":
        from app.db.models import Workflow
        from app.domain.workflows.engine import start_workflow_job

        workflow = db.get(Workflow, str(payload["workflow_id"]))
        assert workflow is not None
        job = start_workflow_job(db, workflow, params=dict(payload.get("params") or {}))
        return {"job_id": job.id}
    raise ConfirmationError(f"No executor for tool {confirmation.tool}")


def _execute_edit_timeline(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    sequence_id = str(payload["sequence_id"])
    applied = 0
    for operation in payload["operations"]:
        kind = operation["kind"]
        args = {key: value for key, value in operation.items() if key != "kind"}
        if kind == "insert_clip":
            seq_ops.insert_clip(db, sequence_id, seq_ops.InsertClip(**args))
        elif kind == "move_clip":
            seq_ops.move_clip(db, sequence_id, seq_ops.MoveClip(**args))
        elif kind == "trim_clip":
            seq_ops.trim_clip(db, sequence_id, seq_ops.TrimClip(**args))
        elif kind == "delete_clip":
            seq_ops.delete_clip(db, sequence_id, seq_ops.DeleteClip(**args))
        elif kind == "cut_clip_range":
            seq_ops.cut_clip_range(db, sequence_id, seq_ops.CutClipRange(**args))
        elif kind == "add_track":
            # The op's own name occupies "kind", so the track kind travels as track_kind.
            seq_ops.add_track(db, sequence_id, seq_ops.AddTrack(kind=str(args.get("track_kind", "video"))))
        elif kind == "remove_track":
            seq_ops.remove_track(db, sequence_id, seq_ops.RemoveTrack(**args))
        elif kind == "set_clip_effects":
            seq_ops.set_clip_effects(db, sequence_id, seq_ops.SetClipEffects(**args))
        elif kind == "set_clip_transform":
            seq_ops.set_clip_transform(db, sequence_id, seq_ops.SetClipTransform(**args))
        applied += 1
    sequence = db.get(Sequence, sequence_id)
    return {"applied_operations": applied, "sequence_revision": sequence.revision if sequence else None}
