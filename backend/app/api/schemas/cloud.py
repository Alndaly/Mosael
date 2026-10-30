"""桌面端登录 MosaelCloud 的请求 / 响应体(见 domain/cloud_binding)。

**响应里没有凭据**:登录成功只回 `{email}`;设备令牌落在本地 `cloud_login` 的加密列里,
渲染层从头到尾看不到它。
"""

from __future__ import annotations

from typing import Literal

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


class CloudPhoneIn(ApiModel):
    """短信登录第一步:手机号。"""

    phone: str = Field(min_length=1, max_length=32)


class CloudPhoneCodeIn(CloudPhoneIn):
    """短信登录第二步:手机号 + 6 位码。"""

    code: str = Field(default="", max_length=12)


class CloudPhoneLoginIn(CloudPhoneIn):
    """手机号 + 密码登录。和邮箱密码走同一条会话落库路径。"""

    password: str = Field(min_length=1, max_length=512)


class CloudSessionOut(ApiModel):
    """「现在登的是谁」 —— 登录标识(邮箱或 E.164 手机号)。设备令牌**不在**这里。"""

    email: str
    has_password: bool = False


class CloudPasswordIn(ApiModel):
    """设置 / 修改云端密码。第一次设置没有旧密码;已有密码时必须给当前密码。"""

    current_password: str = Field(default="", max_length=512)
    new_password: str = Field(min_length=1, max_length=512)


class CloudConnectionSyncOut(ApiModel):
    """「Mosael Cloud」连接对齐之后:哪一条连接、网关目录里有几个模型。"""

    profile_id: str
    models: int


class CloudOrderIn(ApiModel):
    """在线购买下单(ADR 0088 第 3 步):哪个套餐(slug)、哪个渠道。原样转给 Cloud,由它校验。"""

    plan: str = Field(min_length=1, max_length=64)
    channel: Literal["alipay", "wechat"]
