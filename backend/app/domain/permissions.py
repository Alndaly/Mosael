"""授权:这个人能不能碰这个工作区/这份素材。

**从 `app/core/permissions.py` 搬出来的。** 它原本住在 core —— 一个被二十几处 import 的底座,
却在对业务表(WorkspaceMember / Asset / Sequence)做鉴权。同一个文件里还挤着 FastAPI 的认证
插头(`Depends` / `Request` / `Query`),那部分现在在 `api/deps/auth.py`。

**为什么不整体搬进 api**(那里有 27/29 个调用点):授权必须能从**非 HTTP 入口**调用。飞书的
卡片回调不走路由,它和 HTTP 路由共用同一个 `authorize_and_approve`,而后者就在领域层调
`ensure_workspace_perm`(见 domain/agent/confirmations 的说明:两个入口各抄一遍校验时,
漏掉一处等于越权)。

**为什么抛领域异常而不是 HTTPException**:领域层此前 HTTPException 是 0 处。把 FastAPI 引进来
是拿一个倒置换另一个,而且换来的更糟 —— 领域逻辑正是要能脱离 HTTP 被 worker / MCP / 飞书复用。
状态码由 `api` 那一侧统一翻(见 main.py 的异常处理器),两个异常各自对应一个**故意的**答案:

- `NotVisible` → **404**:不是这个工作区的人,连"它存在"都不告诉他;
- `PermissionDenied` → **403**:是这里的人,但角色不够。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.roles import role_at_least
from app.core.usage_scope import bind_workspace
from app.db.models import Asset, Sequence, User, WorkspaceMember


class PermissionDenied(Exception):
    """是这个工作区的人,但角色不够。api 翻成 403。"""


class NotVisible(Exception):
    """对他来说这个东西不存在(不是成员、或行本身没有)。api 翻成 **404 而不是 403** ——
    403 会告诉他"这个 id 是存在的",那正是要避免的泄漏。"""


def _membership(db: Session, user: User, workspace_id: str) -> WorkspaceMember:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if member is None:
        # Non-members get 404, never 403 — don't leak that the workspace exists.
        raise NotVisible("Not found")
    return member


# The current request's HTTP method, bound by the ASGI middleware in app/main.py.
# Lets the shared access chokepoint stay read-open but write-gated without every route
# passing the method through. Defaults to GET so non-HTTP call paths (tests, workers,
# daemon jobs) are treated as reads and never spuriously 403.


def ensure_workspace_member(db: Session, user: User, workspace_id: str) -> None:
    """Pure membership gate, method-agnostic — for read-only POSTs (search / retrieval
    test) that must stay open to viewers."""
    _membership(db, user, workspace_id)
    bind_workspace(workspace_id)


def ensure_workspace_access(db: Session, user: User, workspace_id: str) -> None:
    """**只读闸**:他是不是这个工作区的人。任何成员都能过。

    此前它还兼职判写权限 —— 「当前请求是不是 POST?是就额外要 edit」。那个方法名读自一个只在
    ASGI 中间件里绑定的 ContextVar,**默认 GET**,于是这道闸的正确性不取决于路由写了什么,而
    取决于它碰巧是从哪儿被调用的:后台线程(定时器、自动放行、工作流引擎、飞书回调)里同一个
    函数会安静地放行 viewer(ADR 0008 §2.2 与 D5,tests/test_write_permission_is_explicit.py
    里有复现)。

    现在要写的路由自己点名 `ensure_workspace_perm(..., "edit")`。少一个"聪明"的推断。
    """
    _membership(db, user, workspace_id)
    # 通过闸门 = 这次请求确实是关于这个工作区的。用量记账据此归属,不必再让每个调用点
    # 把 workspace_id 一路穿到底(见 core/usage_scope 的说明)。放在校验之后:没过闸门的
    # 请求不该在上下文里留下痕迹。
    bind_workspace(workspace_id)




def workspace_role(db: Session, user: User, workspace_id: str) -> str | None:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    return member.role if member else None


def ensure_workspace_role(db: Session, user: User, workspace_id: str, minimum: str) -> str:
    """Member must hold at least `minimum` role. Returns the caller's role."""
    member = _membership(db, user, workspace_id)
    if not role_at_least(member.role, minimum):
        raise PermissionDenied("Insufficient workspace role")
    return member.role


#: 老权限位 → 最低角色。**这不是一层新的间接**,是给 47 处调用点一次性换名的对照表:
#: 位与位之间的区别在这个产品里从来没有真实场景,而角色阶梯有。
_PERM_ROLE = {
    "upload": "editor",
    "edit": "editor",
    "delete": "editor",
    "export": "editor",
    "ai": "editor",
    "schedule": "editor",
    "publish": "editor",
    "members": "admin",
}


def ensure_workspace_perm(db: Session, user: User, workspace_id: str, perm: str) -> None:
    """写闸:成员的角色要够。

    保留 `perm` 这个参数是为了让调用点自己说清「这是哪一类操作」—— 它读起来比一个裸的 "editor"
    有信息(`ensure_workspace_perm(..., "publish")` 一眼看出这条路由在发东西)。但它**不再是一个
    可以逐位开关的能力**,只是映射到一档角色(见 _PERM_ROLE)。
    """
    minimum = _PERM_ROLE.get(perm, "admin")
    member = _membership(db, user, workspace_id)
    if not role_at_least(member.role, minimum):
        raise PermissionDenied(f"Permission denied: {perm}")
    bind_workspace(workspace_id)


def ensure_deployment_admin(db: Session, user: User) -> None:
    """守**这个后端实例**的配置:网络出口、插件启用、解释器路径、模型下载。

    判据是 `users.is_deployment_admin` 一列 —— 一个事实,不是一个推断。

    此前它叫 `ensure_deployment_admin`,判据是「在**任意**工作区里是 owner/admin 且在那里持有某个
    权限位」。而任何登录用户都能新建工作区并在里面是 owner,所以那个判据是**自助的**:

        viewer 改实例级网络设置                  403
        他自己新建一个工作区之后再改一次          200   ← 复现过

    顺带,它的第二个条件从来没起过作用:editor 默认持有除 `members` 外的全部权限位,于是
    「持有 perm」恒真 —— 真正的判据只剩「角色 ≥ admin」。所以新判据不再接受 perm 参数。

    单机安装不受影响:那个人就是引导账号,库里第一个用户自动持有这一列。
    """
    if not user.is_deployment_admin:
        raise PermissionDenied("这项设置属于整个部署,只有部署管理员能改")




def require_asset(db: Session, user: User, asset_id: str, *, perm: str | None = None) -> Asset:
    """取素材并过闸。`perm` 是**写**路由必须点名的那一项(见 ensure_workspace_perm);
    只读路由不传,拿到的就是只读闸。"""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotVisible("Not found")
    if perm is None:
        ensure_workspace_access(db, user, asset.workspace_id)
    else:
        ensure_workspace_perm(db, user, asset.workspace_id, perm)
    return asset


def require_sequence_access(db: Session, user: User, sequence_id: str, *, perm: str | None = None) -> Sequence:
    """取序列并过闸。写路由传 `perm="edit"` —— 权限写在调用点上,而不是从请求方法推。"""
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise NotVisible("Not found")
    if perm is None:
        ensure_workspace_access(db, user, sequence.workspace_id)
    else:
        ensure_workspace_perm(db, user, sequence.workspace_id, perm)
    return sequence
