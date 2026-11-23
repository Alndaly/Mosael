from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import TranslateRequest, TranslateResponse
from app.domain.translate import translate_for_member

router = APIRouter(tags=["translate"])


@router.post("/translate", response_model=TranslateResponse)
def translate_texts(body: TranslateRequest, db: DbSession, user: CurrentUser) -> dict:
    """翻一批文字,用哪一家见 domain/translate(能力表)。空串原样回。"""
    out = translate_for_member(
        db, user, body.workspace_id, list(body.texts), body.target_lang, engine=body.engine, profile_id=body.profile_id
    )
    # 翻译本身不改这个工作区的数据,但 AI 引擎记了一笔账 —— 记账跟着调用方的事务走
    # (见 domain/billing/usage.billable 里为什么必须这样),所以只读接口也得落一次盘。
    db.commit()
    return {"translations": out}
