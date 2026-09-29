from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import DenoiseEngineOut
from app.core.i18n import get_current_locale, tr, translate_fields
from app.domain.assets.denoise import install_engine, list_engines
from app.domain.permissions import ensure_deployment_admin

router = APIRouter(tags=["denoise"])

#: 引擎清单里是 i18n key 的那几栏(在出口翻译,领域数据不必知道语言)。
_TRANSLATED = ("label", "description", "setup_hint", "message")


@router.get("/denoise/engines", response_model=list[DenoiseEngineOut])
def list_denoise_engines(db: DbSession, user: CurrentUser) -> list[dict]:
    """降噪的候选(内置引擎和这个人配好的降噪插件,ADR 0032),以及现在能不能用、要不要装。"""
    locale = get_current_locale()
    return [translate_fields(row, _TRANSLATED, locale) for row in list_engines(db, user.id)]


@router.post("/denoise/engines/{engine}/install", response_model=DenoiseEngineOut)
def install_denoise_engine(engine: str, db: DbSession, user: CurrentUser) -> dict:
    """下载并装上这个引擎(后台跑)。

    往**后端主机**上放一个可执行文件是部署级动作,要部署管理员 —— 和装分离引擎、下转写模型同一条。
    """
    ensure_deployment_admin(db, user)
    try:
        row = install_engine(db, user.id, engine)
    except (KeyError, StopIteration) as exc:
        raise HTTPException(status_code=404, detail=tr("routeErr_denoiseEngineNotInstallable")) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return translate_fields(row, _TRANSLATED, get_current_locale())
