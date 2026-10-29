"""设备令牌:签发、列出、吊销、按原文认人(ADR 0088 第 1 步)。

- 原文 = `mct_` + 256 位随机串;**只在签发响应里出现一次**,库里只存 sha256。
  前缀让它在日志、密钥扫描里一眼认得出是 MosaelCloud 的令牌。
- 没有过期时间:它是一台机器的长期凭据,失效靠吊销(桌面端登出、官网「我的设备」里删、删号级联)。
- `last_used_at` 按分钟粒度写:网关每次调用都要认令牌,不能每次都写一次库。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud.errors import CloudError
from cloud.models import CloudDeviceToken, CloudUser, now
from cloud.security import new_token, token_digest

TOKEN_PREFIX = "mct_"
NAME_MAX = 80
#: 同一枚令牌在这个间隔内再次使用,不再刷新 `last_used_at`。
TOUCH_INTERVAL = timedelta(minutes=1)


def device_token_view(token: CloudDeviceToken) -> dict[str, object]:
    """对外形状。**没有** `token_hash`,更没有原文。"""
    return {
        "id": token.id,
        "name": token.name,
        "created_at": token.created_at.isoformat(),
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
    }


def issue(db: Session, user: CloudUser, name: str) -> tuple[CloudDeviceToken, str]:
    """签一枚新令牌,返回 `(行, 原文)`。一台设备重复登录就多一枚 —— 旧的由桌面端登出时自己吊销。"""
    cleaned = name.strip()
    if not cleaned or len(cleaned) > NAME_MAX:
        raise CloudError(400, "device_name_invalid", max=NAME_MAX)
    raw = TOKEN_PREFIX + new_token()
    token = CloudDeviceToken(user_id=user.id, token_hash=token_digest(raw), name=cleaned)
    db.add(token)
    db.commit()
    return token, raw


def list_for(db: Session, user: CloudUser) -> list[CloudDeviceToken]:
    return list(
        db.scalars(
            select(CloudDeviceToken)
            .where(CloudDeviceToken.user_id == user.id)
            .order_by(CloudDeviceToken.created_at.desc())
        )
    )


def revoke(db: Session, user: CloudUser, token_id: str) -> None:
    """吊销自己的一枚令牌。别人的令牌与不存在的一律 404 —— 不让 id 成为探测手段。"""
    token = db.get(CloudDeviceToken, token_id)
    if token is None or token.user_id != user.id:
        raise CloudError(404, "device_token_not_found")
    db.delete(token)
    db.commit()


def authenticate(db: Session, raw: str, *, at: datetime | None = None) -> CloudDeviceToken | None:
    """原文 → 令牌行;认不出就是 None。顺手按分钟粒度刷新 `last_used_at`。"""
    if not raw.startswith(TOKEN_PREFIX):
        return None
    token = db.scalar(select(CloudDeviceToken).where(CloudDeviceToken.token_hash == token_digest(raw)))
    if token is None:
        return None
    moment = at or now()
    if token.last_used_at is None or moment - token.last_used_at >= TOUCH_INTERVAL:
        token.last_used_at = moment
        db.commit()
    return token
