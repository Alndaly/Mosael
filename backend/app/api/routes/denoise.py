from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser
from app.api.schemas import DenoiseEngineOut
from app.core.i18n import normalize_locale, translate_fields
from app.domain.denoise import list_engines

router = APIRouter(tags=["denoise"])


@router.get("/denoise/engines", response_model=list[DenoiseEngineOut])
def list_denoise_engines(request: Request, user: CurrentUser) -> list[dict]:
    """降噪引擎,以及现在能不能用。没有安装这一步 —— 内置的随应用带着,人声提取借的是分离引擎。"""
    locale = normalize_locale(request.headers.get("accept-language"))
    return [translate_fields(row, ("label",), locale) for row in list_engines()]
