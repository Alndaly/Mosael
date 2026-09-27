"""社区账号(ADR 0026):这台后端上**每个人**连着的那个社区账号,和画板分享在本机的记忆。

两张表都归 `domain/community` 写(见 domain/ownership)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.secrets_at_rest import EncryptedText
from app.db.model_base import now


class CommunityAccount(Base):
    """一个人连着的社区账号:设备授权换来的**刷新令牌**,加上显示用的 @handle。

    刷新令牌和服务商密钥住在同一种列类型里(落盘加密,见 core/secrets_at_rest)。它**只进不出**:
    不写日志、不回给前端,只有 `domain/community/accounts` 拿它去换访问令牌。访问令牌只在内存里。

    一人一行(主键就是 user_id):一个人在这台后端上只连一个社区账号。换号 = 先断开再连。
    """

    __tablename__ = "community_accounts"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    #: 社区服务那一侧的用户 id / 公开用户名 / 昵称。给「已连接为 @handle」看,不参与任何判断。
    community_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    handle: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: 连的是哪一个社区(部署设置里的 community_url)。管理员换了地址,旧令牌对新地址无效 —— 按不认识处理。
    origin: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    refresh_token: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class BoardShare(Base):
    """一张画板分享出去之后,本机记住的那条链接。

    快照在社区服务上(不可变、按版本),这里只记「链接是什么、现在第几版、标题和可见性」——
    分享面板一打开就能说出「已分享 · 第 3 版」,再点「更新分享」时沿用同一条链接(服务端按画板的
    `board_key` 认出是同一张)。撤回之后这一行删掉。
    """

    __tablename__ = "board_shares"

    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    #: `unlisted`(知道链接才能看)/ `public`(出现在作者主页)。
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="unlisted")
    #: 谁分享的(本机用户)。换一个人再分享,链接跟着他的社区账号走。
    shared_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
