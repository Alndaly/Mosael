"""账号下的设备令牌管理:签发、列出、吊销(ADR 0088 第 1 步)。

签发要一份已登录的身份 —— 桌面端在登录成功的那一刻用刚拿到的会话换令牌,随后退掉那份会话,
此后只拿令牌说话(账号接口与网关都认它)。
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from cloud.api.deps import CurrentUser, DbSession
from cloud.domain import device_tokens
from cloud.gateway.deps import CurrentDevice

router = APIRouter(tags=["device-tokens"])


class DeviceTokenIn(BaseModel):
    #: 长度在 domain 里判,报错才能说清上限。
    name: str = Field(min_length=1, max_length=512)


@router.post("/device-tokens", status_code=201)
def issue_device_token(body: DeviceTokenIn, user: CurrentUser, db: DbSession, response: Response) -> dict[str, object]:
    """签一枚设备令牌。`secret` 只在这一次响应里出现,之后谁也拿不回来。"""
    token, raw = device_tokens.issue(db, user, body.name)
    response.headers["Cache-Control"] = "no-store"
    return {"token": device_tokens.device_token_view(token), "secret": raw}


@router.get("/device-tokens")
def list_device_tokens(user: CurrentUser, db: DbSession) -> dict[str, object]:
    return {"tokens": [device_tokens.device_token_view(token) for token in device_tokens.list_for(db, user)]}


@router.delete("/device-tokens/current", status_code=204)
def revoke_this_device(device: CurrentDevice, db: DbSession) -> Response:
    """令牌吊销自己 —— 桌面端登出时用。**只认 Bearer**:浏览器没有「当前这枚设备令牌」。"""
    db.delete(device.token)
    db.commit()
    return Response(status_code=204)


@router.delete("/device-tokens/{token_id}", status_code=204)
def revoke_device_token(token_id: str, user: CurrentUser, db: DbSession) -> Response:
    device_tokens.revoke(db, user, token_id)
    return Response(status_code=204)
