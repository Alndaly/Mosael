"""素材和时间线上的确认卡工具:改时间线、导出、字幕配音、分离、降噪、转 GIF、从链接下载。

这几件事的共同点是**要么改用户的片子、要么让这台机器忙很久**,所以都得先开卡。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment, tr
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.db.models import Sequence
from app.domain.sequences import operations as seq_ops
from app.domain.sequences.errors import SequenceDomainError

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
    """开卡前把这组操作**完整地认一遍、真做一遍**:参数按每种操作的模型认(写错的参数名、缺的必填、不是数的数,
    报错里带着正确写法),再在一个保存点里照着现在的时间线做一遍然后撤掉 —— 片段不存在、轨道类型不对、
    切点越界这类只有做的时候才知道的错,在这里就告诉智能体,而不是等用户批准之后才失败。

    卡上存的是认过之后的那一份(补齐了缺省值):卡上写的、批准后做的,就是校验过的那一份。
    """
    _sequence_in(db, workspace_id, payload)
    try:
        payload["operations"] = seq_ops.normalized_edit_operations(payload.get("operations"))
    except SequenceDomainError as exc:
        raise ConfirmationError.relay(exc) from exc
    _rehearse_edit_timeline(db, str(payload["sequence_id"]), payload["operations"], actor)


def _rehearse_edit_timeline(db: Session, sequence_id: str, operations: list[dict[str, Any]], actor: str | None) -> None:
    """在保存点里逐条做一遍,做完(或做不下去)都回滚。逐条做是为了说清**第几条**做不了。"""
    savepoint = db.begin_nested()
    try:
        for index, operation in enumerate(operations, start=1):
            try:
                seq_ops.apply_edit_operations(db, sequence_id, [operation], actor_id=actor)
            except SequenceDomainError as exc:
                raise ConfirmationError(
                    "confirmErr_timelineOpFails", index=index, kind=operation["kind"], reason=str(exc)
                ) from exc
    finally:
        savepoint.rollback()
        # 版本号是用条件 UPDATE 改的(见 _record_operation),会话里那条序列的 revision 跟着变了,
        # 回滚保存点不一定把它带回来 —— 让它下次读的时候重新取。
        sequence = db.get(Sequence, sequence_id)
        if sequence is not None:
            db.expire(sequence)


def _summarize_edit_timeline(db: Session, payload: dict[str, Any]) -> Summary:
    kinds = [operation.get("kind", "?") for operation in payload.get("operations", [])]
    return "confirm_editTimeline", {
        "count": len(kinds),
        "kinds": ", ".join(kinds[:6]) + ("…" if len(kinds) > 6 else ""),
    }


def _execute_edit_timeline(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    sequence_id = str(payload["sequence_id"])
    applied = seq_ops.apply_edit_operations(db, sequence_id, payload["operations"], actor_id=actor)
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
    #: 引擎和音色在**开卡时**就定成确定的一对、写回卡上,和 generate_audio 同一个认法(engine_catalog.pick_speech):
    #: 引擎按名字或 id 认,只给了音色就按音色认出是哪一家,点名的引擎现在就得用得上、克隆音色得在这个工作区。
    #: 此前这里只认引擎、不看音色:一个不存在的音色(或别的工作区的克隆音色)照样开卡,用户批了之后每一句都合成失败。
    from app.domain.voices.engine_catalog import pick_speech
    from app.domain.voices.speech import CLONE_ENGINE, SpeechProviderUnavailable
    from app.domain.voices.voices import VoiceError

    try:
        engine, voice = pick_speech(
            db,
            engine=str(payload.get("engine") or ""),
            voice=str(payload.get("engine_voice") or payload.get("voice_id") or ""),
            user_id=actor,
            workspace_id=workspace_id,
        )
    except (SpeechProviderUnavailable, VoiceError) as exc:
        raise ConfirmationError.relay(exc) from exc
    clone = engine == CLONE_ENGINE
    payload.update(engine=engine, voice_id=voice if clone else "", engine_voice="" if clone else voice)


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
    from app.domain.voices.engine_catalog import synthesis_params
    from app.domain.voices.speech import CLONE_ENGINE
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
    from app.domain.audio_capabilities import SEPARATION

    named = str(payload.get("engine") or "").strip()
    payload["engine"] = _named_provider(db, actor, SEPARATION, named).id if named and named != "auto" else ""


def _summarize_separate_audio(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_separateAudio", {}


def _execute_separate_audio(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Asset
    from app.domain.assets.separation import start_separation_job

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
    from app.domain.assets.denoise import DENOISABLE_KINDS, ready_adapter

    asset = db.get(Asset, str(payload.get("asset_id") or ""))
    if asset is None or asset.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_assetNotInWorkspace")
    if asset.kind not in DENOISABLE_KINDS:
        raise ConfirmationError("confirmErr_denoiseNeedsAudio")
    # 引擎和档位在**开卡之前**就判:批准一张注定失败的卡,只是把同一句话推迟到点完之后。
    #: 引擎按名字或 id 认(内置引擎、配好的降噪插件都行,ADR 0032),认出来就换成提供方 id 存下。
    from app.domain.audio_capabilities import DENOISE

    named = str(payload.get("engine") or "").strip()
    payload["engine"] = _named_provider(db, actor, DENOISE, named).id if named and named != "auto" else ""
    try:
        payload["strength"] = checked_strength(str(payload.get("strength") or ""))
        adapter = ready_adapter(db, actor, str(payload.get("engine") or ""))
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
    from app.domain.assets.denoise import start_denoise_job

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

def _validate_split_image_grid(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.db.models import Asset
    from app.domain.assets.image_grid import ImageGridError, parse_grid

    asset = db.get(Asset, str(payload.get("asset_id") or ""))
    if asset is None or asset.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    if asset.kind != "image":
        raise ConfirmationError("confirmErr_gridNeedsImage")
    try:
        parse_grid(str(payload.get("grid") or "3x3"))
    except ImageGridError as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc


def _summarize_split_image_grid(db: Session, payload: dict[str, Any]) -> Summary:
    from app.domain.assets.image_grid import GRIDS

    rows, cols = GRIDS.get(str(payload.get("grid") or "3x3"), (3, 3))
    return "confirm_splitImageGrid", {"rows": rows, "cols": cols, "count": rows * cols}


def _execute_split_image_grid(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    """本机切,一两秒的事,不起后台任务:确认完直接交回切出来的那几张。"""
    payload = confirmation.payload
    from app.db.models import Asset
    from app.domain.assets.image_grid import ImageGridError, split_image_grid

    asset = db.get(Asset, str(payload["asset_id"]))
    if asset is None or asset.workspace_id != confirmation.workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    try:
        pieces = split_image_grid(db, asset, grid=str(payload.get("grid") or "3x3"), gutter=bool(payload.get("trim_gutter")))
    except ImageGridError as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc
    return {"asset_ids": [piece.id for piece in pieces], "source_asset_id": asset.id}

def _named_provider(db: Session, actor: str | None, capability: Any, name_or_id: str):
    """智能体按名字点一家(ADR 0032 §3):认不出就说清楚配好了的有哪几家。"""
    from app.domain import capabilities

    found = capabilities.resolve_named(db, actor, capability, name_or_id)
    if found is None:
        ready = [one.name for one in capabilities.providers(db, actor, capability) if not one.missing]
        raise ConfirmationError("confirmErr_unknownProvider", name=name_or_id, choices=tr("punct_listSep").join(ready))
    return found


def _document_parser(db: Session, actor: str | None, name_or_id: str):
    from app.domain.documents import CAPABILITY

    return _named_provider(db, actor, CAPABILITY, name_or_id)


def _validate_reparse_document(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.db.models import Asset

    asset = db.get(Asset, str(payload.get("asset_id") or ""))
    if asset is None or asset.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    if asset.kind != "document":
        raise ConfirmationError("confirmErr_parseNeedsDocument")
    _document_parser(db, actor, str(payload.get("parser") or ""))


def _summarize_reparse_document(db: Session, payload: dict[str, Any]) -> Summary:
    #: 选的是插件(MinerU)时文档会离开本机 —— 卡上总说一句,不在这里再去查是哪一种。
    return "confirm_reparseDocument", {"parser": str(payload.get("parser") or "")}


def _execute_reparse_document(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    """起一次解析,交回解析任务;读正文用 read_document(它会等一小会儿,云端解析常要几分钟,还在解析就过一会儿再读)。"""
    payload = confirmation.payload
    from app.db.models import Asset
    from app.domain.capabilities import CapabilityUnavailable
    from app.domain.documents.extraction import start_parse
    from app.domain.documents.local import DocumentParseError

    asset = db.get(Asset, str(payload["asset_id"]))
    if asset is None or asset.workspace_id != confirmation.workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    provider = _document_parser(db, actor, str(payload.get("parser") or ""))
    try:
        extraction = start_parse(db, asset, owner_user_id=actor, provider_id=provider.id, created_by=actor)
    except (CapabilityUnavailable, DocumentParseError) as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc
    return {"asset_id": asset.id, "extraction_id": extraction.id, "job_id": extraction.job_id, "parser": provider.name}

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
    capability="speech",
))


confirmable_tool(ConfirmableTool(
    name="separate_audio",
    permission="render-cost",
    cost="render",
    capability="audio_separation",
    summarize=_summarize_separate_audio,
    execute=_execute_separate_audio,
    validate=_validate_separate_audio,
))


confirmable_tool(ConfirmableTool(
    name="denoise_audio",
    permission="render-cost",
    cost="render",
    capability="audio_denoise",
    summarize=_summarize_denoise_audio,
    execute=_execute_denoise_audio,
    validate=_validate_denoise_audio,
))


def _validate_import_from_url(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain import browser as browser_domain

    url = str(payload.get("url") or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ConfirmationError("confirmErr_browserHttpOnly")
    if str(payload.get("kind") or "video") not in ("video", "audio"):
        raise ConfirmationError("urlImportErr_badKind")
    profile_id = str(payload.get("profile_id") or "").strip()
    if profile_id:
        try:
            profile = browser_domain.get_profile(db, workspace_id, profile_id)
        except browser_domain.BrowserDomainError as exc:
            raise ConfirmationError(str(exc)) from exc
        # 卡上要点名借的是哪个登录身份(摘要拿不到库里的名字)。
        payload["profile_name"] = profile.name


def _summarize_import_from_url(db: Session, payload: dict[str, Any]) -> Summary:
    name = str(payload.get("profile_name") or payload.get("profile_id") or "").strip()
    return "confirm_importFromUrl", {
        "url": str(payload.get("url") or ""),
        "kind": fragment("confirm_importAudio" if payload.get("kind") == "audio" else "confirm_importVideo"),
        "login": fragment("confirm_importWithProfile", name=name) if name else "",
    }


def _execute_import_from_url(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import sharing
    from app.domain.assets.from_url import UrlImportError, start_url_import

    payload = confirmation.payload
    profile_id = str(payload.get("profile_id") or "").strip()
    try:
        # 借登录态是用档案主人的身份:批准的人自己得能用这个档案,别人的私有档案在这里被拒(见 browser.usable_profile)。
        job = start_url_import(
            db,
            workspace_id=confirmation.workspace_id,
            project_id=None,
            items=[{"url": str(payload["url"]), "title": ""}],
            kind=str(payload.get("kind") or "video"),
            created_by=actor,
            profile_id=profile_id or None,
        )
    except (UrlImportError, sharing.NotUsableError) as exc:
        raise ConfirmationError(str(exc)) from exc
    return {"job_id": job.id}


confirmable_tool(ConfirmableTool(
    name="import_from_url",
    permission="external",
    cost="none",
    summarize=_summarize_import_from_url,
    execute=_execute_import_from_url,
    validate=_validate_import_from_url,
))


confirmable_tool(ConfirmableTool(
    name="convert_video_to_gif",
    permission="render-cost",
    cost="render",
    summarize=_summarize_convert_video_to_gif,
    execute=_execute_convert_video_to_gif,
    validate=_validate_convert_video_to_gif,
))


confirmable_tool(ConfirmableTool(
    name="split_image_grid",
    permission="edit",
    cost="none",
    summarize=_summarize_split_image_grid,
    execute=_execute_split_image_grid,
    validate=_validate_split_image_grid,
))


confirmable_tool(ConfirmableTool(
    name="reparse_document",
    permission="edit",
    cost="none",
    capability="document_parse",
    summarize=_summarize_reparse_document,
    execute=_execute_reparse_document,
    validate=_validate_reparse_document,
))
