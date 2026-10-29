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
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    true,
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
    #: 官方账号标记。**只有部署脚本(`cloud.cli seed-official`)会把它写成 true**;
    #: 注册与 `PUT /me` 都不读这个字段。它是公开信息(`public_user()` 带出去),email 仍然不是。
    official: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


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


class CloudShare(Base):
    """一次社区分享:工作流工程文件、画板,或插件。

    **内容必须挂在身份上。** `owner_user_id` 非空,没有匿名发布。`payload` 服务端只校验
    "是一份 JSON 且不超过 2 MB",不解析里面的节点 / 画板结构 —— 那是客户端的事。
    """

    __tablename__ = "cloud_shares"
    __table_args__ = (
        CheckConstraint("kind IN ('workflow', 'board', 'plugin')", name="ck_cloud_shares_kind"),
        CheckConstraint("status IN ('listed', 'removed')", name="ck_cloud_shares_status"),
        # 语言只有两种;和 kind / status 一样,domain 层先校验,数据库再兜一道。
        CheckConstraint("locale IN ('zh-CN', 'en-US')", name="ck_cloud_shares_locale"),
        Index("idx_cloud_shares_owner", "owner_user_id"),
        Index("idx_cloud_shares_created", "created_at"),
        Index("idx_cloud_shares_kind_created", "kind", "created_at"),
        # 种子命令的稳定键:同一官方账号 + 同一 kind + 同一 slug + 同一语言只能有一行
        # (kind / locale 都进键,因为唯一性只该在"同一类内容、同一种语言"里成立)。
        # 用户分享的 slug 是 NULL,多条 NULL 不冲突。
        Index(
            "uq_cloud_shares_owner_kind_slug_locale",
            "owner_user_id",
            "kind",
            "slug",
            "locale",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    #: `workflow` / `board` / `plugin`。别的值在 domain 层就 422,数据库再兜一道 CHECK。
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 这条分享的标题 / 简介是哪一种语言(`zh-CN` / `en-US`)。**发布时必须声明**:
    #: 用户的语言来自官网当前语言段;官方内容按 bundle 里的 `locales` 一条语言一行。
    #: 既有行由 0007 迁移填 `zh-CN` —— 迁移当时没有别的语言信息可推断,只能这么定。
    locale: Mapped[str] = mapped_column(
        String(5), nullable=False, default="zh-CN", server_default="zh-CN"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    #: 工程文件本体。列表和详情都不返回它,只有 `/payload` 与 `/download` 给。
    payload: Mapped[Any] = mapped_column(JSONType, nullable=False)
    #: 紧凑 UTF-8 JSON 的实际字节数。列表页只读这个数,不必碰 payload。
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    license: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    #: 种子命令的稳定标识(bundle 里的 slug)。**用户分享一律 NULL**;不对外暴露,
    #: 只用于"重复跑种子不产生重复行"。
    slug: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
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
    #: 点了 / 评论了的人。响应里只给公开身份(含 official),email 不在这里。
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


class CloudDeviceToken(Base):
    """一台桌面端的长效凭据 —— 网关(ADR 0088)只认它,不认浏览器会话。

    **不是 0004 拆掉的「设备绑定」**:没有设备码、没有在官网上确认配对那一步。桌面端先照常登录
    (拿到会话),再用这份会话**自己**换一枚令牌;换令牌和登录是同一次用户动作。

    和会话分开的理由:会话 30 天过期、是浏览器的东西,而网关调用来自桌面后端、要能长期用、要能
    在官网的「我的设备」里一枚枚吊销。**只存令牌的 sha256**,原文只出现在签发的那一次响应里。
    """

    __tablename__ = "cloud_device_tokens"
    __table_args__ = (Index("idx_cloud_device_tokens_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    #: 桌面端报上来的设备名(如「Kinda 的 MacBook Pro」),只给用户在设备列表里认。
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    #: 最近一次用它鉴权的时间。按分钟粒度写(见 `domain/device_tokens.touch`),不是每个请求一次写库。
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


# ---------------------------------------------------------------- 套餐与积分(ADR 0088 §2)
#
# 积分只有一本账:**余额是流水的结果**。`cloud_credit_batches` 记「这一批发了多少、何时到期」,每一笔进出
# (发放、预占、释放、到期清零、人工调整)都是 `cloud_usage_entries` 里一行带符号的 `delta`,挂在它动的那一批上;
# 某一批剩多少 = 这一批所有流水的和。没有可改写的「余额」列,所以也没有「余额和流水对不上」这种状态。


class CloudPlan(Base):
    """一个套餐。价格与支付在第 3 步(订单)加;这里只记它每月给多少积分、积分活多久。"""

    __tablename__ = "cloud_plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 运营与命令行认它用的短名(如 `pro-monthly`)。
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: 计费周期:`month` / `quarter` / `year`。**积分一律按月发**,周期只决定订阅多久(ADR 0088 待拍板 #2)。
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    monthly_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 每一批月度积分从发放起活多少天(运营参数,如 60:当月没用完还能再用一个月)。
    credit_ttl_days: Mapped[int] = mapped_column(Integer, nullable=False)
    on_sale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)

    __table_args__ = (
        CheckConstraint("period IN ('month', 'quarter', 'year')", name="ck_cloud_plans_period"),
        CheckConstraint("monthly_credits > 0 AND credit_ttl_days > 0", name="ck_cloud_plans_positive"),
    )


class CloudSubscription(Base):
    """一个用户订了哪个套餐、到什么时候。下一批月度积分何时发记在 `next_grant_at`,读余额时按需补发(不靠定时任务)。"""

    __tablename__ = "cloud_subscriptions"
    __table_args__ = (
        Index("idx_cloud_subscriptions_user", "user_id"),
        CheckConstraint("status IN ('active', 'ended')", name="ck_cloud_subscriptions_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey("cloud_plans.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    #: 这个订阅到哪一刻为止(按周期算出来;续费在第 3 步)。过了这一刻不再发新批次,已发的照各自的有效期用完。
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: 下一批月度积分该在何时发。等于或早于现在就补发一批并往后推一个月,直到超过现在或超过 `ends_at`。
    next_grant_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudCreditBatch(Base):
    """一批积分:来源、发了多少、何时到期。**不记余额** —— 余额是这一批流水的和。"""

    __tablename__ = "cloud_credit_batches"
    __table_args__ = (
        Index("idx_cloud_credit_batches_user_expiry", "user_id", "expires_at"),
        CheckConstraint("source IN ('plan', 'gift')", name="ck_cloud_credit_batches_source"),
        CheckConstraint("amount > 0", name="ck_cloud_credit_batches_amount"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False)
    #: `plan`(套餐月度)/ `gift`(赠送;以后的加购再加一种)。
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_subscriptions.id", ondelete="SET NULL"), nullable=True, default=None
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: 运营备注(赠送原因等)。不进任何对外响应。
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="")


class CloudUsageEntry(Base):
    """积分的一笔进出,**只追加**。`delta` 带符号:发放 / 释放为正,预占 / 到期清零为负,人工调整两者皆可。"""

    __tablename__ = "cloud_usage_entries"
    __table_args__ = (
        Index("idx_cloud_usage_entries_batch", "batch_id"),
        Index("idx_cloud_usage_entries_user_created", "user_id", "created_at"),
        Index("idx_cloud_usage_entries_call", "call_id"),
        CheckConstraint(
            "kind IN ('grant', 'reserve', 'release', 'expire', 'adjust')", name="ck_cloud_usage_entries_kind"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[str] = mapped_column(ForeignKey("cloud_credit_batches.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 预占 / 释放属于哪一次网关调用;发放、到期、调整没有。
    call_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_gateway_calls.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudGatewayCall(Base):
    """网关的一次调用:谁、哪台设备、哪个模型、走的哪条通道,预占了多少、最后扣了多少、上游报的用量。

    用户的「用量明细」和平台的成本账都从这里出;积分怎么动的在 `cloud_usage_entries`(按 `call_id` 对得上)。
    """

    __tablename__ = "cloud_gateway_calls"
    __table_args__ = (
        Index("idx_cloud_gateway_calls_user_created", "user_id", "created_at"),
        CheckConstraint(
            "status IN ('reserved', 'settled', 'released')", name="ck_cloud_gateway_calls_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("cloud_users.id", ondelete="CASCADE"), nullable=False)
    device_token_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_device_tokens.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 实际走的那条上游通道(换过通道就是最后成的那条);没走成是空。
    channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("cloud_upstream_channels.id", ondelete="SET NULL"), nullable=True, default=None
    )
    #: `reserved`(进行中)/ `settled`(按用量扣了)/ `released`(没成,全额退回)。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    charged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 用量是不是上游报的。`False` = 上游没给(或流被中途掐断),按字数估的。
    usage_reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


# ---------------------------------------------------------------- 网关的模型目录与上游通道(ADR 0088 §3、§4)


class CloudGatewayModel(Base):
    """网关对外列出的一个模型。`id` 就是桌面端选模型时用的那个名字(如 `deepseek-chat`)。"""

    __tablename__ = "cloud_gateway_models"
    __table_args__ = (CheckConstraint("kind IN ('chat')", name="ck_cloud_gateway_models_kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    #: 第 2 步只有对话;生成类在第 4 步加进这道 CHECK。
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 一次调用最多让上游生成多少 token。预占按它算上限,请求里的 `max_tokens` 不许超过它。
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudModelPrice(Base):
    """一个模型的积分单价,**带生效时间**:调价是加一行,不改旧行;一次调用按它预占那一刻生效的那一行算。"""

    __tablename__ = "cloud_model_prices"
    __table_args__ = (
        Index("idx_cloud_model_prices_model_effective", "model_id", "effective_from"),
        CheckConstraint("input_per_1k >= 0 AND output_per_1k >= 0", name="ck_cloud_model_prices_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("cloud_gateway_models.id", ondelete="CASCADE"), nullable=False)
    #: 每千个输入 / 输出 token 多少积分。整数:积分是最小单位,一次调用按两项相加后向上取整。
    input_per_1k: Mapped[int] = mapped_column(Integer, nullable=False)
    output_per_1k: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class CloudUpstreamChannel(Base):
    """一个模型背后的一条上游通道:哪家的端点、哪把 Key、对上游叫什么模型、优先级。

    Key 用 `CLOUD_CHANNEL_KEY`(Fernet)加密后落库,只在网关发请求那一刻解开,不进日志、不进任何响应。
    """

    __tablename__ = "cloud_upstream_channels"
    __table_args__ = (
        Index("idx_cloud_upstream_channels_model", "model_id", "priority"),
        CheckConstraint("protocol IN ('openai')", name="ck_cloud_upstream_channels_protocol"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("cloud_gateway_models.id", ondelete="CASCADE"), nullable=False)
    #: 对上游说哪种话。第一版只有 OpenAI 兼容(见 ADR 0088 §4)。
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="openai")
    #: 端点前缀,如 `https://api.deepseek.com/v1`;请求打到 `<base_url>/chat/completions`。
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    #: 上游那边这个模型叫什么(可能和网关对外的 id 不同)。
    upstream_model: Mapped[str] = mapped_column(String(120), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(String(1000), nullable=False)
    #: 小的先用。
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    #: 回过 429 / 5xx / 超时之后歇到这一刻;歇着的通道排到最后,全都歇着时照样按优先级试。
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
