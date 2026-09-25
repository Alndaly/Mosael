"""素材和时间线上的确认卡工具:改时间线、导出、字幕配音、分离、降噪、转 GIF。

这几件事的共同点是**要么改用户的片子、要么让这台机器忙很久**,所以都得先开卡。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.db.models import Sequence
from app.domain.sequences import operations as seq_ops

#: 时间线操作的种类由**序列域**说了算 —— 那是「能对时间线做什么」的清单,不是智能体这一个入口的清单。
EDIT_OP_KINDS = seq_ops.EDIT_OP_KINDS

#: 卡上说清原声会怎样 —— 静音和「只去掉人声」都会改变成片的样子,用户得在批准前知道。
#: 原声怎么处理 —— **值是文案 key,不是文案**:它会被拼进落库的那句话里,写死就等于把语言
#: 冻在写它那天(和 NODE_TYPES 的 label 同一条规矩)。
_ORIGINAL_AUDIO_SUMMARY = {
    "duck": "confirm_originalDuck",
    "mute": "confirm_originalMute",
    "keep": "confirm_originalKeep",
    "separate": "confirm_originalSeparate",
}



def _sequence_in(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    """这次要动的那条时间线,**收进这个工作区** —— 改时间线、导出、字幕配音都是"拿一个
    sequence_id 去动一条时间线",没有理由各判各的。"""
    sequence = db.get(Sequence, str(payload.get("sequence_id", "")))
    if sequence is None or sequence.workspace_id != workspace_id:
        raise ConfirmationError("Sequence not found in this workspace")



def _subtitle_cue_count(db: Session, payload: dict[str, Any]) -> int | None:
    """整条字幕轨到底有多少条 —— **用执行时的那一个函数去数**。

    卡上说的必须就是待会儿真要做的:另写一遍「怎么算整条轨」的话,两份实现迟早分叉,而分叉了
    没有任何地方会报错 —— 用户看到的条数和真正配的条数不一样,却只有账单知道。

    只在 clip_ids 留空(= 整条轨)时需要;点名了条目的话条数本来就在 payload 里。
    数不出来就返回 None,卡照旧退回不带条数的说法 —— 为了一个数字让确认卡开不出来是本末倒置。
    """
    if payload.get("clip_ids") or []:
        return None
    try:
        from app.domain.voices.subtitle_dub import subtitle_clip_ids

        return len(subtitle_clip_ids(db, str(payload.get("sequence_id") or ""), str(payload.get("track_id") or "")))
    except Exception:  # noqa: BLE001 — 数不出来不该挡住确认卡
        return None



def _validate_edit_timeline(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _sequence_in(db, workspace_id, payload)

    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ConfirmationError("edit_timeline requires a non-empty operations list")
    for operation in operations:
        kind = operation.get("kind") if isinstance(operation, dict) else None
        if kind not in EDIT_OP_KINDS:
            raise ConfirmationError(f"Unsupported timeline operation: {kind}")


def _summarize_edit_timeline(db: Session, payload: dict[str, Any]) -> Summary:
    kinds = [operation.get("kind", "?") for operation in payload.get("operations", [])]
    return "confirm_editTimeline", {
        "count": len(kinds),
        "kinds": ", ".join(kinds[:6]) + ("…" if len(kinds) > 6 else ""),
    }


def _execute_edit_timeline(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    sequence_id = str(payload["sequence_id"])
    applied = seq_ops.apply_edit_operations(db, sequence_id, payload["operations"])
    sequence = db.get(Sequence, sequence_id)
    return {"applied_operations": applied, "sequence_revision": sequence.revision if sequence else None}


def _validate_render_sequence(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _sequence_in(db, workspace_id, payload)


def _summarize_render_sequence(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_renderSequence", {}


def _execute_render_sequence(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.render import start_export

    job = start_export(db, str(payload["sequence_id"]))
    return {"job_id": job.id}


def _validate_dub_subtitles(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _sequence_in(db, workspace_id, payload)

    if str(payload.get("line") or "all") not in {"all", "first", "last"}:
        raise ConfirmationError("confirmErr_badLine")
    clip_ids = payload.get("clip_ids")
    if clip_ids is not None and not isinstance(clip_ids, list):
        raise ConfirmationError("confirmErr_clipIdsNotArray")
    from app.domain.voices.original_audio import DEFAULT_ORIGINAL_AUDIO, ORIGINAL_AUDIO_MODES

    if str(payload.get("original_audio") or DEFAULT_ORIGINAL_AUDIO) not in ORIGINAL_AUDIO_MODES:
        raise ConfirmationError("confirmErr_badOriginalAudio", modes=" / ".join(ORIGINAL_AUDIO_MODES))


def _summarize_dub_subtitles(db: Session, payload: dict[str, Any]) -> str:
    count = len(payload.get("clip_ids") or [])
    # **这里有两个不同的零。** `len(clip_ids) == 0` 的意思是「没点名 = 整条轨」,不是
    # 「零条字幕」—— 直接写成「0 条」会让人以为什么都不会发生,所以此前退回了「整条字幕轨」。
    # 但那一退把**量级**也丢了:这是一次花钱的动作(卡上挂着「AI 成本」),而整条轨可能是
    # 3 条也可能是 300 条。真去数一遍,零就是真的零,那时写出来反而是对的。
    subtitle_cues = _subtitle_cue_count(db, payload)
    if count:
        scope = fragment("confirm_dubScopeClips", count=count)
    elif subtitle_cues is None:
        scope = fragment("confirm_dubScopeTrack")
    else:
        scope = fragment("confirm_dubScopeTrackCounted", count=subtitle_cues)
    fit = fragment("confirm_dubFit") if payload.get("match_duration", True) else ""
    from app.domain.voices.original_audio import DEFAULT_ORIGINAL_AUDIO

    original = fragment(_ORIGINAL_AUDIO_SUMMARY.get(str(payload.get("original_audio") or DEFAULT_ORIGINAL_AUDIO), ""))
    return "confirm_dubSubtitles", {"scope": scope, "fit": fit, "original": original}


def _execute_dub_subtitles(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.voices.engine_catalog import CLONE_ENGINE, synthesis_params
    from app.domain.voices.original_audio import DEFAULT_ORIGINAL_AUDIO
    from app.domain.voices.subtitle_dub import start_subtitle_dub, subtitle_clip_ids

    sequence_id = str(payload.get("sequence_id") or "")
    clip_ids = [str(one) for one in (payload.get("clip_ids") or []) if str(one).strip()]
    if not clip_ids:
        clip_ids = subtitle_clip_ids(db, sequence_id, str(payload.get("track_id") or ""))
    engine = str(payload.get("engine") or "").strip() or CLONE_ENGINE
    job = start_subtitle_dub(
        db,
        sequence_id=sequence_id,
        clip_ids=clip_ids,
        match_duration=bool(payload.get("match_duration", True)),
        line=str(payload.get("line") or "all"),
        created_by=actor,
        synthesis=synthesis_params(
            db,
            engine=engine,
            voice=str(payload.get("voice_id" if engine == CLONE_ENGINE else "engine_voice") or ""),
            speed=float(payload.get("speed") or 1.0),
            user_id=actor,
            workspace_id=confirmation.workspace_id,
        ),
        original_audio=str(payload.get("original_audio") or DEFAULT_ORIGINAL_AUDIO),
    )
    return {"job_id": job.id}


def _validate_separate_audio(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.db.models import Asset

    asset = db.get(Asset, str(payload.get("asset_id") or ""))
    if asset is None or asset.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_assetNotInWorkspace")
    if asset.kind not in {"audio", "video"}:
        raise ConfirmationError("confirmErr_separateNeedsAudio")


def _summarize_separate_audio(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_separateAudio", {}


def _execute_separate_audio(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Asset
    from app.domain.separation import start_separation_job

    asset = db.get(Asset, str(payload["asset_id"]))
    if asset is None or asset.workspace_id != confirmation.workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    # **起任务,不在这里同步跑完** —— 批准确认卡的那个请求不该挂十几分钟
    # (和 convert_video_to_gif 同款:返回 job_id,智能体按它问进度)。
    job = start_separation_job(db, asset=asset, created_by=actor, engine=str(payload.get("engine") or ""))
    return {"job_id": job.id}


def _validate_denoise_audio(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.ai.providers.contracts.denoise import DenoiseError, checked_strength
    from app.db.models import Asset
    from app.core.i18n import t
    from app.domain.denoise import DENOISABLE_KINDS, ready_adapter

    asset = db.get(Asset, str(payload.get("asset_id") or ""))
    if asset is None or asset.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_assetNotInWorkspace")
    if asset.kind not in DENOISABLE_KINDS:
        raise ConfirmationError("confirmErr_denoiseNeedsAudio")
    # 引擎和档位在**开卡之前**就判:批准一张注定失败的卡,只是把同一句话推迟到点完之后。
    try:
        payload["strength"] = checked_strength(str(payload.get("strength") or ""))
        adapter = ready_adapter(str(payload.get("engine") or ""))
        # 卡上要说的话(用哪个、会不会去掉音乐)在这里就定下来 —— _summarize 不查注册表。
        payload["resolved_engine"] = adapter.engine_id
        payload["engine_name"] = t(adapter.label_key)
        payload["removes_music"] = adapter.removes_music
        payload["has_strengths"] = bool(adapter.strengths)
    except DenoiseError as exc:
        raise ConfirmationError(str(exc)) from exc


#: 强度档的文案 key。**值是 key 不是文案** —— 这张表本身也会被读到界面上。
_DENOISE_STRENGTH = {
    "light": "confirm_denoiseLight",
    "medium": "confirm_denoiseMedium",
    "strong": "confirm_denoiseStrong",
}


def _summarize_denoise_audio(db: Session, payload: dict[str, Any]) -> Summary:
    level_key = _DENOISE_STRENGTH.get(str(payload.get("strength")), "")
    strength = ""
    if payload.get("has_strengths", True) and level_key:
        strength = fragment("confirm_denoiseStrength", level=fragment(level_key))
    return "confirm_denoiseAudio", {
        "engine": payload.get("engine_name") or fragment("confirm_denoiseDefaultEngine"),
        "strength": strength,
        "music": fragment("confirm_denoiseRemovesMusic") if payload.get("removes_music") else "",
    }


def _execute_denoise_audio(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Asset
    from app.domain.denoise import start_denoise_job

    asset = db.get(Asset, str(payload["asset_id"]))
    if asset is None or asset.workspace_id != confirmation.workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    job = start_denoise_job(
        db,
        asset=asset,
        created_by=actor,
        engine=str(payload.get("engine") or ""),
        strength=str(payload.get("strength") or ""),
    )
    return {"job_id": job.id}


def _validate_convert_video_to_gif(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.db.models import Asset

    asset = db.get(Asset, str(payload.get("asset_id") or ""))
    if asset is None or asset.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_videoNotInWorkspace")
    if asset.kind != "video":
        raise ConfirmationError("confirmErr_gifNeedsVideo")
    try:
        fps = int(payload.get("fps") or 12)
        width = int(payload.get("width") or 720)
        start = float(payload.get("start") or 0)
        duration = payload.get("duration")
        duration = float(duration) if duration not in (None, "") else None
    except (TypeError, ValueError) as exc:
        raise ConfirmationError("confirmErr_gifBadParams") from exc
    if fps < 1 or fps > 30 or width < 64 or width > 1920 or start < 0 or (duration is not None and duration <= 0):
        raise ConfirmationError("confirmErr_gifParamsOutOfRange")


def _summarize_convert_video_to_gif(db: Session, payload: dict[str, Any]) -> Summary:
    duration = payload.get("duration")
    return "confirm_videoToGif", {
        "fps": payload.get("fps", 12),
        "width": payload.get("width", 720),
        "clip": fragment("confirm_gifClip", duration=duration) if duration not in (None, "") else "",
    }


def _execute_convert_video_to_gif(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Asset
    from app.domain.assets.video_gif import start_video_to_gif

    asset = db.get(Asset, str(payload["asset_id"]))
    if asset is None or asset.workspace_id != confirmation.workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    duration = payload.get("duration")
    job = start_video_to_gif(
        db,
        asset=asset,
        created_by=actor,
        fps=int(payload.get("fps") or 12),
        width=int(payload.get("width") or 720),
        start=float(payload.get("start") or 0),
        duration=float(duration) if duration not in (None, "") else None,
    )
    return {"job_id": job.id, "source_asset_id": asset.id}

confirmable_tool(ConfirmableTool(
    name="edit_timeline",
    permission="edit",
    cost="none",
    summarize=_summarize_edit_timeline,
    execute=_execute_edit_timeline,
    validate=_validate_edit_timeline,
))


confirmable_tool(ConfirmableTool(
    name="render_sequence",
    permission="render-cost",
    cost="render",
    summarize=_summarize_render_sequence,
    execute=_execute_render_sequence,
    validate=_validate_render_sequence,
))


confirmable_tool(ConfirmableTool(
    name="dub_subtitles",
    permission="ai-cost",
    cost="ai",
    summarize=_summarize_dub_subtitles,
    execute=_execute_dub_subtitles,
    validate=_validate_dub_subtitles,
))


confirmable_tool(ConfirmableTool(
    name="separate_audio",
    permission="render-cost",
    cost="render",
    summarize=_summarize_separate_audio,
    execute=_execute_separate_audio,
    validate=_validate_separate_audio,
))


confirmable_tool(ConfirmableTool(
    name="denoise_audio",
    permission="render-cost",
    cost="render",
    summarize=_summarize_denoise_audio,
    execute=_execute_denoise_audio,
    validate=_validate_denoise_audio,
))


confirmable_tool(ConfirmableTool(
    name="convert_video_to_gif",
    permission="render-cost",
    cost="render",
    summarize=_summarize_convert_video_to_gif,
    execute=_execute_convert_video_to_gif,
    validate=_validate_convert_video_to_gif,
))

