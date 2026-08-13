from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AsrModelOut
from app.domain.permissions import ensure_deployment_admin
from app.audio import asr_models
from app.core.i18n import normalize_locale, translate_fields

router = APIRouter(tags=["asr"])


@router.get("/asr/models", response_model=list[AsrModelOut])
def list_asr_models(request: Request, user: CurrentUser) -> list[dict]:
    """Downloadable transcription models with install/download status."""
    # 目录里存的是 key,**在出口翻译**(见 core/i18n):领域数据不必知道语言。
    locale = normalize_locale(request.headers.get("accept-language"))
    return [translate_fields(row, ("label", "detail", "message"), locale) for row in asr_models.list_status()]


@router.post("/asr/models/{model_id}/download", response_model=AsrModelOut)
def download_asr_model(model_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Deliberately (pre-)download a model in the external ASR interpreter."""
    # 下载模型是往**后端主机**上装东西 —— 部署级动作,不属于任何工作区。
    ensure_deployment_admin(db, user)
    try:
        return asr_models.start_download(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知模型") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
