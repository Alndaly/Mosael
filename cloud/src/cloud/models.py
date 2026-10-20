"""MosaelCloud 的数据形状。

**这是另一套账号体系,不是本地 Mosael 的 `users`。** 表名统一带 `cloud_` 前缀,是为了让"这份库
属于谁"在 `sqlite3 .tables` 的第一眼就看得出来,也为了让一条"Cloud 库里不许出现 users 表"的测试
有东西可断言。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cloud.db import Base, JSONType


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    """朴素 UTC —— 和仓库其它服务一致,避免 SQLite 里两种时区语义混着存。"""
    return datetime.now(UTC).replace(tzinfo=None)


class CloudUser(Base):
    """一个 MosaelCloud 账号。邮箱必填,密码可选(第三方登录建出来的账号没有);**没有**本地账号的用户名、工作区、部署管理员。

    身份(`display_name` / `handle` / `avatar_seed`)是**另一件事**,可空:注册不要求填,
    第一次发布或评论时才要求。没填之前账号照样能浏览、能登录。
    """

    __tablename__ = "cloud_users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 统一存小写。唯一索引保证"一个邮箱一个账号",并发注册靠数据库兜底。
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    #: argon2id 哈希(见 security.hash_password)。绝不存明文。
    #: **可空**:第三方登录新建的账号没有密码,只靠第三方身份或邮箱验证码登录。
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: 注册时要先验邮箱验证码,验过即写这个时间;更早的账号可能是空,不做回填。
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    #: 公开昵称。可空 = 还没有身份;空串不允许。**公开响应里只给这一列,不给 email。**
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    #: 唯一短名,个人页 `/u/<handle>`。可空(还没起名字),多个 NULL 不算冲突。
    handle: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True, default=None)
    #: 头像种子:一个短字符串。P1 的头像 = 昵称首字母 + 由这个种子决定的颜色,**不存图片**。
    avatar_seed: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)


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


class CloudIdentity(Base):
    """一个第三方身份(GitHub / Google)与某个 MosaelCloud 账号的绑定。

    `(provider, provider_user_id)` 唯一:同一个第三方账号只能指向一个 Cloud 账号。
    反方向不唯一:一个 Cloud 账号可以绑多个第三方(`user_id` 上的索引只为查"这个账号绑了谁")。
    """

    __tablename__ = "cloud_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_cloud_identities_provider_user"),
        Index("idx_cloud_identities_user", "cloud_user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: `github` / `google`。就这两个,校验在路由层做。
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 第三方那边的稳定 id:GitHub 的数字 id、Google 的 `sub`。一律按字符串存。
    provider_user_id: Mapped[str] = mapped_column(String(191), nullable=False)
    cloud_user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudOAuthState(Base):
    """一次第三方登录的中间状态 —— **只存哈希**,原始值只出现在跳转 URL / 那枚短命 cookie 里。

    - `state`:防 CSRF 的一次性串。库里存 sha256,回调时按哈希查、原子地标 `used_at`。
    - `nonce`:同时写进发起请求的浏览器的一枚 HttpOnly cookie;回调必须带回来。
      这一期不验 id_token,所以它不是 OIDC 的 nonce,而是"这次 state 属于这个浏览器"的绑定。
    - `code_verifier`:PKCE 的 verifier。换 token 要用明文,所以不能只存哈希;它和 state 一起
      10 分钟过期、用完即随行作废(整张表都是短期数据)。
    """

    __tablename__ = "cloud_oauth_states"
    __table_args__ = (Index("idx_cloud_oauth_states_expires", "expires_at"),)

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 发起登录时如果浏览器已经登录,就记下是谁 —— 回调时把第三方身份绑到这个账号,
    #: 而不是另建一个。为空 = 这次是登录 / 注册。
    link_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=True
    )
    #: 回调失败时把用户送回他点按钮的那一页,以及用哪种语言显示原因。
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    return_page: Mapped[str] = mapped_column(String(16), nullable=False, default="login")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


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


class CloudShare(Base):
    """一次社区分享:工作流工程文件,或画板。

    **内容必须挂在身份上。** `owner_user_id` 非空,没有匿名发布。`payload` 服务端只校验
    "是一份 JSON 且不超过 2 MB",不解析里面的节点 / 画板结构 —— 那是客户端的事。
    """

    __tablename__ = "cloud_shares"
    __table_args__ = (
        CheckConstraint("kind IN ('workflow', 'board')", name="ck_cloud_shares_kind"),
        CheckConstraint("status IN ('listed', 'removed')", name="ck_cloud_shares_status"),
        Index("idx_cloud_shares_owner", "owner_user_id"),
        Index("idx_cloud_shares_created", "created_at"),
        Index("idx_cloud_shares_kind_created", "kind", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    #: `workflow` / `board`。别的值在 domain 层就 422,数据库再兜一道 CHECK。
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    #: 工程文件本体。列表和详情都不返回它,只有 `/payload` 与 `/download` 给。
    payload: Mapped[Any] = mapped_column(JSONType, nullable=False)
    #: 紧凑 UTF-8 JSON 的实际字节数。列表页只读这个数,不必碰 payload。
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    license: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    #: P1 只有 `listed` / `removed`。作者删除 = 软删(改状态),不再出现在任何公开读接口里。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="listed")
    #: 下载计次。`POST /download` 每次 +1。
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now, onupdate=now)


class CloudShareLike(Base):
    """一个人对一次分享的点赞。**去重靠 `(share_id, user_id)` 主键**,不靠先查再插。"""

    __tablename__ = "cloud_share_likes"
    __table_args__ = (Index("idx_cloud_share_likes_user", "user_id"),)

    share_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_shares.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudShareFavorite(Base):
    """一个人收藏的一次分享。和点赞同一套形状:唯一性由主键保证,重复写是幂等的。"""

    __tablename__ = "cloud_share_favorites"
    __table_args__ = (Index("idx_cloud_share_favorites_user", "user_id"),)

    share_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_shares.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudShareComment(Base):
    """一条评论。`body` 存原文(不转义、不渲染 markdown);响应是 JSON 纯文本,由前端按文本显示。"""

    __tablename__ = "cloud_share_comments"
    __table_args__ = (
        Index("idx_cloud_share_comments_share", "share_id", "created_at"),
        Index("idx_cloud_share_comments_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    share_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_shares.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudShareNotification(Base):
    """"谁对谁的分享做了什么" —— 一条互动一行,收件人永远是分享作者。

    **自己对自己的分享不产生通知**,这条规则在 domain 层写一次,不在读取时再过滤。

    `(recipient_id, actor_id, share_id, kind)` 在未读状态下只允许一行:靠一条部分唯一索引
    (`WHERE read_at IS NULL`)兜底。于是同一个人对同一条分享连续点赞 / 取消 / 再点赞,或者
    连续评论,最多只堆出一条未读;已读之后的新互动才会新开一行(历史保留)。

    取消点赞 / 收藏删掉的是**未读**那一行;已读的那行是历史,不再断言"他还赞着"。
    删评论按 `comment_id` 把对应通知一起删。分享软删只影响读取(join 掉),不删这里的行。
    """

    __tablename__ = "cloud_share_notifications"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('like', 'favorite', 'comment')", name="ck_cloud_share_notifications_kind"
        ),
        # 列表:按收件人取新序。SQLite 的反射不保留排序方向,所以这里按同名列声明,
        # 实际建库语句是 `(recipient_id, created_at DESC)`(见 0003 迁移),alembic check 不误报。
        Index("idx_cloud_share_notifications_recipient_created", "recipient_id", "created_at"),
        # 未读数:`recipient_id + read_at IS NULL`。
        Index("idx_cloud_share_notifications_recipient_read", "recipient_id", "read_at"),
        # 删评论时按 comment_id 找通知。
        Index("idx_cloud_share_notifications_comment", "comment_id"),
        # 一个槽位最多一条未读 —— 重复点赞 / 连续评论不会刷出多条。
        Index(
            "uq_cloud_share_notifications_unread",
            "recipient_id",
            "actor_id",
            "share_id",
            "kind",
            unique=True,
            sqlite_where=text("read_at IS NULL"),
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 收到通知的人 = 分享作者。删号时一起消失。
    recipient_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    #: 点了 / 评论了的人。响应里只给公开三列,email 不在这里。
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    share_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_shares.id", ondelete="CASCADE"), nullable=False
    )
    #: `like` / `favorite` / `comment`。
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 评论通知指向的那条评论;点赞 / 收藏为空。评论被删时这一行也一起删。
    comment_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_share_comments.id", ondelete="CASCADE"), nullable=True, default=None
    )
    #: 读掉就填。NULL = 未读。
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
