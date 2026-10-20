"""MosaelCloud 的数据形状。

**这是另一套账号体系,不是本地 Mosael 的 `users`。** 表名统一带 `cloud_` 前缀,是为了让"这份库
属于谁"在 `sqlite3 .tables` 的第一眼就看得出来,也为了让一条"Cloud 库里不许出现 users 表"的测试
有东西可断言。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cloud.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    """朴素 UTC —— 和仓库其它服务一致,避免 SQLite 里两种时区语义混着存。"""
    return datetime.now(UTC).replace(tzinfo=None)


class CloudUser(Base):
    """一个 MosaelCloud 账号。只有邮箱和密码;**没有**本地账号的用户名、工作区、部署管理员。"""

    __tablename__ = "cloud_users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 统一存小写。唯一索引保证"一个邮箱一个账号",并发注册靠数据库兜底。
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    #: argon2id 哈希(见 security.hash_password)。绝不存明文。
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 注册时要先验邮箱验证码,验过即写这个时间;更早的账号可能是空,不做回填。
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudSession(Base):
    """浏览器里的一次登录。**只存令牌的 sha256**,原始令牌只出现在 Set-Cookie 那一次。"""

    __tablename__ = "cloud_sessions"
    __table_args__ = (Index("idx_cloud_sessions_user", "user_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CloudEmailCode(Base):
    """一次邮箱验证码。**只存哈希**;6 位明文只出现在发出去的那封邮件里。

    码不绑用户:注册时用户还不存在,登录时邮箱可能根本没注册(枚举防护要求两条路径的响应
    一致,所以未注册邮箱也会留一行 —— 它永远收不到码,也就永远用不了)。
    """

    __tablename__ = "cloud_email_codes"
    __table_args__ = (
        Index("idx_cloud_email_codes_lookup", "email", "purpose", "created_at"),
        Index("idx_cloud_email_codes_ip", "request_ip", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    #: `signup` / `login`。同一个验证码不能跨用途使用。
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 验错次数。到上限即作废,逼用户重新发码。
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 请求来源 IP,只用于"每 IP 每小时"限流;它和码一起过期,不是身份,也不进任何响应。
    request_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class CloudDeviceCode(Base):
    """一次设备码绑定。桌面端拿 `device_code`,用户看 `user_code`,官网确认后这里记下是谁。"""

    __tablename__ = "cloud_device_codes"
    __table_args__ = (
        Index("idx_cloud_device_codes_user", "user_id"),
        Index("idx_cloud_device_codes_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 给人念的 8 位码,形如 `ABCD-EFGH`。
    user_code: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    #: 给桌面端轮询的 256 位随机串;只存哈希。
    device_code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: 确认的人。确认之前为空;账号删掉时跟着级联消失。
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=True
    )
    #: pending → approved → consumed。没有 denied:这一期官网只提供"允许",不提供"拒绝"。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class CloudDevice(Base):
    """一台已经绑定的设备 —— 桌面端存着的那份云端凭据在这里只存哈希。

    **凭据是长期有效的**(撤销之前一直能用),不是短期 access + refresh:这一期桌面端只需要
    "把绑定结果存下来",而 refresh 轮换要配一套客户端刷新逻辑,本期用不上。代价是它比短期令牌
    更值钱,所以:随机 256 位、只存哈希、按人可撤销、删号即级联删除。
    """

    __tablename__ = "cloud_devices"
    __table_args__ = (Index("idx_cloud_devices_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
