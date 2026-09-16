from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.ai.runtime import separation_models
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import SeparationEngineOut
from app.core.i18n import normalize_locale, translate_fields
from app.domain.permissions import ensure_deployment_admin

router = APIRouter(tags=["separation"])


@router.get("/separation/engines", response_model=list[SeparationEngineOut])
def list_separation_engines(request: Request, user: CurrentUser) -> list[dict]:
    """人声/伴奏分离引擎,以及它们装没装。"""
    # 领域里存的是 key,**在出口翻译**(见 core/i18n)——领域数据不必知道语言。
    locale = normalize_locale(request.headers.get("accept-language"))
    return [translate_fields(row, ("label", "message"), locale) for row in separation_models.list_status()]


@router.post("/separation/engines/{engine}/install", response_model=SeparationEngineOut)
def install_separation_engine(engine: str, db: DbSession, user: CurrentUser) -> dict:
    """把这个引擎的运行环境装上(建 venv + 装依赖)。

    和下载转写模型同一条:往**后端主机**上装东西是部署级动作,不属于任何工作区。
    """
    ensure_deployment_admin(db, user)
    try:
        return separation_models.start_install(engine)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知的分离引擎") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
