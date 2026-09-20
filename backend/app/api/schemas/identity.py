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
    workspaces: int = 0


class BootstrapOut(ApiModel):
    """登录页开屏问的两件事(见 routes/auth.bootstrap)。不需要登录就能读。"""

    #: 这个部署里已经有账号了吗。没有 → 界面进「创建管理员账户」。
    has_users: bool = False
    #: 收不收自助注册。不收时注册要邀请码,界面才摆那个框。
    open_registration: bool = True


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


class SetRoleRequest(ApiModel):
    role: str = Field(pattern="^(owner|admin|editor|viewer)$")
