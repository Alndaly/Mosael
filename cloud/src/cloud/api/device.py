"""设备码绑定契约(这一期只做"能绑",不做任何云端业务能力)。

完整时序:

    desktop                      website (signed in)                cloud
      POST /device/code  ─────────────────────────────────────────▶  生成 user_code + device_code
     显示 user_code          GET /account?user_code=…  ───────────▶  用户看到确认框
                             POST /device/approve {user_code}  ──▶  记下是谁确认的
      POST /device/token {device_code}  ─────────────────────────▶  待确认: 428;已确认: 发凭据(只这一次)

`device_code` 只出现在桌面端手里,`user_code` 只给人看。两者都只以哈希落盘(`device_code`),
或者以不可枚举的短码落盘(`user_code`,确认后即作废)。
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

from cloud.api.deps import CurrentConfig, CurrentDevice, CurrentUser, DbSession
from cloud.errors import CloudError
from cloud.models import CloudDevice, CloudDeviceCode, now
from cloud.security import new_token, new_user_code, normalize_user_code, token_digest

router = APIRouter(tags=["devices"])


class DeviceCodeIn(BaseModel):
    device_name: str = Field(default="", max_length=120)


class DeviceApproveIn(BaseModel):
    user_code: str = Field(min_length=1, max_length=32)


class DeviceTokenIn(BaseModel):
    device_code: str = Field(min_length=1, max_length=512)


def device_out(device: CloudDevice) -> dict[str, object]:
    return {
        "id": device.id,
        "name": device.name,
        "created_at": device.created_at.isoformat(),
    }


@router.post("/device/code")
def create_device_code(body: DeviceCodeIn, db: DbSession, config: CurrentConfig) -> dict[str, object]:
    """桌面端发起绑定。不需要登录 —— 登录的是接下来在官网上确认的那个人。"""
    device_code = new_token()
    user_code = ""
    for _ in range(10):
        candidate = new_user_code()
        if db.scalar(select(CloudDeviceCode.id).where(CloudDeviceCode.user_code == candidate)) is None:
            user_code = candidate
            break
    if not user_code:  # pragma: no cover - 8 位码撞十次,概率可以忽略
        raise CloudError(500, "internal_error")

    db.add(
        CloudDeviceCode(
            user_code=user_code,
            device_code_hash=token_digest(device_code),
            device_name=body.device_name.strip(),
            expires_at=now() + timedelta(seconds=config.device_code_ttl_seconds),
            status="pending",
        )
    )
    db.commit()

    verification_uri = f"{config.public_url}/en/account"
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": verification_uri,
        "verification_uri_complete": f"{verification_uri}?user_code={user_code}",
        "expires_in": config.device_code_ttl_seconds,
        "interval": config.device_poll_interval_seconds,
    }


@router.post("/device/approve", status_code=204)
def approve_device(body: DeviceApproveIn, user: CurrentUser, db: DbSession) -> Response:
    """已登录的官网用户确认"允许这台设备使用我的 MosaelCloud 账号"。"""
    code = normalize_user_code(body.user_code)
    grant = db.scalar(select(CloudDeviceCode).where(CloudDeviceCode.user_code == code)) if code else None
    if grant is None:
        raise CloudError(404, "user_code_invalid")
    if grant.consumed_at is not None:
        raise CloudError(410, "user_code_used")
    if grant.expires_at <= now():
        raise CloudError(410, "device_code_expired")
    if grant.status == "approved":
        # 同一个人再点一次是幂等的;换个人来抢就是冲突。
        if grant.user_id == user.id:
            return Response(status_code=204)
        raise CloudError(409, "user_code_used")

    grant.status = "approved"
    grant.user_id = user.id
    grant.approved_at = now()
    db.commit()
    return Response(status_code=204)


@router.post("/device/token")
def exchange_device_code(body: DeviceTokenIn, db: DbSession) -> dict[str, object]:
    """桌面端轮询。未确认 428;成功时给**一次性**凭据,同一个 device_code 不能再换第二次。"""
    grant = db.scalar(
        select(CloudDeviceCode).where(CloudDeviceCode.device_code_hash == token_digest(body.device_code))
    )
    if grant is None:
        raise CloudError(404, "device_code_invalid")
    if grant.consumed_at is not None:
        raise CloudError(410, "device_code_used")
    if grant.expires_at <= now():
        raise CloudError(410, "device_code_expired")
    if grant.status != "approved" or grant.user_id is None:
        raise CloudError(428, "authorization_pending")
    user = grant.user_id

    # 原子地把 approved → consumed:两个并发的轮询只有一个能换到凭据。
    consumed = db.execute(
        update(CloudDeviceCode)
        .where(CloudDeviceCode.id == grant.id, CloudDeviceCode.status == "approved")
        .values(status="consumed", consumed_at=now())
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise CloudError(410, "device_code_used")

    raw = new_token()
    device = CloudDevice(
        user_id=user,
        name=grant.device_name,
        token_hash=token_digest(raw),
    )
    db.add(device)
    db.commit()

    from cloud.models import CloudUser

    account = db.get(CloudUser, user)
    return {
        "status": "approved",
        "credential": {
            "device_id": device.id,
            "token": raw,
            "account": {"id": user, "email": account.email if account else ""},
        },
    }


@router.get("/devices")
def list_devices(user: CurrentUser, db: DbSession) -> dict[str, object]:
    rows = db.scalars(
        select(CloudDevice).where(CloudDevice.user_id == user.id).order_by(CloudDevice.created_at.desc())
    ).all()
    return {"devices": [device_out(device) for device in rows]}


@router.delete("/device/{device_id}", status_code=204)
def revoke_device(device_id: str, user: CurrentUser, db: DbSession) -> Response:
    """云端撤销一台设备。删行即失效 —— 凭据的查找就是按哈希查这张表。"""
    removed = db.execute(
        delete(CloudDevice).where(CloudDevice.id == device_id, CloudDevice.user_id == user.id)
    )
    if removed.rowcount == 0:
        raise CloudError(404, "device_not_found")
    db.commit()
    return Response(status_code=204)


@router.get("/device/me")
def device_me(pair: CurrentDevice) -> dict[str, object]:
    device, user = pair
    return {"device": device_out(device), "account": {"id": user.id, "email": user.email}}
