from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import JobOut, SynthesizeRequest, TtsEngineOut, VoiceFromSpeakerRequest, VoiceOut
from app.audio import tts_models, voices
from app.core.permissions import ensure_workspace_access

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
    ensure_workspace_access(db, user, workspace_id)
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
    ensure_workspace_access(db, user, asset.workspace_id)
    try:
        voice = voices.create_from_speaker(
            db, workspace_id=asset.workspace_id, asset_id=body.asset_id, speaker=body.speaker, name=body.name
        )
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _voice_out(voice)


@router.delete("/voices/{voice_id}", status_code=204)
def delete_voice(voice_id: str, db: DbSession, user: CurrentUser) -> Response:
    voice = voices.get_voice(db, voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="音色不存在")
    ensure_workspace_access(db, user, voice.workspace_id)
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
    ensure_workspace_access(db, user, voice.workspace_id)
    try:
        return voices.start_synthesis(db, voice_id=voice_id, text=body.text, project_id=body.project_id)
    except voices.VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tts/models", response_model=list[TtsEngineOut])
def list_tts_models(user: CurrentUser) -> list[dict]:
    return tts_models.list_status()


@router.post("/tts/models/{engine_id}/download", response_model=TtsEngineOut)
def download_tts_model(engine_id: str, user: CurrentUser) -> dict:
    try:
        return tts_models.start_download(engine_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知引擎") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
