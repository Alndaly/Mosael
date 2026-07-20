from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import TranslateRequest, TranslateResponse
from app.domain.translate import TranslateError, translate_many

router = APIRouter(tags=["translate"])


@router.post("/translate", response_model=TranslateResponse)
def translate_texts(body: TranslateRequest, db: DbSession, user: CurrentUser) -> dict:
    """Translate a batch of strings (Google free or an AI provider). Empty strings pass through."""
    try:
        out = translate_many(
            db, list(body.texts), body.target_lang, engine=body.engine, profile_id=body.profile_id
        )
    except TranslateError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"translations": out}
