"""创作页里的语音和播客(ADR 0055):**记录**收在生成会话里,**活儿**由配音那一族做。

图像、视频、音乐走生成管线(`operations.create_generation_job` → 适配器);语音和播客不是生成适配器(ADR 0022 决定 2:
音色是每个引擎自己的一张表、带克隆和远端副本,字幕配音一个任务要念很多句),所以这里只做三件事:

1. 过会话的闸(点了名的会话:是他的;从创作页来的还要同一族,`lock_family`),没点名就现开一条 —— 和生成管线同一个
   `_named_session` / `_resolve_session`;
2. 叫配音那一族建任务(`voices.start_synthesis` / `start_podcast`),告诉它用量记在这条记录名下、产出登记之后交给 `attach_output`;
3. 写这条记录(`GenerationJob`,kind 是 `speech` / `podcast`)。

依赖方向是生成 → 配音:配音那一族不知道有生成记录,它只认 `usage_source` 和 `on_asset` 这两个普通的口子。失败、停止由
落终态监听抄到记录上(runner.record_failure,不看任务种类)。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from sqlalchemy.orm import Session

from app.db.model_base import new_id
from app.db.models import GeneratedAsset, GenerationJob, Job, ProviderProfile, Voice
from app.domain.generation.operations import _named_session, _resolve_session

SPEECH = "speech"
PODCAST = "podcast"
#: 播客记录的「模型」一格:一次合成出一整段对谈,不是某一个音色。
DIALOGUE = "dialogue"
#: 记录、用量事件上「这是哪条生成记录」的来源种类(和生成管线记账同一个,sessions._attach_costs 只认它)。
USAGE_SOURCE = "generation_job"


def attach_output(record_id: str, db: Session, asset_id: str) -> None:
    """配音那一族登记完产出、任务落「成功」之前(同一个事务)调到这里:把产出挂到记录上,补一行 `GeneratedAsset`。

    在同一个事务里挂,而不是等任务落终态再挂:那是提交之后另开的事务,中间那一下界面会读到「任务成功了、记录上没有产出」,
    画成一张一直在排队的占位(ADR 0055 §5)。会话在念的时候被删了(记录跟着没了)就什么都不做。"""
    record = db.get(GenerationJob, record_id)
    if record is None:
        return
    record.result_asset_id = asset_id
    request = dict(record.request or {})
    db.add(GeneratedAsset(
        asset_id=asset_id,
        provider=record.provider,
        model=record.model,
        prompt=str(request.get("prompt") or ""),
        parameters={key: value for key, value in request.items() if key != "prompt"},
        job_id=record.job_id,
    ))


def _existing_profile(db: Session, provider_profile_id: str | None) -> str | None:
    """记录上的连接一格有外键:给的 id 不在(界面带了一条删掉的)就不记,合成时照常由配音那一族自己解析。"""
    if provider_profile_id and db.get(ProviderProfile, provider_profile_id) is not None:
        return provider_profile_id
    return None


def create_speech(
    db: Session,
    *,
    workspace_id: str,
    session_id: str | None,
    project_id: str | None,
    created_by: str | None,
    text: str,
    engine: str,
    voice: str,
    voice_label: str = "",
    engine_label: str = "",
    engine_voice_resource: str = "",
    provider_profile_id: str | None = None,
    engine_model: str = "",
    clone_engine: str = "",
    clone_model: str = "",
    speed: float = 1.0,
    lock_family: bool = False,
) -> tuple[GenerationJob, Job]:
    """念一段字,记成会话里的一条(ADR 0055 §3)。`voice` 是「音色一格」:克隆引擎是配音库里的嗓子 id,别的引擎是它自己的音色
    (能复刻的引擎点配音库里的嗓子时也是嗓子 id)—— 和工作流、画板、智能体同一个口径,由 `synthesis_params` 拆成合成要的那组参数。

    `voice_label` / `engine_label`:界面那份目录里的名字(火山按账号现拉的音色只有界面那边知道名字),没给就在这里查。
    远端引擎念配音库里的嗓子还没同意上传时,`RemoteConsentRequired` 原样抛出(路由回 409,界面弹确认框)。"""
    from app.domain.voices.engine_catalog import engine_label as engine_name, synthesis_params
    from app.domain.voices.voice_labels import builtin_voice_label
    from app.domain.voices.voices import start_synthesis

    named = (
        _named_session(db, workspace_id=workspace_id, session_id=session_id, actor=created_by,
                       family_of=SPEECH if lock_family else None)
        if session_id else None
    )
    options: dict[str, Any] = {
        "clone_engine": clone_engine, "clone_model": clone_model,
        "provider_profile_id": provider_profile_id, "engine_model": engine_model,
        "engine_voice_resource": engine_voice_resource,
    }
    params = synthesis_params(
        db, engine=engine, voice=voice, speed=speed, user_id=created_by, workspace_id=workspace_id,
        **{key: value for key, value in options.items() if value},
    )
    engine = str(params["engine"])
    library_voice = db.get(Voice, str(params.get("voice_id") or "")) if params.get("voice_id") else None
    voice_name = library_voice.name if library_voice is not None else (voice_label.strip() or builtin_voice_label(voice) or voice)
    record_id = new_id()
    job = start_synthesis(
        db,
        text=text,
        project_id=project_id,
        created_by=created_by,
        voice_label=voice_name,
        usage_source=(USAGE_SOURCE, record_id),
        on_asset=partial(attach_output, record_id),
        **params,
    )
    session = _resolve_session(
        db, workspace_id=workspace_id, named=named, prompt=text, created_by=created_by, engine=(None, engine, SPEECH),
    )
    request: dict[str, Any] = {
        "prompt": text,
        "voice": voice,
        "voice_label": voice_name,
        "engine_label": engine_label.strip() or engine_name(db, engine, created_by),
        "speed": float(params.get("speed") or 1.0),
    }
    if params.get("clone_engine"):
        request["clone_engine"] = params["clone_engine"]
    if params.get("clone_model"):
        request["clone_model"] = params["clone_model"]
    if params.get("engine_voice_resource"):
        request["voice_resource"] = params["engine_voice_resource"]
    return _record(db, record_id, session_id=session.id, job=job, provider=engine, model=voice, kind=SPEECH,
                   provider_profile_id=_existing_profile(db, provider_profile_id), request=request), job


def create_podcast(
    db: Session,
    *,
    workspace_id: str,
    session_id: str | None,
    project_id: str | None,
    created_by: str | None,
    mode: str,
    text: str = "",
    turns: list[dict[str, Any]] | None = None,
    speakers: list[dict[str, str]] | None = None,
    speed: float = 1.0,
    provider_profile_id: str | None = None,
    lock_family: bool = False,
) -> tuple[GenerationJob, Job]:
    """一段双人播客,记成会话里的一条(ADR 0055 §6)。`text` 在「改写材料」时是材料、「聊一个主题」时是主题;「照稿念」给
    `turns: [{speaker: 0|1, text}]`(`speaker` 是 `speakers` 里的第几位)。`speakers` 是 `[{value, label}]`,label 只用来显示。
    连接没点名就用这个人设的播客默认连接。"""
    from app.domain.providers import models as provider_models
    from app.domain.voices.voice_labels import builtin_voice_label
    from app.domain.voices.speech import PODCAST_ENGINE
    from app.domain.voices.voices import podcast_speakers, start_podcast

    named = (
        _named_session(db, workspace_id=workspace_id, session_id=session_id, actor=created_by,
                       family_of=PODCAST if lock_family else None)
        if session_id else None
    )
    if not provider_profile_id:
        default = provider_models.resolve_default(db, "podcast", created_by)
        provider_profile_id = default.provider_profile_id if default is not None else None
    given = [one for one in (speakers or []) if str(one.get("value") or "").strip()]
    labels = {str(one["value"]): str(one.get("label") or "").strip() for one in given}
    chosen = podcast_speakers([str(one["value"]) for one in given])
    script = [{"speaker": turn.get("speaker"), "text": str(turn.get("text") or "").strip()} for turn in (turns or [])]
    script = [turn for turn in script if turn["text"]] if mode == "read" else []
    record_id = new_id()
    job = start_podcast(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        created_by=created_by,
        mode=mode,
        text=text if mode == "summarize" else "",
        topic=text if mode == "research" else "",
        turns=script,
        speakers=chosen,
        speed=speed,
        provider_profile_id=provider_profile_id,
        usage_source=(USAGE_SOURCE, record_id),
        on_asset=partial(attach_output, record_id),
    )
    subject = script[0]["text"] if script else text
    session = _resolve_session(
        db, workspace_id=workspace_id, named=named, prompt=subject, created_by=created_by,
        engine=(_existing_profile(db, provider_profile_id), PODCAST_ENGINE, PODCAST),
    )
    request: dict[str, Any] = {
        "mode": mode,
        "prompt": text if mode != "read" else "",
        "speakers": [{"value": voice, "label": labels.get(voice) or builtin_voice_label(voice) or voice} for voice in chosen],
        "speed": float(speed or 1.0),
    }
    if script:
        request["turns"] = script
    return _record(db, record_id, session_id=session.id, job=job, provider=PODCAST_ENGINE, model=DIALOGUE, kind=PODCAST,
                   provider_profile_id=_existing_profile(db, provider_profile_id), request=request), job


def _record(
    db: Session,
    record_id: str,
    *,
    session_id: str,
    job: Job,
    provider: str,
    model: str,
    kind: str,
    provider_profile_id: str | None,
    request: dict[str, Any],
) -> GenerationJob:
    from app.db.models import GenerationSession, now

    #: 任务中心「前往」打开的是这条创作会话(job_catalog 的 record_field)。任务是配音那一族建的,会话在它之后才定下来。
    job.payload = {**(job.payload or {}), "session_id": session_id}
    record = GenerationJob(
        id=record_id,
        workspace_id=job.workspace_id,
        session_id=session_id,
        job_id=job.id,
        provider_profile_id=provider_profile_id,
        provider=provider,
        model=model,
        kind=kind,
        request=request,
    )
    db.add(record)
    session = db.get(GenerationSession, session_id)
    if session is not None:
        session.updated_at = now()
    #: 不提交:提交归入口。任务在提交之后才派发(jobs.dispatch_job),那时记录已经在库里,`attach_output` 找得到它。
    db.flush()
    db.refresh(record)
    return record
