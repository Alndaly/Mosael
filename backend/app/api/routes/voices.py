from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, Request
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.domain.voices.transcription import ASRError
from app.core.i18n import normalize_locale, tr, translate_fields
from app.db.models import Job, Voice
from app.api.schemas import (
    EngineSynthesizeRequest,
    TtsEngineChoiceOut,
    PodcastRequest,
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
from app.domain.voices import voices
from app.domain.permissions import ensure_workspace_perm, ensure_deployment_admin, ensure_workspace_access
from app.ai.runtime import config as tts_config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voices"])


def _voice_out(voice) -> dict:
    return {
        "id": voice.id,
        "name": voice.name,
        "reference_text": voice.reference_text,
        "source": voice.source,
        "source_speaker": voice.source_speaker,
        "has_reference": bool(voice.reference_key),
        "created_at": voice.created_at,
    }


@router.get("/voices", response_model=list[VoiceOut])
def list_voices(workspace_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    return [_voice_out(v) for v in voices.list_voices(db, workspace_id)]


@router.post("/voices/upload", response_model=VoiceOut)
def upload_voice(
    db: DbSession,
    user: CurrentUser,
    workspace_id: str = Form(...),
    name: str = Form(...),
    reference_text: str = Form(""),
    file: UploadFile = File(...),
) -> dict:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "ref").suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        voice = voices.create_from_upload(
            db, workspace_id=workspace_id, source=tmp_path, name=name, reference_text=reference_text
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return _voice_out(voice)


@router.post("/voices/from-speaker", response_model=VoiceOut)
def voice_from_speaker(body: VoiceFromSpeakerRequest, db: DbSession, user: CurrentUser) -> dict:
    from app.db.models import Asset

    asset = db.get(Asset, body.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_assetNotFound"))
    ensure_workspace_perm(db, user, asset.workspace_id, "ai")
    try:
        voice = voices.create_from_speaker(
            db, workspace_id=asset.workspace_id, asset_id=body.asset_id, speaker=body.speaker, name=body.name
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _voice_out(voice)


@router.patch("/voices/{voice_id}", response_model=VoiceOut)
def update_voice(voice_id: str, body: VoiceUpdate, db: DbSession, user: CurrentUser) -> Voice:
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_voiceNotFound"))
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    try:
        return voices.update_voice(db, voice, name=body.name, reference_text=body.reference_text)
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/voices/{voice_id}/recognize-reference", response_model=VoiceOut)
def recognize_reference(voice_id: str, db: DbSession, user: CurrentUser) -> Voice:
    """用本机的转写引擎听一遍参考音频,把参考文本填上。"""
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_voiceNotFound"))
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    try:
        return voices.recognize_reference_text(db, voice)
    except (voices.VoiceError, ASRError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/voices/{voice_id}", status_code=204)
def delete_voice(voice_id: str, db: DbSession, user: CurrentUser) -> Response:
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_voiceNotFound"))
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    voices.delete_voice(db, voice)
    return Response(status_code=204)


@router.get("/voices/{voice_id}/sample")
def voice_sample(voice_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_voiceNotFound"))
    ensure_workspace_access(db, user, voice.workspace_id)
    path = voices.reference_path(voice)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=tr("routeErr_referenceAudioMissing"))
    return FileResponse(path, media_type="audio/wav")


@router.post("/voices/{voice_id}/synthesize", response_model=JobOut)
def synthesize(voice_id: str, body: SynthesizeRequest, db: DbSession, user: CurrentUser):
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_voiceNotFound"))
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    try:
        return voices.start_synthesis(
            db, voice_id=voice_id, text=body.text, project_id=body.project_id,
            created_by=user.id, clone_engine=body.clone_engine, clone_model=getattr(body, "clone_model", ""),
            speed=body.speed,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tts/f5-models")
def list_f5_models(request: Request, user: CurrentUser) -> list[dict]:
    """本地克隆能用哪几份权重,各自认得什么语言、装没装。

    这是「引擎 / 模型」分开之后新长出来的一层:引擎什么语言都支持,支持范围由权重决定
    (见 ai/runtime/f5_models)。
    """
    from app.ai.runtime import f5_models

    locale = normalize_locale(request.headers.get("accept-language"))
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
def list_tts_engines(request: Request, db: DbSession, user: CurrentUser) -> list[dict]:
    """Engines the配音 UI can offer, and what each one needs from the user."""
    from app.domain.voices.engine_catalog import describe_engines

    locale = normalize_locale(request.headers.get("accept-language"))
    return [translate_fields(row, ("label", "note"), locale) for row in describe_engines(db, user.id)]


@router.post("/tts/podcast", response_model=JobOut)
def generate_podcast(body: PodcastRequest, db: DbSession, user: CurrentUser) -> Job:
    """Queue a podcast. Same permission as any other AI spend in the workspace."""
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    try:
        return voices.start_podcast(
            db,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            created_by=user.id,
            text=body.text,
            topic=body.topic,
            mode=body.mode,
            speakers=body.speakers,
            speed=body.speed,
            provider_profile_id=body.provider_profile_id,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tts/voices", response_model=list[TtsVoiceOut])
def list_tts_voices(engine: str, db: DbSession, user: CurrentUser) -> list[dict]:
    """The voices an engine can speak in, live where the account allows it (see engine_catalog)."""
    from app.domain.voices.engine_catalog import list_engine_voices

    return list_engine_voices(db, engine, user_id=user.id)


@router.post("/tts/synthesize", response_model=JobOut)
def synthesize_with_engine(body: EngineSynthesizeRequest, db: DbSession, user: CurrentUser):
    """Synthesise with a remote engine. Separate from /voices/{id}/synthesize because there is
    no Voice row to hang it off — the engine supplies the voice."""
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    try:
        return voices.start_synthesis(
            db,
            text=body.text,
            project_id=body.project_id,
            created_by=user.id,
            workspace_id=body.workspace_id,
            engine=body.engine,
            engine_voice=body.engine_voice,
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
        "source": cfg.source,
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
    from app.db.models import TtsConfig

    row = db.get(TtsConfig, "default")
    if row is None:
        row = TtsConfig(id="default")
        db.add(row)
    # **写和回读用的是同一份名单。** 分成两处的话,新加的字段会是"写进去了、没人验"的那个 ——
    # 而"没人验"正是下面那道校验要拦的东西。
    wanted = {
        "engine": body.engine,
        "python_path": body.python_path.strip(),
        "source": body.source,
        "fish_repo_dir": body.fish_repo_dir.strip(),
        "fish_model_dir": body.fish_model_dir.strip(),
    }
    # pip 镜像不在这里写 —— 它归「安装源」(见 routes/settings/system.set_install_source)。
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
def list_tts_models(request: Request, user: CurrentUser) -> list[dict]:
    locale = normalize_locale(request.headers.get("accept-language"))
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
