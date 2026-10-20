"""桌面端登录 MosaelCloud 的请求 / 响应体(见 domain/cloud_binding)。

**响应里没有 cookie**:登录成功只回 `{email}`;会话 cookie 落在本地 `cloud_login` 的加密列里,
渲染层从头到尾看不到它。
"""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.base import ApiModel


class CloudLoginIn(ApiModel):
    """邮箱 + 密码。**这一份只存在这一次请求里**,不落库、不进日志。"""

    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class CloudEmailIn(ApiModel):
    """验证码登录的第一步:只要邮箱。"""

    email: str = Field(min_length=1, max_length=320)


class CloudCodeIn(ApiModel):
    """验证码登录的第二步:邮箱 + 6 位码。"""

    email: str = Field(min_length=1, max_length=320)
    code: str = Field(default="", max_length=12)


class CloudSessionOut(ApiModel):
    """「现在登的是谁」 —— 只有邮箱。cookie 值**不在**这里。"""

    email: str
