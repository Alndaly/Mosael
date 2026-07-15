from __future__ import annotations

from typing import Any

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
    _require_pending(confirmation)
    confirmation.status = "rejected"
    confirmation.resolved_at = now()
    db.commit()
    return confirmation


def approve_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _require_pending(confirmation)
    confirmation.status = "approved"
    db.commit()
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


def _require_pending(confirmation: ToolConfirmation) -> None:
    if confirmation.status != "pending":
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
    if tool in ("generate_image", "generate_video"):
        if not str(payload.get("prompt", "")).strip():
            raise ConfirmationError("Generation requires a prompt")


def _summarize(tool: str, payload: dict[str, Any]) -> str:
    if tool == "edit_timeline":
        kinds = [operation.get("kind", "?") for operation in payload.get("operations", [])]
        return f"{len(kinds)} 个时间线操作: {', '.join(kinds[:6])}{'…' if len(kinds) > 6 else ''}"
    if tool == "render_sequence":
        return "导出时间线为 mp4"
    prompt = str(payload.get("prompt", ""))[:80]
    return f"生成{'图片' if tool == 'generate_image' else '视频'}: {prompt}"


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

        ensure_builtin_generation_models(db)
        kind = "image" if confirmation.tool == "generate_image" else "video"
        generation, job = create_generation_job(
            db,
            workspace_id=confirmation.workspace_id,
            project_id=payload.get("project_id"),
            provider=str(payload.get("provider", "mock")),
            model=str(payload.get("model", f"mock-{kind}")),
            kind=kind,
            prompt=str(payload["prompt"]),
            parameters=dict(payload.get("parameters") or {}),
            source_asset_ids=[],
        )
        start_generation_thread(generation.id)
        return {"job_id": job.id, "generation_id": generation.id}
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
        applied += 1
    sequence = db.get(Sequence, sequence_id)
    return {"applied_operations": applied, "sequence_revision": sequence.revision if sequence else None}
