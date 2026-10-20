"""「绑定 MosaelCloud」和社区分享只读反代的本地入口。

云端凭据只走这里和本地库;渲染层拿不到 token。绑定接口只做四件事:发起、完成、看状态、解绑。
社区分享的那三条只是**只读转发**:桌面端打的是本机后端,而 Cloud 只接受官网同源、不开 CORS ——
没有这一层,真机上社区分享永远打不开。**写接口(发布 / 评论 / 点赞)不转发**:它们要第一方
会话,桌面端没有,转了只会 401。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.cloud import (
    CloudBindingCompleteIn,
    CloudBindingCompleteOut,
    CloudBindingOut,
    CloudBindingRemovedOut,
    CloudBindingStartIn,
    CloudBindingStartOut,
)
from app.domain import cloud_binding

router = APIRouter(tags=["cloud"])

#: 社区分享 id 的形状(外部输入):Cloud 的 id 是短 token,这里只收一个路径段能装下的字符。
#: **先过这一道再拼进 URL** —— 不把用户给的东西直接接到云地址后面。
SHARE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
ShareId = Annotated[str, Path(pattern=SHARE_ID_PATTERN, description="MosaelCloud 社区分享 id")]

#: 这三句和绑定入口用同一套话:同一个部署没接 Cloud、连不上 Cloud 时,界面看到的是同一句话。
_CLOUD_UNREACHABLE = {"code": "cloud_unreachable", "message": "Can't reach MosaelCloud. Check the network and try again."}
_CLOUD_TIMEOUT = {"code": "cloud_timeout", "message": "MosaelCloud took too long to answer. Try again in a moment."}
_CLOUD_UPSTREAM_ERROR = {
    "code": "cloud_upstream_error",
    "message": "MosaelCloud returned a server error. Try again in a moment.",
}


def _http_error(error: cloud_binding.CloudBindingError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message})


def _fail(error: cloud_binding.CloudBindingError) -> None:
    raise _http_error(error)


@router.post("/cloud/binding/start", response_model=CloudBindingStartOut)
def start_binding(body: CloudBindingStartIn, user: CurrentUser) -> dict:
    try:
        return cloud_binding.start(user, body.device_name)
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(status_code=503, detail=_CLOUD_UNREACHABLE) from exc
    except cloud_binding.CloudBindingError as exc:
        _fail(exc)


@router.post("/cloud/binding/complete", response_model=CloudBindingCompleteOut)
def complete_binding(body: CloudBindingCompleteIn, user: CurrentUser, db: Tx) -> dict:
    try:
        return cloud_binding.complete(db, user, body.device_code)
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(status_code=503, detail=_CLOUD_UNREACHABLE) from exc
    except cloud_binding.CloudBindingError as exc:
        _fail(exc)


@router.get("/cloud/binding", response_model=CloudBindingOut)
def get_binding(user: CurrentUser, db: DbSession) -> dict:
    return cloud_binding.status_of(db, user)


@router.delete("/cloud/binding", response_model=CloudBindingRemovedOut)
def remove_binding(user: CurrentUser, db: Tx) -> dict:
    return {"removed": cloud_binding.remove(db, user)}


# ---------------------------------------------------------------- 社区分享(只读反代)


def _relay(status: int, body: dict | list) -> JSONResponse:
    """把 Cloud 的回答**原样**交出去:状态码是它的,JSON 也逐字段是它的。

    4xx(404 / 413 / 422)尤其不翻译 ——「这份分享不存在」是界面照着 404 说的话;后端替它翻译,
    两边的码和文案就会各说一套。5xx 是唯一的例外:那是 Cloud 自己的故障,对本地调用方是 502。
    """
    if status >= 500:
        raise HTTPException(status_code=502, detail={**_CLOUD_UPSTREAM_ERROR, "upstream_status": status})
    return JSONResponse(content=body, status_code=status)


def _forward(call: Callable[[], tuple[int, dict | list]]) -> JSONResponse:
    """一次转发的统一出口:慢 → 504,到不了 → 503,没配 → 503(和绑定入口同一句),5xx → 502。"""
    try:
        status, body = call()
    except cloud_binding.CloudTimeout as exc:
        raise HTTPException(status_code=504, detail=_CLOUD_TIMEOUT) from exc
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(status_code=503, detail=_CLOUD_UNREACHABLE) from exc
    except cloud_binding.CloudBindingError as exc:
        raise _http_error(exc) from exc
    return _relay(status, body)


@router.get("/cloud/v1/shares/{share_id}")
def get_community_share(share_id: ShareId) -> JSONResponse:
    """分享详情。**公开读**:不转发本地会话,云端那侧按游客认。"""
    return _forward(lambda: cloud_binding.get_json(f"/shares/{share_id}"))


@router.get("/cloud/v1/shares/{share_id}/payload")
def get_community_share_payload(share_id: ShareId) -> JSONResponse:
    """分享内容本体。响应就是 Cloud 的 `{"payload": …}`,这里不拆、不校验。"""
    return _forward(lambda: cloud_binding.get_json(f"/shares/{share_id}/payload"))


@router.post("/cloud/v1/shares/{share_id}/download")
def download_community_share(share_id: ShareId) -> JSONResponse:
    """下载一次。Cloud 那侧会**把 downloads +1**,所以方法必须是 POST —— 别顺手改成 GET。"""
    return _forward(lambda: cloud_binding.post_json(f"/shares/{share_id}/download", {}))
