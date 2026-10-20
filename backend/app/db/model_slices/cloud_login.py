"""本地保存的 MosaelCloud **登录会话** —— 不是本地账号。

这张表只回答一件事:这台部署里的**这个本地用户**,在 MosaelCloud 上用邮箱/密码登进去之后,
云端发下来的那一枚会话 cookie 是什么。它不参与本地登录,不产生工作区,也不出现在任何导出里。

**只存 cookie,不存密码**:桌面端自己完成一次登录,之后所有转发都带上这一枚 cookie。cookie
值走落盘加密(见 core/secrets_at_rest)—— 它等价于云端的长效凭据;而且没有任何接口把它交回
渲染层(登录响应只回邮箱)。
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
    #: 云端会话 cookie 的**名字**。云端换名字时这里跟着换,不写死一个常量。
    cookie_name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 云端会话 cookie 的**原文**。落盘加密;只在转发时读出来拼 Cookie 头,不进日志、不进接口回包。
    cookie_value: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    #: 云端会话什么时候过期(来自 Set-Cookie 的 Max-Age)。过期的那一行不再参与转发。
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
