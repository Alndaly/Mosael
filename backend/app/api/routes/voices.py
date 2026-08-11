from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.audio.service import AsrError
from app.db.models import Voice
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
from app.audio import tts_daemon, tts_models, voices
from app.domain.permissions import ensure_workspace_perm, ensure_deployment_admin, ensure_workspace_access
from app.domain import tts_config

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
        raise HTTPException(status_code=404, detail="素材不存在")
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
        raise HTTPException(status_code=404, detail="音色不存在")
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
        raise HTTPException(status_code=404, detail="音色不存在")
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    try:
        return voices.recognize_reference_text(db, voice)
    except (voices.VoiceError, AsrError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/voices/{voice_id}", status_code=204)
def delete_voice(voice_id: str, db: DbSession, user: CurrentUser) -> Response:
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="音色不存在")
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    voices.delete_voice(db, voice)
    return Response(status_code=204)


@router.get("/voices/{voice_id}/sample")
def voice_sample(voice_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="音色不存在")
    ensure_workspace_access(db, user, voice.workspace_id)
    path = voices.reference_path(voice)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="参考音频缺失")
    return FileResponse(path, media_type="audio/wav")


@router.post("/voices/{voice_id}/synthesize", response_model=JobOut)
def synthesize(voice_id: str, body: SynthesizeRequest, db: DbSession, user: CurrentUser):
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="音色不存在")
    ensure_workspace_perm(db, user, voice.workspace_id, "ai")
    try:
        return voices.start_synthesis(
            db, voice_id=voice_id, text=body.text, project_id=body.project_id,
            created_by=user.id, clone_engine=body.clone_engine, speed=body.speed,
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tts/engines", response_model=list[TtsEngineChoiceOut])
def list_tts_engines(user: CurrentUser) -> list[dict]:
    """Engines the配音 UI can offer, and what each one needs from the user."""
    from app.audio.tts_providers import describe_engines

    return describe_engines()


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
    """The voices an engine can speak in, live where the account allows it.

    火山's catalogue depends on the account, and a voice used with the wrong resource family
    fails with an opaque 55000000 — so when AK/SK are configured the list is pulled from the
    account and each voice carries its family. Without them, the built-in list still works;
    it is smaller and can go stale, which is a far better failure than an empty dropdown.
    """
    from app.audio.tts_providers import EDGE_BUILTIN_VOICES, PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES, EdgeTTS, OpenAITTS
    from app.domain.providers import resolve_profile, profile_extra

    if engine == OpenAITTS.id:
        return [{"value": voice, "label": voice} for voice in OpenAITTS.VOICES]
    if engine == EdgeTTS.id:
        return [{"value": voice, "label": label} for voice, label in EDGE_BUILTIN_VOICES]
    if engine == "volcano-podcast":
        return [{"value": voice, "label": label} for voice, label in PODCAST_SPEAKERS]
    if engine != "volcano":
        return []

    # ak/sk 是密字段,跟着**我自己**那把钥匙走(见 domain/provider_credentials) ——
    # 列音色用的是我的账号,不是"这个部署里随便谁的"。
    volcano = resolve_profile(db, "volcano", user_id=user.id)
    ak, sk = str((volcano.extra if volcano else {}).get("ak") or ""), str((volcano.extra if volcano else {}).get("sk") or "")
    if ak and sk:
        from app.integrations.volc_openapi import VolcOpenAPIError, list_all_speakers

        try:
            live = list_all_speakers(ak, sk)
        except VolcOpenAPIError as exc:
            # Falling back beats failing: the user can still synthesise, and the reason the
            # live list is missing belongs in the log rather than in a broken dropdown.
            logger.info("volcano live voice list unavailable: %s", exc)
        else:
            if live:
                return [
                    {
                        "value": speaker.get("VoiceType", ""),
                        "label": speaker.get("Name") or speaker.get("VoiceType", ""),
                        "resource_id": speaker.get("ResourceID", ""),
                    }
                    for speaker in live
                    if speaker.get("VoiceType")
                ]
    return [{"value": voice, "label": label} for voice, label in VOLCANO_BUILTIN_VOICES]


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
    row.engine = body.engine
    row.python_path = body.python_path.strip()
    row.source = body.source
    row.pip_index = body.pip_index.strip()
    row.fish_repo_dir = body.fish_repo_dir.strip()
    row.fish_model_dir = body.fish_model_dir.strip()
    db.commit()
    tts_config.refresh()
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
    return tts_models.list_status()


@router.post("/tts/models/{engine_id}/download", response_model=TtsEngineOut)
def download_tts_model(engine_id: str, db: DbSession, user: CurrentUser) -> dict:
    # 下载模型是往**后端主机**上装东西 —— 部署级动作,不属于任何工作区。
    ensure_deployment_admin(db, user)
    try:
        return tts_models.start_download(engine_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知引擎") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
