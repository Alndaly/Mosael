from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from app.api.responses import file_response

from app.api.deps import CurrentUser, DbSession, Tx
from app.domain.voices.transcription import ASRError
from app.core.i18n import get_current_locale, tr, translate_fields
from app.db.models import Job
from app.api.schemas import (
    EngineSynthesizeRequest,
    RemoteCopyRequest,
    VoiceDeleteOut,
    VoicePreviewRequest,
    TtsEngineChoiceOut,
    TtsVoiceOut,
    JobOut,
    SynthesizeRequest,
    TtsConfigOut,
    TtsConfigUpdate,
    TtsEngineOut,
    VoiceFromSpeakerRequest,
    VoiceOut,
    VoiceUpdate,
)
from app.ai.runtime import tts_daemon, tts_models
from app.domain.voices import tts_settings, voices
from app.domain.permissions import ensure_deployment_admin
from app.domain.voices import use_cases as voice_uc
from app.ai.runtime import config as tts_config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voices"])


def _voice_out(db, voice, user_id: str, copies: list | None = None) -> dict:
    from app.domain.voices import remote

    if copies is None:
        copies = remote.copies_by_voice(db, [voice.id], owner_user_id=user_id).get(voice.id, [])
    return {
        "id": voice.id,
        "name": voice.name,
        "reference_text": voice.reference_text,
        "source": voice.source,
        "source_speaker": voice.source_speaker,
        "has_reference": bool(voice.reference_key),
        "consent_kind": voice.consent_kind,
        "consent_at": voice.consent_at,
        "created_at": voice.created_at,
        "remote_copies": [_copy_out(db, copy) for copy in copies],
    }


def _copy_out(db, copy) -> dict:
    from app.db.models import ProviderProfile
    from app.domain.voices.speech import BUILTIN_PREFIX

    profile = db.get(ProviderProfile, copy.provider_profile_id)
    return {
        "id": copy.id,
        "engine": f"{BUILTIN_PREFIX}{copy.engine}",
        "provider_profile_id": copy.provider_profile_id,
        "connection": profile.name if profile is not None else "",
        "target_model": copy.target_model,
        "status": copy.status,
        #: 存的是远端的原话或一个文案 key;是 key 就按读的人的语言翻。
        "error": tr(copy.error) if copy.error else "",
        "last_used_at": copy.last_used_at,
        "created_at": copy.created_at,
    }


@router.get("/voices", response_model=list[VoiceOut])
def list_voices(workspace_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    from app.domain.voices import remote

    voice_uc.ensure_can_list(db, user, workspace_id)
    rows = voices.list_voices(db, workspace_id)
    copies = remote.copies_by_voice(db, [voice.id for voice in rows], owner_user_id=user.id)
    return [_voice_out(db, voice, user.id, copies.get(voice.id, [])) for voice in rows]


@router.post("/voices/upload", response_model=VoiceOut)
def upload_voice(
    db: Tx,
    user: CurrentUser,
    workspace_id: str = Form(...),
    name: str = Form(...),
    reference_text: str = Form(""),
    #: 这把嗓子是谁的(必选,ADR 0028 §5):本人 / 已取得本人同意 / 虚构。
    consent_kind: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    voice_uc.ensure_can_speak(db, user, workspace_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "ref").suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        voice = voices.create_from_upload(
            db, workspace_id=workspace_id, source=tmp_path, name=name, reference_text=reference_text,
            consent_kind=consent_kind, actor_id=user.id,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return _voice_out(db, voice, user.id, [])


@router.post("/voices/from-speaker", response_model=VoiceOut)
def voice_from_speaker(body: VoiceFromSpeakerRequest, db: Tx, user: CurrentUser) -> dict:

    asset = voice_uc.source_asset(db, user, body.asset_id)
    try:
        voice = voices.create_from_speaker(
            db, workspace_id=asset.workspace_id, asset_id=body.asset_id, speaker=body.speaker, name=body.name,
            consent_kind=body.consent_kind, actor_id=user.id,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _voice_out(db, voice, user.id, [])


@router.patch("/voices/{voice_id}", response_model=VoiceOut)
def update_voice(voice_id: str, body: VoiceUpdate, db: Tx, user: CurrentUser) -> dict:
    voice = voice_uc.usable(db, user, voice_id)
    try:
        return _voice_out(db, voices.update_voice(db, voice, name=body.name, reference_text=body.reference_text,
                                                  consent_kind=body.consent_kind, actor_id=user.id), user.id)
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/voices/{voice_id}/recognize-reference", response_model=VoiceOut)
def recognize_reference(voice_id: str, db: Tx, user: CurrentUser) -> dict:
    """转写一遍参考音频(按这个人的转写默认),把参考文本填上。"""
    voice = voice_uc.usable(db, user, voice_id)
    try:
        return _voice_out(db, voices.recognize_reference_text(db, voice, actor_id=user.id), user.id)
    except (voices.VoiceError, ASRError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/voices/{voice_id}/remote-copies", response_model=JobOut)
def copy_voice_to_engine(voice_id: str, body: RemoteCopyRequest, db: Tx, user: CurrentUser) -> Job:
    """把这把嗓子复刻到一个远端引擎上(ADR 0037):配音库的「复刻到百炼」,或配音时确认框里点了同意。

    参考音频会传到这个人自己的那家账号里,所以要他点过头:这个账号没同意过、请求又没带 `consent`,回 409(和配音那边
    同一个确认框)。同意记在副本上,之后换模型、副本被删按需重建,不再问。复刻在任务里做(上传、建、等它就绪,
    约十秒),这里只排上。
    """
    from app.domain.voices import remote

    voice = voice_uc.usable(db, user, voice_id)
    try:
        return remote.start_enrollment(
            db, voice, engine=body.engine, actor_id=user.id, consent=body.consent,
            provider_profile_id=body.provider_profile_id,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/voices/{voice_id}", response_model=VoiceDeleteOut)
def delete_voice(voice_id: str, db: Tx, user: CurrentUser) -> dict:
    """删一把嗓子:先删它在远端的副本,删不掉的列在回包里(本机这一行照删)。"""
    voice = voice_uc.usable(db, user, voice_id)
    failures = voices.delete_voice(db, voice)
    return {
        "remote_failures": [
            {
                "connection": failure.connection,
                "target_model": failure.target_model,
                "remote_voice_id": failure.remote_voice_id,
                "reason": tr(failure.reason),
            }
            for failure in failures
        ]
    }


@router.get("/voices/{voice_id}/sample")
def voice_sample(voice_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    voice = voice_uc.readable(db, user, voice_id)
    path = voices.reference_path(voice)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=tr("routeErr_referenceAudioMissing"))
    return file_response(db, path, media_type="audio/wav")


@router.post("/voices/{voice_id}/synthesize", response_model=JobOut)
def synthesize(voice_id: str, body: SynthesizeRequest, db: Tx, user: CurrentUser):
    voice_uc.usable(db, user, voice_id)
    try:
        return voices.start_synthesis(
            db, voice_id=voice_id, text=body.text, project_id=body.project_id,
            created_by=user.id, clone_engine=body.clone_engine, clone_model=getattr(body, "clone_model", ""),
            speed=body.speed,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tts/f5-models")
def list_f5_models(user: CurrentUser) -> list[dict]:
    """本地克隆能用哪几份权重,各自认得什么语言、装没装。

    这是「引擎 / 模型」分开之后新长出来的一层:引擎什么语言都支持,支持范围由权重决定
    (见 ai/runtime/f5_models)。
    """
    from app.ai.runtime import f5_models

    locale = get_current_locale()
    return [translate_fields(row, ("label", "note"), locale) for row in f5_models.list_status()]


@router.post("/tts/f5-models/{model_id}/download")
def download_f5_model(model_id: str, db: DbSession, user: CurrentUser) -> dict:
    # 和引擎下载同一道闸门:往**后端主机**上装 1.4 GB 权重是部署级动作,不属于任何工作区。
    ensure_deployment_admin(db, user)
    from app.ai.runtime import f5_models

    try:
        return f5_models.start_download(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=tr("routeErr_noSuchModel")) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tts/engines", response_model=list[TtsEngineChoiceOut])
def list_tts_engines(db: DbSession, user: CurrentUser) -> list[dict]:
    """Engines the配音 UI can offer, and what each one needs from the user."""
    from app.domain.voices.engine_catalog import describe_engines

    locale = get_current_locale()
    return [translate_fields(row, ("label", "note"), locale) for row in describe_engines(db, user.id)]


@router.get("/tts/voices", response_model=list[TtsVoiceOut])
def list_tts_voices(engine: str, db: DbSession, user: CurrentUser, workspace_id: str = "") -> list[dict]:
    """The voices an engine can speak in, live where the account allows it (see engine_catalog).

    带上工作区时,能复刻的引擎(CosyVoice)在系统音色之外再列这个工作区配音库里的克隆音色(`cloned`,ADR 0037)。"""
    from app.domain.voices.engine_catalog import list_engine_voices

    if workspace_id:
        voice_uc.ensure_can_list(db, user, workspace_id)
    return list_engine_voices(db, engine, user_id=user.id, workspace_id=workspace_id)


@router.post("/tts/preview")
def preview_voice(body: VoicePreviewRequest, db: DbSession, user: CurrentUser) -> Response:
    """试听一个配音引擎里的一把嗓子(资产的音色、以后挑嗓子的地方):念一小句,音频直接回给调用方。

    **和真用的时候同一条路** —— 参数由 engine_catalog.synthesis_params 凑(火山的资源族它自己查),合成走
    speak_to_file(解析连接、筛模型、记账),听到的就是以后念台词的那个声音。不建任务、不进素材库:试听
    活到播完为止。本地克隆的音色不在这里 —— 它的参考录音就是它(`GET /voices/{id}/sample`)。
    """
    from app.domain.voices.engine_catalog import synthesis_params
    from app.domain.voices.remote import RemoteConsentRequired
    from app.domain.voices.speech import CLONE_ENGINE

    # 念一句是花钱的(各家 TTS 按字符计费),和配音同一档权限;记账挂在这个工作区上。
    voice_uc.ensure_can_speak(db, user, body.workspace_id)
    if body.engine == CLONE_ENGINE:
        raise HTTPException(status_code=422, detail=tr("routeErr_previewCloneUsesSample"))
    try:
        params = synthesis_params(
            db, engine=body.engine, voice=body.voice, user_id=user.id, workspace_id=body.workspace_id
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="mosael-preview-") as tmp:
        try:
            out = voices.speak_to_file(
                db,
                text=body.text.strip(),
                engine=body.engine,
                engine_voice=str(params.get("engine_voice") or ""),
                speed=1.0,
                workspace_id=body.workspace_id,
                user_id=user.id,
                voice_resource=str(params.get("engine_voice_resource") or ""),
                out_dir=Path(tmp),
                source_type="voice_preview",
                source_id=user.id,
                #: 能复刻的引擎点了配音库里的嗓子:念的是它的远端副本(ADR 0037)。
                voice_id=str(params.get("voice_id") or "") or None,
            )
        except RemoteConsentRequired:
            raise  # 不是失败:界面据此弹「上传到哪」的确认框
        except Exception as exc:  # noqa: BLE001 — 合成失败是结果(缺 Key、音色不存在),不是服务端故障
            raise HTTPException(status_code=422, detail=str(exc)[:300]) from exc
        audio = out.read_bytes()
        media_type = "audio/mpeg" if out.suffix == ".mp3" else "audio/wav"
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post("/tts/synthesize", response_model=JobOut)
def synthesize_with_engine(body: EngineSynthesizeRequest, db: Tx, user: CurrentUser):
    """Synthesise with a remote engine. Separate from /voices/{id}/synthesize because the engine
    supplies the voice — a stock one, or (CosyVoice) a library voice it speaks through its remote copy,
    which needs the account's consent first (409 `remote_voice_consent_required`, ADR 0037)."""
    voice_uc.ensure_can_speak(db, user, body.workspace_id)
    try:
        return voices.start_synthesis(
            db,
            text=body.text,
            project_id=body.project_id,
            created_by=user.id,
            workspace_id=body.workspace_id,
            engine=body.engine,
            engine_voice=body.engine_voice,
            voice_id=body.voice_id or None,
            engine_voice_resource=body.engine_voice_resource,
            provider_profile_id=body.provider_profile_id,
            engine_model=body.engine_model,
            speed=body.speed,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _tts_config_out() -> dict:
    cfg = tts_config.get()
    return {
        "engine": cfg.engine,
        "python_path": cfg.python_path,
        "pip_index": cfg.pip_index,
        "fish_repo_dir": cfg.fish_repo_dir,
        "fish_model_dir": cfg.fish_model_dir,
        **tts_models.probe_interpreter(cfg.engine),
    }


def _refuse_to_report_a_save_that_did_not_take(wanted: dict[str, str]) -> None:
    """刚写进去的那几个值,回读一遍必须还是它们 —— 不是的话报错,**不要回一个 200**。

    这道校验存在的理由是一次真实的故障:配置来源(`config.use_source`)装在了 lifespan 里,
    于是读取路径悄悄回落到环境变量那份默认值。行确实写进了库,可接口回的是旧的 f5-tts,
    一句错都不报 —— 用户看到的是"我明明改了、点了保存、它自己变回去了"。

    这不是那一个 bug 的补丁,是**那一类**的:写入路径只有这一条,而读取路径上任何一处让
    用户存的那份失真(装配没接上、`tts_settings.load` 吞掉数据库错误退回默认值、以后某个
    新的兜底),症状都是同一个形状 —— 存了、没生效、没人说。把"写完 = 读回来是同一份"钉在
    这里,那一整类就都会当场出声。

    **不回滚**:库里那一行是对的,坏的是读取那一侧。回滚等于把一次正确的写入也扔掉,
    换来的只是"一致地没生效"。留着它,修好读取侧(或重启)之后它就生效了。
    """
    saved = tts_config.get()
    drifted = {
        name: (value, getattr(saved, name, None))
        for name, value in wanted.items()
        if getattr(saved, name, None) != value
    }
    if not drifted:
        return
    detail = "; ".join(f"{name}: {want!r} → {got!r}" for name, (want, got) in drifted.items())
    logger.error("TTS 设置写进去了,回读却不是同一份:%s", detail)
    raise HTTPException(
        status_code=500,
        detail=tr("routeErr_ttsSettingsNotApplied", detail=detail),
    )


@router.get("/settings/tts", response_model=TtsConfigOut)
def get_tts_config(db: DbSession, user: CurrentUser) -> dict:
    return _tts_config_out()


@router.put("/settings/tts", response_model=TtsConfigOut)
def set_tts_config(body: TtsConfigUpdate, db: DbSession, user: CurrentUser) -> dict:
    # python_path lands in subprocess argv, so this route is remote code execution for
    # whoever can reach it.
    ensure_deployment_admin(db, user)
    row = tts_settings.saved_row(db)
    # **写和回读用的是同一份名单。** 分成两处的话,新加的字段会是"写进去了、没人验"的那个 ——
    # 而"没人验"正是下面那道校验要拦的东西。
    wanted = {
        "engine": body.engine,
        "python_path": body.python_path.strip(),
        "fish_repo_dir": body.fish_repo_dir.strip(),
        "fish_model_dir": body.fish_model_dir.strip(),
    }
    # pip 镜像、模型下载源不在这里写 —— 它们归「安装源」(见 routes/settings/system.set_install_source)。
    for name, value in wanted.items():
        setattr(row, name, value)
    db.commit()
    tts_config.refresh()
    _refuse_to_report_a_save_that_did_not_take(wanted)
    # 解释器路径/下载源/fish 目录刚改过 —— 探测缓存里的答案是按旧配置算的,
    # 而上一次的失败消息说的也是改之前那套(源已经换掉了,卡片还在说旧的那个)。
    tts_models.clear_runtime_probes()
    tts_models.forget_failures()
    # 常驻的合成进程是**带着旧 env 起来的**(检出目录、权重目录、下载源都在里面)。
    # 配置刚改过,让它重起一个 —— 否则下一次合成还按改之前那套跑。
    tts_daemon.pool().drop_all()
    return _tts_config_out()


@router.get("/tts/models", response_model=list[TtsEngineOut])
def list_tts_models(user: CurrentUser) -> list[dict]:
    locale = get_current_locale()
    return [translate_fields(row, ("label", "detail", "message"), locale) for row in tts_models.list_status()]


@router.post("/tts/models/{engine_id}/download", response_model=TtsEngineOut)
def download_tts_model(engine_id: str, db: DbSession, user: CurrentUser) -> dict:
    # 下载模型是往**后端主机**上装东西 —— 部署级动作,不属于任何工作区。
    ensure_deployment_admin(db, user)
    try:
        return tts_models.start_download(engine_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=tr("routeErr_unknownEngine")) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
