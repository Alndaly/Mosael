"""账号、登录态、工作区与成员的请求/响应体。"""

from __future__ import annotations

from datetime import datetime
from pydantic import ConfigDict, Field
from app.api.schemas.base import ApiModel, OrmModel

class AuthCredentials(ApiModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=4, max_length=200)


class RegisterCredentials(AuthCredentials):
    display_name: str = Field(default="", max_length=120)
    #: 进这个部署的邀请码。空库的第一个账号不需要;开放注册的部署也不需要。
    invite_code: str = Field(default="", max_length=64)


class DeploymentAdminUpdate(ApiModel):
    granted: bool


class InviteCreate(ApiModel):
    note: str = Field(default="", max_length=120)


class UserOut(OrmModel):
    id: str
    username: str
    display_name: str
    signature: str
    #: 空 = 未设置头像;非空时前端以 /api/auth/users/{id}/avatar?v=<key> 取图并借 key 破缓存。
    avatar_key: str = ""
    #: 这个部署的管理员(见 core/permissions.ensure_deployment_admin)。界面据此决定要不要
    #: 摆出「部署」那一块、以及能不能把一把钥匙共享给全员。
    is_deployment_admin: bool = False
    #: 这个账号挂着的第三方登录(`google` / `apple`,见 OAuthIdentity)。空 = 用户名加密码的账号。
    #: users 表上没有这一格 —— 身份映射本来就在 oauth_identities 里,另存一份只会两处漂移;
    #: 所以它不是 ORM 属性,由 routes/auth.current_user_out 查出来填上。
    oauth_providers: list[str] = Field(default_factory=list)


class AdminPasswordResetOut(ApiModel):
    """部署管理员替成员重置密码:新的临时密码原文**只在这一次**给出(库里存哈希),交给对方后他在「设置 → 账户」里改。"""

    password: str


class AdminUserOut(ApiModel):
    """管理员看到的一个人。"""

    id: str
    username: str
    display_name: str
    is_deployment_admin: bool
    created_at: datetime
    #: 最近一次用到这个部署。空 = 从没登录过(或老会话还没记过)。
    last_seen_at: datetime | None = None
    #: 他现在跑的客户端版本。**由客户端自报**,空 = 那个客户端不报(老版本)——
    #: 空着而不是编一个,"不知道"和"0.0.0"是两回事。
    client_version: str = ""
    #: 哪个界面(`app` / `browser-extension`)。和版本分开:挤成一栏的时候,扩展把产品名
    #: 塞进了版本栏,管理页于是显示「vbrowser-extension」。
    client_surface: str = ""
    workspaces: int = 0


class BootstrapOut(ApiModel):
    """登录页开屏问的两件事(见 routes/auth.bootstrap)。不需要登录就能读。"""

    #: 这个部署里已经有账号了吗。没有 → 界面进「创建管理员账户」。
    has_users: bool = False
    #: 收不收自助注册。不收时注册要邀请码,界面才摆那个框。
    open_registration: bool = True
    #: 成员用浏览器打开 Mosael 的地址(部署管理员在管理页配,ADR 0054);空 = 没有网页版。
    web_url: str = ""


class AuthOut(ApiModel):
    token: str
    user: UserOut


class UserProfileUpdate(ApiModel):
    username: str = Field(min_length=2, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    signature: str = Field(default="", max_length=500)


class PasswordUpdate(ApiModel):
    current_password: str = Field(min_length=4, max_length=200)
    new_password: str = Field(min_length=4, max_length=200)


class RenameRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=160)


class WorkspaceOut(OrmModel):
    id: str
    name: str
    role: str | None = None  # the caller's role in this workspace (None if unknown)


class WorkspaceMemberOut(ApiModel):
    user_id: str
    username: str
    display_name: str
    role: str
    is_self: bool = False


class MembersOut(ApiModel):
    members: list[WorkspaceMemberOut]
    my_role: str


class InviteMemberRequest(ApiModel):
    username: str = Field(min_length=2, max_length=80)
    role: str = Field(default="editor", pattern="^(admin|editor|viewer)$")


class InvitationOut(ApiModel):
    id: str
    workspace_id: str
    workspace_name: str
    inviter_name: str
    invitee_name: str
    role: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvitationListOut(ApiModel):
    invitations: list[InvitationOut]


class InviteLinkCreate(ApiModel):
    """在工作区团队页发一张邀请链接(ADR 0054)。所有者不经链接给。"""

    role: str = Field(default="editor", pattern="^(admin|editor|viewer)$")


class InviteCodeIn(ApiModel):
    """链接里那串码。**放在请求体里,不放进地址** —— 地址会进访问日志,而它就是凭据。"""

    code: str = Field(min_length=8, max_length=200)


class InviteLinkOut(ApiModel):
    """一张发出去的邀请链接。原文不在这里(库里只有哈希);认它靠末尾几位。"""

    id: str
    code_hint: str
    #: 进哪个工作区;空 = 只进这台部署(不带工作区的邀请)。
    workspace_id: str | None
    role: str
    note: str
    #: open / used / revoked / expired
    state: str
    #: 还没账号的人能不能凭它注册(部署管理员放过行,或者部署开放注册)。
    allows_signup: bool
    #: 工作区管理员请部署管理员放行了、还在等。
    signup_requested: bool
    created_by_name: str
    expires_at: datetime
    created_at: datetime


class IssuedInviteLinkOut(ApiModel):
    """刚发出去的那一张:**原文只在这一次**。`web_url` 是部署配的网页地址(空 = 没有网页版,只给深链)。"""

    link: InviteLinkOut
    code: str
    web_url: str


class InviteLinkPreviewOut(ApiModel):
    """打开链接、还没登录的那一屏要知道的(只给拿着原文的人)。"""

    workspace_name: str
    inviter_name: str
    role: str
    state: str
    allows_signup: bool


class InviteLinkJoinedOut(ApiModel):
    """凭链接进了哪个工作区(界面切过去,toast 说主人和角色,能撤销)。"""

    workspace_id: str
    workspace_name: str
    role: str
    owner_name: str
    already_member: bool


class WebUrlUpdate(ApiModel):
    """部署的网页地址:空串 = 没有网页版。"""

    url: str = Field(default="", max_length=500)


class SetRoleRequest(ApiModel):
    role: str = Field(pattern="^(owner|admin|editor|viewer)$")
