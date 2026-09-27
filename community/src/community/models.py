"""社区服务的表。形状的任何变化都要配一条 Alembic 迁移(tests/test_migrations.py 盯着两边一致)。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from community.db import Base, JSONType, UTCDateTime, new_id, utcnow

# ---------------- 账号 ----------------

ROLE_USER = "user"
ROLE_MODERATOR = "moderator"
ROLE_ADMIN = "admin"
ROLES = (ROLE_USER, ROLE_MODERATOR, ROLE_ADMIN)

STATUS_ACTIVE = "active"
STATUS_BANNED = "banned"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    #: 公开的用户名,小写存,唯一。
    handle: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    #: 头像是一个上传过的文件(按内容哈希)。
    avatar_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: E.164。
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_USER)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE)
    #: 官方条目的作者(种子数据导入的那一个)。
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    #: handle 只能改一次:改过的记下时间。
    handle_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: 同意的是哪一版协议、什么时候同意的(国内上线要求留痕)。
    terms_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    terms_agreed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SmsCode(Base):
    """发出去的每一条验证码。**只存哈希**;同时是短信限速的账本(按号码、按 IP 数条数)。"""

    __tablename__ = "sms_codes"
    __table_args__ = (
        Index("ix_sms_codes_phone_created", "phone", "created_at"),
        Index("ix_sms_codes_ip_created", "ip", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(64), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RateCounter(Base):
    """数据库里的一个限速计数器(密码登录失败按账号、按 IP 两个维度)。多个进程共用同一个库,数得准。"""

    __tablename__ = "rate_counters"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AuthSession(Base):
    """一次登录。刷新令牌属于它;吊销它 = 这台设备下线。"""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: `web`(刷新令牌在 cookie 里)或 `app`(设备授权,刷新令牌在桌面端的加密凭据里)。
    kind: Mapped[str] = mapped_column(String(8))
    device_name: Mapped[str] = mapped_column(String(120), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    #: 滑动窗口的到期时间(每刷新一次往后推,但不超过绝对上限)。
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    absolute_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class RefreshToken(Base):
    """刷新令牌。库里只有哈希;用过一次就换成下一个(successor)。"""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    #: 和它一起发出去的那张访问令牌的签发时间与角色 —— 宽限期里要原样再给一遍同一对令牌。
    pair_iat: Mapped[int] = mapped_column(BigInteger)
    pair_role: Mapped[str] = mapped_column(String(16))
    rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    successor_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class DeviceAuthorization(Base):
    """设备授权(RFC 8628):桌面端拿设备码轮询,用户在网页上用用户码确认。"""

    __tablename__ = "device_authorizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    device_code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_code: Mapped[str] = mapped_column(String(9), unique=True)
    client_name: Mapped[str] = mapped_column(String(120), default="")
    #: pending → approved → consumed;或 denied。
    status: Mapped[str] = mapped_column(String(16), default="pending")
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    interval: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_polled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


# ---------------- 工作流与插件 ----------------

KIND_WORKFLOW = "workflow"
KIND_PLUGIN = "plugin"
ITEM_KINDS = (KIND_WORKFLOW, KIND_PLUGIN)

VERSION_PENDING = "pending"
VERSION_APPROVED = "approved"
VERSION_REJECTED = "rejected"


class Item(Base):
    """社区上的一项:一个工作流或一个插件。版本在 ItemVersion 里。

    `title` / `summary` 是 JSON:用户提交的是一个字符串,官方条目是 `{"zh": …, "en": …}` ——
    和插件索引同一条约定,原样交给读的一方按语言挑。
    """

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("kind", "slug"),
        Index("ix_items_kind_created", "kind", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16))
    slug: Mapped[str] = mapped_column(String(160))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: 插件的清单 id —— 第一个提交它的人占有它。
    plugin_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    title: Mapped[Any] = mapped_column(JSONType)
    summary: Mapped[Any] = mapped_column(JSONType)
    description: Mapped[str] = mapped_column(Text, default="")
    cover_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    #: 当前公开的那一版(工作流发布即上架;插件要审核通过)。为空 = 还没有公开的版本。
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 当前版本的几样摘要,列表页用(不必每行都去读版本)。
    version_label: Mapped[str] = mapped_column(String(64), default="")
    has_code: Mapped[bool] = mapped_column(Boolean, default=False)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[Any] = mapped_column(JSONType, default=dict)
    #: 搜索用:标题、简介(各语言)与标签拼起来的小写文本。
    search_text: Mapped[str] = mapped_column(Text, default="")
    downloads_total: Mapped[int] = mapped_column(Integer, default=0)
    likes_total: Mapped[int] = mapped_column(Integer, default=0)
    views_total: Mapped[int] = mapped_column(Integer, default=0)
    #: 近 7 天的热度(下载 + 3×点赞 + 0.1×浏览),每次记数时重算。
    trend_score: Mapped[float] = mapped_column(Float, default=0.0)
    hidden_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    hidden_reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ItemTag(Base):
    __tablename__ = "item_tags"

    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    tag: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)


class ItemVersion(Base):
    """一项的一个版本 —— 也就是一次「提交」。审核队列里的就是 status=pending 的这些。"""

    __tablename__ = "item_versions"
    __table_args__ = (
        UniqueConstraint("item_id", "number"),
        UniqueConstraint("item_id", "version"),
        Index("ix_item_versions_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    #: 这一项的第几次提交(1 起)。
    number: Mapped[int] = mapped_column(Integer)
    #: 给人看的版本号:插件是清单里的 semver,工作流是提交序号。
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=VERSION_PENDING)
    submitter_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: 文件在存储里的位置。官方插件的包在 GitHub Release 上,这里为空、走 external_download。
    file_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    file_sha256: Mapped[str] = mapped_column(String(64), default="")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    #: 同一版的各语言文件(只有官方工作流有:`{"zh": {key, sha256, size}, "en": …}`)。
    localized_files: Mapped[Any] = mapped_column(JSONType, nullable=True)
    external_download: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: 插件:`{manifest, files, index_entry}`;工作流:`{graph, graphs?, summary}`。
    meta: Mapped[Any] = mapped_column(JSONType, default=dict)
    changelog: Mapped[str] = mapped_column(Text, default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Like(Base):
    __tablename__ = "likes"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ItemDailyStat(Base):
    """按天聚合的下载 / 浏览 / 点赞。"""

    __tablename__ = "item_daily_stats"

    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)


REPORT_OPEN = "open"
REPORT_RESOLVED = "resolved"
REPORT_DISMISSED = "dismissed"


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    #: workflow / plugin / share
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(String(32), index=True)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=REPORT_OPEN)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


# ---------------- 文件与画板分享 ----------------

BLOB_PENDING = "pending"
BLOB_READY = "ready"


class Blob(Base):
    """一个按内容哈希存的文件(画板里的媒体、头像)。同一份内容只存一次。"""

    __tablename__ = "blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(200))
    #: pending = 要过上传地址,还没核对过内容;ready = 哈希核对过。
    status: Mapped[str] = mapped_column(String(16), default=BLOB_PENDING)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BlobOwner(Base):
    """谁「拥有」这份文件:上传过它,或者在要上传地址时证明自己有它(知道哈希)。快照只能引用自己拥有的文件;
    每个用户的存储用量按这张表算。"""

    __tablename__ = "blob_owners"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sha256: Mapped[str] = mapped_column(ForeignKey("blobs.sha256", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


VISIBILITY_UNLISTED = "unlisted"
VISIBILITY_PUBLIC = "public"
VISIBILITIES = (VISIBILITY_UNLISTED, VISIBILITY_PUBLIC)


class Share(Base):
    """一个分享出去的画板。同一张画板(同一主人、同一 board_key)再分享 = 新版本,链接不变。"""

    __tablename__ = "shares"
    __table_args__ = (UniqueConstraint("owner_id", "board_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: 撤回之后置空:同一张画板再分享得到一个新链接,撤回的那个永远 410。
    board_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    visibility: Mapped[str] = mapped_column(String(16), default=VISIBILITY_UNLISTED)
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    hidden_reason: Mapped[str] = mapped_column(String(200), default="")


class ShareVersion(Base):
    """快照的一个版本。不可变。"""

    __tablename__ = "share_versions"
    __table_args__ = (UniqueConstraint("share_id", "number"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    share_id: Mapped[str] = mapped_column(ForeignKey("shares.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[Any] = mapped_column(JSONType)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    #: 第一次请求时生成的分享预览图在存储里的位置。
    og_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class ShareVersionBlob(Base):
    __tablename__ = "share_version_blobs"

    version_id: Mapped[str] = mapped_column(ForeignKey("share_versions.id", ondelete="CASCADE"), primary_key=True)
    sha256: Mapped[str] = mapped_column(ForeignKey("blobs.sha256"), primary_key=True)


__all__ = [
    "AuthSession",
    "Blob",
    "BlobOwner",
    "DeviceAuthorization",
    "Item",
    "ItemDailyStat",
    "ItemTag",
    "ItemVersion",
    "Like",
    "RateCounter",
    "RefreshToken",
    "Report",
    "Share",
    "ShareVersion",
    "ShareVersionBlob",
    "SmsCode",
    "User",
]
