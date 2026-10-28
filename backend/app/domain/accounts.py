"""账号本身:凭用户名密码认人、改自己的资料与头像、部署管理员名单。

`members` 管的是「谁在哪个工作区、怎么被邀请进来」;这里管的是那个人的账号行。此前这些规则写在
`api/routes/auth.py` 里(用户名撞车、最后一个部署管理员不能收回、头像的类型与大小),路由成了第二个
领域层 —— 别的入口要做同样的事就得再抄一遍。

领域只改对象,提交交给入口层(见 core/unit_of_work)。需要等提交成功之后才能做的(删旧头像文件)
用 `after_commit` 登记。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import LocalizedError
from app.core.security import hash_password, revoke_other_logins, verify_password
from app.core.unit_of_work import after_commit
from app.db.models import OAuthIdentity, User, new_id
from app.domain import members
from app.domain.permissions import ensure_deployment_admin


class AccountError(LocalizedError):
    """账号操作被规则拦下。路由按子类翻成对应的 HTTP 状态。"""


class LastDeploymentAdmin(AccountError):
    """要收回的是最后一个部署管理员。"""


class WrongPassword(AccountError):
    """改密码时给的当前密码不对。"""


class AvatarRejected(AccountError):
    """头像的类型不收、是空文件或太大。`status` 是路由该回的 HTTP 状态。"""

    def __init__(self, key: str, *, status: int) -> None:
        super().__init__(key)
        self.status = status


def authenticate(db: Session, username: str, password: str) -> User | None:
    """用户名(按 `members.normalize_username` 规整)+ 密码对得上就是这个人,对不上一律 None ——
    不区分「没这个人」和「密码错」。"""
    user = db.scalar(select(User).where(User.username == members.normalize_username(username)))
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def login_providers(db: Session, user: User) -> list[str]:
    """这个账号是从哪些第三方登录进来过的。「怎么登进来的」不在 users 行上,在 oauth_identities 里。"""
    return list(
        db.scalars(
            select(OAuthIdentity.provider).where(OAuthIdentity.user_id == user.id).order_by(OAuthIdentity.created_at)
        )
    )


def change_password(db: Session, user: User, *, current: str, new: str, keep: str) -> int:
    """改密码,并把这个人**别处的登录**都踢下线(`keep` 那一份留着,改完不用重新登录)。返回踢掉了几处。"""
    if not verify_password(current, user.password_hash):
        raise WrongPassword("routeErr_currentPasswordWrong")
    user.password_hash = hash_password(new)
    return revoke_other_logins(db, user.id, keep)


def has_users(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(User)))


def update_profile(db: Session, user: User, *, username: str, display_name: str, signature: str) -> User:
    """改自己的用户名、显示名和签名。用户名撞上别人的报 `members.UsernameTaken`。"""
    username = members.normalize_username(username)
    if username != user.username:
        existing = db.scalar(select(User).where(User.username == username, User.id != user.id))
        if existing is not None:
            raise members.UsernameTaken("memberErr_usernameTaken")
    user.username = username
    user.display_name = display_name.strip() or username
    user.signature = signature.strip()
    return user


#: 收哪几种图(content-type → 落盘扩展名),以及多大为止。
AVATAR_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
AVATAR_MAX_BYTES = 4 * 1024 * 1024
_AVATAR_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def set_avatar(db: Session, user: User, *, content_type: str, data: bytes) -> User:
    """上传/替换头像:落 data_dir/avatars/<uid>-<随机 id>.<ext>,每次一个新 key,天然破缓存。

    `data` 由调用方最多读 `AVATAR_MAX_BYTES + 1` 个字节 —— 多一个字节就知道超没超,不必整份读进来。
    旧文件在提交成功后清理;失败也只是留一个孤儿文件,不影响正确性。

    **key 不能用秒级时间戳。** 此前是 `<uid>-<秒>.<ext>`:同一秒里再传一张同类型的(连点两下),新 key 和旧 key
    一模一样 —— 写入覆盖了旧文件,提交后又按「旧 key」清理,删掉的正是刚传上去的那张,库里记着头像、盘上没有文件。
    """
    ext = AVATAR_TYPES.get((content_type or "").lower())
    if ext is None:
        raise AvatarRejected("routeErr_avatarType", status=415)
    if not data:
        raise AvatarRejected("routeErr_emptyFile", status=422)
    if len(data) > AVATAR_MAX_BYTES:
        raise AvatarRejected("routeErr_avatarTooLarge", status=413)
    avatars_dir = settings.data_dir / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    key = f"avatars/{user.id}-{new_id()}.{ext}"
    (settings.data_dir / key).write_bytes(data)
    previous = _avatar_path(user.avatar_key)
    user.avatar_key = key
    if previous is not None:
        after_commit(db, lambda: previous.unlink(missing_ok=True))
    return user


def _avatar_path(key: str | None) -> Path | None:
    """头像 key 在盘上的位置。key 只能落在 avatars/ 下,防目录穿越 —— 库里即便被改坏也不放行,读和删同一道判断。"""
    key = key or ""
    if not key.startswith("avatars/") or "/../" in key or key.endswith(".."):
        return None
    return settings.data_dir / key


def avatar_file(db: Session, user_id: str) -> tuple[Path, str] | None:
    """某人头像在盘上的位置和 media type;没有就是 None。"""
    target = db.get(User, user_id)
    path = _avatar_path(target.avatar_key if target else None)
    if path is None or not path.is_file():
        return None
    return path, _AVATAR_MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream")


def deployment_users(db: Session, actor: User) -> list[dict[str, object]]:
    """这个部署里的所有账号。给部署管理员用 —— 授予/收回那一列需要知道有谁。

    只有部署管理员能看:成员名单在工作区里各自可见,而**跨工作区的全量名单**是部署级信息。
    """
    ensure_deployment_admin(db, actor)
    rows = db.scalars(select(User).order_by(User.created_at.asc()))
    return [
        {
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
            "is_deployment_admin": row.is_deployment_admin,
        }
        for row in rows
    ]


def set_deployment_admin(db: Session, actor: User, user_id: str, *, granted: bool) -> User | None:
    """授予 / 收回「部署管理员」。只有部署管理员能改 —— 能自己给自己发就又回到自助了。

    最后一个部署管理员不能被收回:没有他,实例配置改不了、注册邀请码也发不出来,这个部署就成了
    一块砖头,而且**没有任何应用内的路可以救回来**。目标账号不存在时返回 None。
    """
    ensure_deployment_admin(db, actor)
    target = db.get(User, user_id)
    if target is None:
        return None
    if not granted:
        others = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_deployment_admin.is_(True), User.id != target.id)
        )
        if not others:
            raise LastDeploymentAdmin("routeErr_lastDeploymentAdmin")
    target.is_deployment_admin = bool(granted)
    return target
