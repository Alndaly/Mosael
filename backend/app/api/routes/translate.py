from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import TranslateRequest, TranslateResponse
from app.core.permissions import ensure_workspace_member
from app.domain.translate import TranslateError, translate_many

router = APIRouter(tags=["translate"])


@router.post("/translate", response_model=TranslateResponse)
def translate_texts(body: TranslateRequest, db: DbSession, user: CurrentUser) -> dict:
    """Translate a batch of strings (Google free or an AI provider). Empty strings pass through."""
    # ensure_workspace_member 而不是 ensure_workspace_access:翻译不改这个工作区的任何数据,
    # 查看者也该能用。过闸门的同时把工作区绑进上下文,AI 翻译的用量据此归属。
    ensure_workspace_member(db, user, body.workspace_id)
    try:
        out = translate_many(
            db, list(body.texts), body.target_lang, engine=body.engine, profile_id=body.profile_id
        )
    except TranslateError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # 翻译本身不改这个工作区的数据,但 AI 引擎记了一笔账 —— 记账跟着调用方的事务走
    # (见 domain/usage.billable 里为什么必须这样),所以只读接口也得落一次盘。
    db.commit()
    return {"translations": out}
