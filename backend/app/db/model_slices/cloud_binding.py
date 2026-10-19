"""本地保存的 MosaelCloud 绑定 —— **不是本地账号**。

这张表只回答一件事:这台部署里的**这个本地用户**,在 MosaelCloud 上绑了谁、拿到的设备凭据是什么。
它不参与本地登录,不产生工作区,也不出现在任何导出里。云端 token 走落盘加密(见 core/secrets_at_rest),
且没有任何接口把它交回渲染层。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.secrets_at_rest import EncryptedText
from app.db.model_base import now


class CloudBinding(Base):
    __tablename__ = "cloud_bindings"

    #: 一个本地用户只绑一个云端账号。删本地账号时这行跟着走(外键 CASCADE)。
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    #: 云端账号的 id / 邮箱。**不是**本地 users 的 id —— 两套身份各认各的。
    cloud_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    #: 云端那台设备的 id,给出「云端撤销」时对得上;本地解绑只删这一行。
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 设备凭据原文。落盘加密,读取只发生在绑定完成与(将来的)云端调用,不进日志、不进接口回包。
    token: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
