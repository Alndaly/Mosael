"""本地保存的 MosaelCloud **登录** —— 不是本地账号。

这张表只回答一件事:这台部署里的**这个本地用户**登进 MosaelCloud 之后,Cloud 签给这台桌面端的那一枚
**设备令牌**是什么(ADR 0088 第 1 步)。它不参与本地登录,不产生工作区,也不出现在任何导出里。

**只存令牌,不存密码、不存 cookie**:登录那一跳拿到的会话 cookie 立刻换成令牌、随即退掉。令牌值走
落盘加密(见 core/secrets_at_rest)—— 它是这台机器在云端的长效凭据;没有任何接口把它交回渲染层
(登录响应只回邮箱)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.secrets_at_rest import EncryptedText
from app.db.model_base import now


class CloudLogin(Base):
    __tablename__ = "cloud_login"

    #: 一个本地用户只登一个云端账号。删本地账号时这行跟着走(外键 CASCADE)。
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    #: 云端账号的邮箱。登录响应只回它;它也是界面上「你现在登的是谁」的唯一来源。
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    #: 这枚令牌在 Cloud 上的 id —— 用户在官网「我的设备」里看到、吊销的就是它。
    device_token_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 设备令牌原文(`mct_…`)。落盘加密;只在转发时读出来拼 Bearer 头,不进日志、不进接口回包。
    device_token: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
