"""账号与工作区:谁是谁、谁在哪个工作区里、以及登录态。

这几张表是整个应用的**租户边界**:每张业务表上的 workspace_id 最终指到这里,而
ensure_workspace_access 问的就是 workspace_members 有没有这一行。归属见 domain/ownership.py。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.db.model_base import new_id, now

class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: 自动放行的准则(见 domain/agent/rules)。带 server_default:迁移语句里写了 DEFAULT,
    #: 模型这边不写的话,**迁移出来的库和新建的库 schema 不一致** —— 同一份代码两种形状,
    #: 而先撞上的往往是一条裸 SQL(测试或以后的运维脚本),报一句看不懂的 NOT NULL 失败。
    #: 下面几个带 DEFAULT 的列同理:http 主机白名单、发布账号白名单、run_code 要不要
    #: 交给判断者、以及一段自由文本。**工作区级**而不是会话级:它是"这个团队允许什么"的策略,
    #: 不是"这次对话想怎么样"的选择 —— 后者是权限模式。
    autopilot_rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    #: 他对**这个后端实例**负责吗 —— 网络出口、插件启用、解释器路径、模型下载。
    #:
    #: 此前这件事没有对应物,只能用「在任意工作区里是 owner/admin」去近似,而任何人都能新建
    #: 工作区并在里面是 owner —— 那个近似是**自助的**(ADR 0008 §2.1 有复现)。把它变成数据之后,
    #: 判据不再能被自己造出来。
    #:
    #: **不叫「机器主人」**:共享部署里跑这个后端的人未必是任何一个用户。这说的是谁对这个部署
    #: 负责,不是谁拥有这台机器。库里第一个账号自动持有,之后只能由已有的部署管理员授予。
    is_deployment_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    signature: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 头像文件相对 data_dir 的 key(avatars/<uid>-<ts>.<ext>);空 = 未设置,前端回退首字母。
    avatar_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class AuthSession(Base):
    """一份可以用来调这个 API 的凭据 —— 人登录的,和子进程回连用的,是同一张表、同一种权力。

    **每一行都必须会过期。** 此前没有 `expires_at`,于是"用完删掉"是每个铸造点各自的责任:
    对话轮次记得删,工具通道忘了(一次调用留一行),OAuth 刷新/查额度/订阅登录也忘了 ——
    同一个缺陷发作了五次,而漏掉一处不会有任何东西报错。周期由表来保证之后,忘记撤销最多是
    多活一会儿,不再是留下一把永久钥匙。铸造与清理都在 core/security.py。

    `kind` 区分的是**周期的来源**:登录会话的周期是"这个人还在用这台机器"(活跃即续期),
    服务令牌的周期是"那次操作要跑多久"(用得再多也不续)。
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("idx_auth_sessions_user", "user_id"),
        # 清理按过期时间扫全表;泄漏期攒下的行可能不少,别让它退化成顺序扫描。
        Index("idx_auth_sessions_expires", "expires_at"),
    )

    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    #: login(人)| service(子进程回连)。决定要不要滑动续期。
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="login", server_default="login")
    #: 这份凭据属于哪次智能体会话(service 令牌;登录令牌为空)。**确认卡的归属从这里来**——
    #: 归属由凭据决定,不由调用方在请求体里声明,否则任何拿着同一份凭据的通道都能把自己的动作
    #: 挂到一个开了自动放行的会话上。不设外键:会话删掉之后令牌仍要能认出人来(周期结束自然消失)。
    agent_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    #: 不给默认值:每个铸造点都必须说清这份凭据该活多久,漏了是 IntegrityError 而不是永久有效。
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: 这个客户端自报的版本(见 api/deps/auth.parse_client_header)。**必须由客户端报** ——
    #: 后端进程的 app_version 是它自己的版本,回答不了"分布式部署里某个人装的是哪一版",
    #: 而那正是管理员要看的:它解释了为什么只有他撞得到那个早就修好的 bug。
    client_version: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    #: 哪个界面(app / browser-extension)。和上面那一列**分开存**:它们是两个问题,
    #: 而此前挤在一栏里 —— 扩展把产品名塞进版本栏,管理页于是显示「vbrowser-extension」。
    client_surface: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    #: 这份凭据最近一次被用到。管理员据此看"他还在用吗" —— 停用一个账号之前总要先知道这个。
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OAuthIdentity(Base):
    """第三方登录身份(google/apple)→ 本地账号的映射;同一账号可挂多个身份。
    subject 是提供方 id_token 里的稳定用户标识(sub),email 只作展示留痕。"""

    __tablename__ = "oauth_identities"

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")  # owner|admin|editor|viewer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class RegistrationInvite(Base):
    """**进这个部署**的邀请码 —— 与 WorkspaceInvitation(进某个工作区)是两件事。

    关掉自助注册之后必须有这个:老的邀请流程是「按用户名邀请一个**已注册**账号」,而账号从哪来
    正是被关掉的那条路。两层划分在这里第一次显形 —— 一个是部署的门,一个是工作区的门。

    码是随机串,由管理员带外发给对方;对方拿它注册并**自己设密码** —— 保持仓库既有的那条
    「密码不经过任何第三人之手」(见 domain/members 的说明)。
    """

    __tablename__ = "registration_invites"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    #: 给谁的(仅备注,不做校验)—— 管理员自己看得出这个码发给了谁。
    note: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    used_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WorkspaceInvitation(Base):
    """工作区邀请(邀请制):受邀人从通知里 接受/拒绝,接受才写成员行。"""

    __tablename__ = "workspace_invitations"
    __table_args__ = (Index("idx_ws_invitations_invitee_status", "invitee_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    inviter_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    invitee_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="editor")  # admin|editor|viewer
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|accepted|declined
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
