"""出图、出片、出音乐/音效、念字、做播客 —— 花的是供应商的钱,所以都要先开卡。

它们**不自己实现生成**:都汇进 create_generation_job / voices 那两条漏斗。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _asked_for(payload: dict[str, Any]) -> str:
    """卡上写出**要生成什么**。提示词/正文/选题三个键里哪个有就用哪个(四个工具各用一个)。"""
    return str(payload.get("prompt") or payload.get("text") or payload.get("topic") or "")[:80]


#: 走生成漏斗(create_generation_job)的那三个工具各自生成哪一种。此前 image / video 两个执行体
#: 各抄一份、靠 `"image" if tool == "generate_image" else "video"` 判 —— 多一种就会被判成视频。
_GENERATION_KIND_BY_TOOL = {"generate_image": "image", "generate_video": "video", "generate_sound": "audio"}


def _execute_generation(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import parse_source_assets
    from app.domain.generation.runner import start_generation_thread
    kind = _GENERATION_KIND_BY_TOOL[confirmation.tool]
    generation, job = create_generation_job(
        db,
        workspace_id=confirmation.workspace_id,
        session_id=None,
        project_id=payload.get("project_id"),
        created_by=actor,
        provider=str(payload.get("provider", "")),
        provider_profile_id=str(payload.get("provider_profile_id", "")).strip() or None,
        model=str(payload.get("model", "")),
        kind=kind,
        prompt=str(payload.get("prompt") or ""),
        negative_prompt=str(payload.get("negative_prompt", "")),
        parameters=dict(payload.get("parameters") or {}),
        source_assets=parse_source_assets(payload.get("source_assets"), kind=kind),
    )
    start_generation_thread(generation.id)
    return {"job_id": job.id, "generation_id": generation.id}


def _validate_generate_image(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    if not str(payload.get("prompt") or payload.get("text") or "").strip():
        raise ConfirmationError("Generation requires a prompt")

def _summarize_generate_image(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_generateImage", {"asked": _asked_for(payload)}

def _validate_generate_video(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    if not str(payload.get("prompt") or payload.get("text") or "").strip():
        raise ConfirmationError("Generation requires a prompt")

def _summarize_generate_video(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_generateVideo", {"asked": _asked_for(payload)}

def _validate_generate_sound(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    # 文字规矩按模型走(只给歌词、给视频配声什么字都不给都合法),由生成漏斗按描述符判;
    # 这里只拦「什么都没给」—— 连一段要配声的视频都没有。
    parameters = payload.get("parameters") or {}
    if not (
        str(payload.get("prompt") or "").strip()
        or str(parameters.get("lyrics") or "").strip()
        or payload.get("source_assets")
    ):
        raise ConfirmationError("Generation requires a prompt, lyrics or a source asset")

def _summarize_generate_sound(db: Session, payload: dict[str, Any]) -> Summary:
    asked = _asked_for(payload) or str((payload.get("parameters") or {}).get("lyrics") or "")[:80]
    return "confirm_generateSound", {"asked": asked}

def _validate_generate_audio(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    if not str(payload.get("prompt") or payload.get("text") or "").strip():
        raise ConfirmationError("Generation requires a prompt")

def _summarize_generate_audio(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_generateAudio", {"asked": _asked_for(payload)}

def _execute_generate_audio(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.voices.voices import start_synthesis
    from app.domain import provider_models

    profile_id = str(payload.get("provider_profile_id") or "").strip()
    engine = str(payload.get("engine") or payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not engine:
        default = provider_models.resolve_default(db, "tts", actor)
        if default is not None:
            profile_id = default.provider_profile_id
            engine = default.profile.vendor
            model = model or default.model_id
    if not engine:
        raise ConfirmationError("confirmErr_noTtsProvider")
    job = start_synthesis(
        db,
        text=str(payload.get("text") or payload.get("prompt") or ""),
        project_id=payload.get("project_id"),
        created_by=actor,
        workspace_id=confirmation.workspace_id,
        engine=engine,
        engine_voice=str(payload.get("voice") or payload.get("engine_voice") or ""),
        engine_voice_resource=str(payload.get("voice_resource") or payload.get("engine_voice_resource") or ""),
        speed=float(payload.get("speed") or 1.0),
        provider_profile_id=profile_id or None,
        engine_model=model,
    )
    return {"job_id": job.id}

def _validate_generate_podcast(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    mode = str(payload.get("mode") or "summarize")
    if mode not in {"summarize", "read", "research"}:
        raise ConfirmationError("Unsupported podcast mode")
    if mode == "research":
        required = payload.get("topic")
    else:
        required = payload.get("text") or payload.get("prompt")
    if not str(required or "").strip():
        raise ConfirmationError("Podcast generation requires text or topic")

def _summarize_generate_podcast(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_generatePodcast", {"asked": _asked_for(payload)}

def _execute_generate_podcast(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.voices.voices import start_podcast
    from app.domain import provider_models

    profile_id = str(payload.get("provider_profile_id") or "").strip()
    if not profile_id:
        default = provider_models.resolve_default(db, "podcast", actor)
        if default is not None:
            profile_id = default.provider_profile_id
    job = start_podcast(
        db,
        workspace_id=confirmation.workspace_id,
        project_id=payload.get("project_id"),
        created_by=actor,
        text=str(payload.get("text") or payload.get("prompt") or ""),
        topic=str(payload.get("topic") or ""),
        mode=str(payload.get("mode") or "summarize"),
        speakers=list(payload.get("speakers") or []),
        speed=float(payload.get("speed") or 1.0),
        provider_profile_id=profile_id or None,
    )
    return {"job_id": job.id}

confirmable_tool(ConfirmableTool(
    name="generate_image",
    permission="ai-cost",
    cost="ai",
    summarize=_summarize_generate_image,
    execute=_execute_generation,
    validate=_validate_generate_image,
))


confirmable_tool(ConfirmableTool(
    name="generate_video",
    permission="ai-cost",
    cost="ai",
    summarize=_summarize_generate_video,
    execute=_execute_generation,
    validate=_validate_generate_video,
))


confirmable_tool(ConfirmableTool(
    name="generate_sound",
    permission="ai-cost",
    cost="ai",
    summarize=_summarize_generate_sound,
    execute=_execute_generation,
    validate=_validate_generate_sound,
))


confirmable_tool(ConfirmableTool(
    name="generate_audio",
    permission="ai-cost",
    cost="ai",
    summarize=_summarize_generate_audio,
    execute=_execute_generate_audio,
    validate=_validate_generate_audio,
))


confirmable_tool(ConfirmableTool(
    name="generate_podcast",
    permission="ai-cost",
    cost="ai",
    summarize=_summarize_generate_podcast,
    execute=_execute_generate_podcast,
    validate=_validate_generate_podcast,
))


