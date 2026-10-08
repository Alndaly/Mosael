"""出图、出片、出音乐/音效、念字、做播客 —— 花的是供应商的钱,所以都要先开卡。

它们**不自己实现生成**:都汇进 create_generation_job / voices 那两条漏斗。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _asked_for(payload: dict[str, Any]) -> str:
    """卡上写出**要生成什么**。提示词/正文/选题三个键里哪个有就用哪个(四个工具各用一个);
    不收提示词的模型(放大这类)什么字都没有,卡上就写用哪个模型。"""
    return str(payload.get("prompt") or payload.get("text") or payload.get("topic") or payload.get("model") or "")[:80]


#: 走生成漏斗(create_generation_job)的那三个工具各自生成哪一种。此前 image / video 两个执行体
#: 各抄一份、靠 `"image" if tool == "generate_image" else "video"` 判 —— 多一种就会被判成视频。
_GENERATION_KIND_BY_TOOL = {"generate_image": "image", "generate_video": "video", "generate_sound": "audio"}


def _execute_generation(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import parse_source_assets
    from app.core.unit_of_work import after_commit
    from app.domain.generation.runner import start_generation_thread
    from app.domain.entities import parse_entity_ids
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
        entity_ids=parse_entity_ids(payload.get("entity_ids")),
        #: 智能体声明的授权(generate_video 的 digital_human_consent);卡片由人批准时一并过目。
        digital_human_consent=payload.get("digital_human_consent") is True,
    )
    # 生成线程重开会话去读刚建的行 —— 等入口提交之后再起;执行体后面炸了、整个回滚,它就不起。
    generation_id = generation.id
    after_commit(db, lambda: start_generation_thread(generation_id))
    #: `session_id`:open_view("ai", 它) 把人带到这条创作会话(ADR 0055 §9)。
    result: dict[str, Any] = {"job_id": job.id, "generation_id": generation.id, "session_id": generation.session_id}
    #: `@` 到的资产挂了哪几张参考图、哪几张没挂上(ADR 0027)—— 模型据此如实告诉用户,而不是以为全挂上了。
    if generation.request.get("entities"):
        result["entities"] = generation.request["entities"]
    return result


def _check_generation_text(db: Session, payload: dict[str, Any], actor: str | None, kind: str) -> None:
    """提示词 / 歌词按**选中模型的描述符**判(见 generation.operations.check_text_inputs),和执行时的漏斗
    同一套规矩:放大这类不收提示词的模型不写提示词是对的,写了反而当场说;文生图什么都不写照样拦。
    此前这里写死「必须有提示词」,于是智能体想替人跑一张放大工作流,卡都开不出来。"""
    from app.domain.generation.operations import GenerationDomainError, check_text_inputs

    # 点名了资产、自己没写提示词:资产的提示词描述在执行时才拼进来(domain/entities/mentions),空着不算缺。
    if payload.get("entity_ids") and not str(payload.get("prompt") or "").strip():
        return
    try:
        check_text_inputs(
            db,
            user_id=actor,
            kind=kind,
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            provider_profile_id=str(payload.get("provider_profile_id") or "").strip() or None,
            prompt=str(payload.get("prompt") or ""),
            parameters=dict(payload.get("parameters") or {}),
        )
    except GenerationDomainError as exc:
        raise ConfirmationError.relay(exc) from exc


def _validate_generate_image(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _check_generation_text(db, payload, actor, "image")

def _summarize_generate_image(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_generateImage", {"asked": _asked_for(payload)}

def _validate_generate_video(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain.generation.operations import GenerationDomainError, check_digital_human_rights, is_digital_human_request

    #: 数字人没声明授权、音色或人物缺声明:开卡时就说,不等人批准之后才在漏斗里被拒。
    sources = [one for one in payload.get("source_assets") or [] if isinstance(one, dict)]
    if is_digital_human_request(sources, dict(payload.get("parameters") or {})):
        if payload.get("digital_human_consent") is not True:
            raise ConfirmationError("genErr_digitalHumanNeedsConsent")
        try:
            check_digital_human_rights(db, workspace_id, sources)
        except GenerationDomainError as exc:
            raise ConfirmationError.relay(exc) from exc
    _check_generation_text(db, payload, actor, "video")

def _summarize_generate_video(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_generateVideo", {"asked": _asked_for(payload)}

def _validate_generate_sound(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _check_generation_text(db, payload, actor, "audio")

def _summarize_generate_sound(db: Session, payload: dict[str, Any]) -> Summary:
    asked = _asked_for(payload) or str((payload.get("parameters") or {}).get("lyrics") or "")[:80]
    return "confirm_generateSound", {"asked": asked}

def _validate_generate_audio(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    """引擎和音色在**开卡时**就定成确定的一对,写回卡上 —— 用户批的就是卡上那一对,执行时不再猜。

    配音没有默认:此前这里留空引擎就去查「语音合成的默认模型」,而那一格按设计不存在(`defaultable=False`),
    于是只给音色的调用总是在批准之后才失败,报「没有配置真实供应商」—— 智能体据此让用户去设置里给 Edge 配一个
    引擎,而 Edge 是内置的、免费的、什么都不用配。怎么认见 engine_catalog.pick_speech。
    """
    from app.domain.voices.engine_catalog import pick_speech
    from app.domain.voices.remote import RemoteConsentRequired
    from app.domain.voices.speech import SpeechProviderUnavailable
    from app.domain.voices.voices import VoiceError

    if not str(payload.get("text") or "").strip():
        raise ConfirmationError("confirmErr_speechNeedsText")
    try:
        payload["engine"], payload["voice"] = pick_speech(
            db,
            engine=str(payload.get("engine") or ""),
            voice=str(payload.get("voice") or ""),
            user_id=actor,
            workspace_id=workspace_id,
        )
        _check_remote_voice(db, payload, workspace_id=workspace_id, actor=actor)
    except (SpeechProviderUnavailable, VoiceError, RemoteConsentRequired) as exc:
        raise ConfirmationError.relay(exc) from exc


def _check_remote_voice(db: Session, payload: dict[str, Any], *, workspace_id: str, actor: str | None) -> None:
    """远端引擎念配音库里的嗓子(ADR 0037):开卡时就问(声明过是谁的、这个账号同意过上传),不等批准之后任务才失败。
    没同意过的,卡开不出来,那句话告诉智能体请用户去配音库点「复刻到百炼」。"""
    from app.domain.voices.remote import check_voice, speaks_library_voice

    engine, voice = str(payload.get("engine") or ""), str(payload.get("voice") or "")
    if speaks_library_voice(db, engine, voice):
        check_voice(db, engine=engine, voice_id=voice, workspace_id=workspace_id, user_id=actor,
                    engine_model=str(payload.get("model") or "").strip())

def _summarize_generate_audio(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_generateAudio", {"asked": _asked_for(payload)}

def _execute_generate_audio(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    """念卡上定好的那一对,记成创作页里的一条新会话(ADR 0055 §4,和它出图一样)。参数经 synthesis_params 拼,和工作流、
    画板、字幕配音同一条路。"""
    payload = confirmation.payload
    from app.domain.generation.voiced import create_speech

    record, job = create_speech(
        db,
        workspace_id=confirmation.workspace_id,
        session_id=None,
        project_id=payload.get("project_id"),
        created_by=actor,
        text=str(payload.get("text") or ""),
        engine=str(payload.get("engine") or ""),
        voice=str(payload.get("voice") or ""),
        engine_model=str(payload.get("model") or "").strip(),
        speed=float(payload.get("speed") or 1.0),
    )
    return {"job_id": job.id, "generation_id": record.id, "session_id": record.session_id}

def _validate_generate_podcast(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
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
    """一段双人播客,记成创作页里的一条新会话(ADR 0055 §4)。「照读」给的是一段字(不是逐段的稿子):按句拆成两人轮流的几段
    再交进去 —— 领域只认逐段的稿子(`turns`)。"""
    payload = confirmation.payload
    from app.ai.providers import split_podcast_rounds
    from app.domain.generation.voiced import create_podcast

    mode = str(payload.get("mode") or "summarize")
    text = str(payload.get("text") or payload.get("prompt") or "")
    speakers = [str(one) for one in (payload.get("speakers") or []) if str(one or "").strip()]
    turns = None
    if mode == "read":
        dual = len(speakers) != 1
        turns = [{"speaker": index % 2 if dual else 0, "text": line}
                 for index, line in enumerate(split_podcast_rounds(text, dual=dual))]
    record, job = create_podcast(
        db,
        workspace_id=confirmation.workspace_id,
        session_id=None,
        project_id=payload.get("project_id"),
        created_by=actor,
        mode=mode,
        text=str(payload.get("topic") or "") if mode == "research" else text,
        turns=turns,
        speakers=[{"value": one} for one in speakers],
        speed=float(payload.get("speed") or 1.0),
        provider_profile_id=str(payload.get("provider_profile_id") or "").strip() or None,
    )
    return {"job_id": job.id, "generation_id": record.id, "session_id": record.session_id}

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


