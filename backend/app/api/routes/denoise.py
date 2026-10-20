from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import DenoiseDefaultUpdate, DenoiseEngineOut
from app.core.i18n import get_current_locale, tr, translate_fields
from app.domain import denoise_defaults
from app.domain.assets.denoise import install_engine, list_engines
from app.domain.permissions import ensure_deployment_admin

router = APIRouter(tags=["denoise"])

#: 引擎清单里是 i18n key 的那几栏(在出口翻译,领域数据不必知道语言)。
_TRANSLATED = ("label", "description", "setup_hint", "message")


def _status_rows(db, user) -> list[dict]:
    """候选的每一行 + 「是不是这台机器的默认」。

    默认只有一个,判据在 domain/denoise_defaults(有效值的唯一解析点)。**这里加的是部署默认,
    不是"这次会用谁"** —— 后者还要叠上每个人自己在「能力提供方」里的选择,界面不在这里猜。
    """
    default = denoise_defaults.default_engine(db)
    rows = list_engines(db, user.id)
    for row in rows:
        row["is_default"] = bool(default) and row["engine"] == default
    return rows


@router.get("/denoise/engines", response_model=list[DenoiseEngineOut])
def list_denoise_engines(db: DbSession, user: CurrentUser) -> list[dict]:
    """降噪的候选(内置引擎和这个人配好的降噪插件,ADR 0032),以及现在能不能用、要不要装。"""
    locale = get_current_locale()
    return [translate_fields(row, _TRANSLATED, locale) for row in _status_rows(db, user)]


@router.put("/settings/denoise", response_model=DenoiseEngineOut)
def set_default_denoise_engine(body: DenoiseDefaultUpdate, db: DbSession, user: CurrentUser) -> dict:
    """把这台机器的默认降噪引擎设成这一种。

    **只许设已经装好的**(`domain/denoise_defaults.set_default_engine`):没装的设成默认,"默认"
    就是一句空话 —— 下一次降噪照样得先下载。和装引擎同一道门(往这台机器上放东西、决定它默认用
    哪一个,对所有人都是一件部署级的事)。

    回的是改完之后的那一行;界面据此**再向后端问一次**整张列表,而不是自己把别的行改掉。
    """
    ensure_deployment_admin(db, user)
    try:
        engine = denoise_defaults.set_default_engine(db, body.engine)
    except denoise_defaults.UnknownDenoiseEngine as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (denoise_defaults.DenoiseEngineNotInstalled, denoise_defaults.DenoiseEngineNotReady) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    locale = get_current_locale()
    row = next(one for one in _status_rows(db, user) if one["engine"] == engine)
    return translate_fields(row, _TRANSLATED, locale)


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
