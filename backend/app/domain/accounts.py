"""账号本身:建号、凭用户名密码认人、改自己的资料与头像、改密与重置、删号、部署管理员名单。

`members` 管的是「谁在哪个工作区、怎么被邀请进来」;这里管的是那个人的账号行,从建出来到删掉。此前这些规则写在
`api/routes/auth.py` 里(用户名撞车、最后一个部署管理员不能收回、头像的类型与大小),路由成了第二个
领域层 —— 别的入口要做同样的事就得再抄一遍。

领域只改对象,提交交给入口层(见 core/unit_of_work)。需要等提交成功之后才能做的(删旧头像文件)
用 `after_commit` 登记。
"""

from __future__ import annotations

import secrets
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import LocalizedError, tr
from app.core.security import hash_password, revoke_other_logins, verify_password
from app.core.unit_of_work import after_commit
from app.db.models import AuthSession, OAuthIdentity, User, WorkspaceMember, new_id
from app.domain import deployment, members
from app.domain.usernames import normalize_username
from app.domain.permissions import ensure_deployment_admin


class AccountError(LocalizedError):
    """账号操作被规则拦下。路由按子类翻成对应的 HTTP 状态。"""


class LastDeploymentAdmin(AccountError):
    """要收回的是最后一个部署管理员。"""


class WrongPassword(AccountError):
    """改密码时给的当前密码不对。"""


class AccountNotFound(AccountError):
    """部署管理员要操作的那个账号不存在。"""


class ResetOwnPassword(AccountError):
    """部署管理员想在管理页里重置自己的密码 —— 那会把自己踢下线;改自己的密码走「设置 → 账户」(要旧密码)。"""


class SignupClosed(AccountError):
    """这个部署不收自助注册,也没带一个还能用的邀请码。"""


class UsernameTaken(AccountError):
    """用户名已经有人用了。"""


class AccountInSharedWorkspaces(AccountError):
    """要删的账号还在有别人的工作区里:那里面有同事的东西,先去转让或移出。"""


class AvatarRejected(AccountError):
    """头像的类型不收、是空文件或太大。`status` 是路由该回的 HTTP 状态。"""

    def __init__(self, key: str, *, status: int) -> None:
        super().__init__(key)
        self.status = status


def create_account(db: Session, *, username: str, display_name: str, password: str | None, invite_code: str = "") -> User:
    """建一个账号。本地注册和第三方登录第一次进来**都走这里**。

    此前两处各建各的,而第三方登录那处不看注册闸门:部署关掉自助注册之后,只要配了 Google /
    Apple 登录,任何人照样能进来 —— 正是 ADR 0008 §0 那条提权链的第一环。

    **引导之后转邀请制**:空库时照常放行 —— 那时没有任何人能发邀请,而没有部署管理员的部署是块
    砖头,所以第一个账号成为部署管理员,并认领登录之前建的工作区。之后要么部署开放注册,要么带
    一个还能用的邀请码(一次性:用掉就作废)。

    `password` 为 None 是第三方账号:没有本地口令,填一个不可用的随机散列,密码登录天然走不通。
    flush 拿到 id,提交交给调用方 —— 会话行要和账号一起进库。
    """
    bootstrapping = db.scalar(select(User).limit(1)) is None
    invite = members.usable_invite(db, invite_code)
    if not bootstrapping and not deployment.open_registration(db):
        if invite is None:
            #: 填了码却用不了,和压根没填是两回事:手里有码的人(抄错一位、过了一周、被别人先用了)此前也被告知
            #: 「去要一个邀请码」,不知道是码的问题(体检 UM-09)。
            raise SignupClosed("routeErr_inviteCodeUnusable" if (invite_code or "").strip() else "routeErr_signupClosed")
        if not members.link_allows_signup(db, invite):
            #: 工作区管理员发的链接只管进工作区,进部署那道门还没人点头(ADR 0054 D48)。
            raise SignupClosed("routeErr_inviteLinkNeedsDeploymentAdmin")
    username = normalize_username(username)
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise UsernameTaken("memberErr_usernameTaken")
    user = User(
        username=username,
        display_name=display_name.strip() or username,
        signature="",
        password_hash=hash_password(password if password is not None else secrets.token_hex(24)),
        is_deployment_admin=bootstrapping,
    )
    db.add(user)
    db.flush()
    members.adopt_orphan_workspaces(db, user)
    if invite is not None:
        #: 带着工作区的链接,注册完直接是那个工作区的成员 —— 不经过「先建一个自己的工作区」那一步。
        members.use_invite_link(db, invite, user)
    return user


#: 管理员重置时生成的临时密码多长(token_urlsafe 的字节数,出来是 16 个字符)。
_TEMP_PASSWORD_BYTES = 12


def reset_password(db: Session, user: User, password: str | None = None) -> str:
    """给一个账号换一个新密码,并让他已经登录着的会话全部失效。返回新密码的原文(只这一次,库里存的是哈希)。

    忘了密码的人此前没有任何路:登录页没有入口,部署管理员也改不了别人的密码,只能删号重来 —— 连他的对话、密钥、
    只有他一个人的工作区一起没了;唯一的部署管理员忘了密码就整台锁死。现在两条路:管理页「重置密码」(部署管理员
    替成员换)、后端命令行 `reset-password`(兜唯一管理员被锁在外面,见 app/cli)。

    `password` 为 None 时生成一个随机的临时密码 —— 交给对方,他登录后在「设置 → 账户」里改成自己的。不提交。
    """
    chosen = password if password is not None else secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)
    user.password_hash = hash_password(chosen)
    #: 旧会话一起作废:要重置往往是因为账号可能落在别人手上,换了密码而旧令牌照样能用就白换了。
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(synchronize_session=False)
    db.flush()
    return chosen


#: 指向"某个人"的列。删账号时要跟着走的就是这些 —— **按 schema 认,不手写清单**:
#: 新加一张带 owner_user_id 的表时,手写清单不会有任何东西提醒你漏了它,而漏掉的那些行会
#: 变成指向不存在的人的孤儿(这些列有意不设外键,见 db.models)。
PERSON_COLUMNS = ("user_id", "owner_user_id")


def _tables_pointing_at_a_person() -> list[tuple[str, str]]:
    from app.db.models import Base

    return [
        (table.name, column.name)
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if column.name in PERSON_COLUMNS
    ]


def delete_user_account(db: Session, user: User) -> None:
    """删掉这个账号,以及只属于他的那些东西。

    **他独占的工作区跟着他走**(里面只有他自己的内容,留着就是一堆没人看得见的行);**还有别人
    在的不跟着走** —— 那里面有同事的素材、时间线、对话,宁可让管理员先去转让,也不要一次点击
    毁掉别人的工作。

    删的范围按 schema 推导(见 PERSON_COLUMNS),不手写清单:`agent_sessions.owner_user_id`
    这类列有意不设外键,手写清单漏掉一张表不会有任何东西报错,只会留下指向不存在的人的孤儿行。

    和「不能收回最后一个部署管理员」同一条:最后一个管理员不能删,否则这台部署没人管了。
    """
    with members.MEMBERSHIP_LOCK:
        if user.is_deployment_admin and _is_last_deployment_admin(db, user):
            raise LastDeploymentAdmin("memberErr_lastDeploymentAdmin")
        blocked = members.shared_workspaces(db, user.id)
        if blocked:
            names = tr("punct_listSep").join(w.name for w in blocked)
            raise AccountInSharedWorkspaces("memberErr_sharedWorkspaces", names=names)

        #: 独占的工作区走和「删工作区」同一条路:行靠外键 CASCADE 走,文件(素材、音色、LUT、字体、3D 模型、技能)在
        #: 提交之后清。此前这里直接 `db.delete(workspace)`,绕过了那条路 —— 文件一个都没清。
        for workspace in members.solo_workspaces(db, user.id):
            members.delete_workspace(db, workspace.id)
        db.flush()
        from app.domain.storage_cleanup import delete_user_files

        avatar_key = user.avatar_key
        after_commit(db, lambda: delete_user_files(avatar_key))

        # 剩下的按列扫。users 那一行留到最后 —— 有 CASCADE 的表会自己走,没有的在这里清掉。
        for table, column in _tables_pointing_at_a_person():
            if table == "users":
                continue
            db.execute(text(f"DELETE FROM {table} WHERE {column} = :uid"), {"uid": user.id})
        db.delete(user)
        db.commit()


def authenticate(db: Session, username: str, password: str) -> User | None:
    """用户名(按 `usernames.normalize_username` 规整)+ 密码对得上就是这个人,对不上一律 None ——
    不区分「没这个人」和「密码错」。"""
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
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
    """改自己的用户名、显示名和签名。用户名撞上别人的报 `UsernameTaken`。"""
    username = normalize_username(username)
    if username != user.username:
        existing = db.scalar(select(User).where(User.username == username, User.id != user.id))
        if existing is not None:
            raise UsernameTaken("memberErr_usernameTaken")
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


def people_overview(db: Session, actor: User) -> list[dict[str, object]]:
    """管理员控制台的成员一览:身份、最近在用吗、跑的是哪一版、在几个工作区里。只有部署管理员能看。

    版本取他**最近一次**用到的那份凭据上报的 —— 一个人可以同时开着桌面端和网页端,而管理员
    要回答的是"他现在跑的是哪一版"。
    """
    ensure_deployment_admin(db, actor)
    latest: dict[str, AuthSession] = {}
    for session in db.scalars(select(AuthSession).order_by(AuthSession.last_seen_at)):
        if session.last_seen_at is not None:
            latest[session.user_id] = session  # 按 last_seen 升序,最后一条即最新
    workspaces = dict(
        db.execute(select(WorkspaceMember.user_id, func.count()).group_by(WorkspaceMember.user_id)).all()
    )
    rows: list[dict[str, object]] = []
    for person in db.scalars(select(User).order_by(User.created_at)):
        seen = latest.get(person.id)
        rows.append({
            "id": person.id,
            "username": person.username,
            "display_name": person.display_name,
            "is_deployment_admin": person.is_deployment_admin,
            "created_at": person.created_at,
            "last_seen_at": seen.last_seen_at if seen is not None else None,
            "client_version": seen.client_version if seen is not None else "",
            "client_surface": seen.client_surface if seen is not None else "",
            "workspaces": int(workspaces.get(person.id, 0)),
        })
    return rows


def _is_last_deployment_admin(db: Session, user: User) -> bool:
    """除了他再没有别的部署管理员。收回管理员和删号都不许走到这一步:没有部署管理员的部署是一块砖头。"""
    others = db.scalar(
        select(func.count()).select_from(User).where(User.is_deployment_admin.is_(True), User.id != user.id)
    )
    return not others


def _managed_account(db: Session, actor: User, user_id: str) -> User:
    """部署管理员要操作的那个账号:先认人,再取;不存在抛 AccountNotFound。"""
    ensure_deployment_admin(db, actor)
    target = db.get(User, user_id)
    if target is None:
        raise AccountNotFound("routeErr_accountNotFound")
    return target


def delete_member_account(db: Session, actor: User, user_id: str) -> None:
    """部署管理员删掉一个账号,以及只属于他的那些东西(规则见 delete_user_account,删不了抛 AccountError 的子类)。"""
    delete_user_account(db, _managed_account(db, actor, user_id))


def reset_member_password(db: Session, actor: User, user_id: str) -> str:
    """部署管理员替一个成员重置密码:生成一个临时密码(只这一次给出),他已经登录着的会话全部作废。

    忘了密码的人此前只能被删号重来。不能用在自己身上(见 ResetOwnPassword)。
    """
    target = _managed_account(db, actor, user_id)
    if target.id == actor.id:
        raise ResetOwnPassword("routeErr_resetOwnPassword")
    return reset_password(db, target)


def set_deployment_admin(db: Session, actor: User, user_id: str, *, granted: bool) -> User | None:
    """授予 / 收回「部署管理员」。只有部署管理员能改 —— 能自己给自己发就又回到自助了。

    最后一个部署管理员不能被收回:没有他,实例配置改不了、注册邀请码也发不出来,这个部署就成了
    一块砖头,而且**没有任何应用内的路可以救回来**。目标账号不存在时返回 None。
    """
    ensure_deployment_admin(db, actor)
    target = db.get(User, user_id)
    if target is None:
        return None
    if not granted and _is_last_deployment_admin(db, target):
        raise LastDeploymentAdmin("routeErr_lastDeploymentAdmin")
    target.is_deployment_admin = bool(granted)
    return target
