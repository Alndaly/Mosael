"""浏览器档案与智能体浏览器会话的用例:按工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看档案列表不点名权限;建、改、删档案、记下打开过、在会话上跑动作 / 关会话点名 edit。
档案存的是**某人已登录的浏览器**,能不能用还要过 sharing 的归属判据;改、删只认主人,那道闸
(`browser.update_profile` / `delete_profile`,actor 必填)由路由直接点名。不提交事务
(底下的 close_session 仍自己提交:关会话是收尾,不能随调用方回滚)。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import BrowserProfile, BrowserSession, User, now
from app.domain import browser, host_files, sharing
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm

SHARE_KIND = "browser_profile"


def _profile(db: Session, profile_id: str) -> BrowserProfile:
    prof = db.get(BrowserProfile, profile_id)
    if prof is None:
        raise NotVisible("routeErr_browserProfileNotFound")
    return prof


def manageable_profile(db: Session, user: User, profile_id: str) -> BrowserProfile:
    """改、删之前取档案并过工作区的闸;「只认主人」那道在 browser.update_profile / delete_profile 里。"""
    prof = _profile(db, profile_id)
    ensure_workspace_perm(db, user, prof.workspace_id, "edit")
    return prof


# ---------------- 档案 ----------------


def list_profiles(db: Session, user: User, workspace_id: str) -> list[BrowserProfile]:
    """默认只有主人看得见(见 domain/sharing)。"""
    ensure_workspace_access(db, user, workspace_id)
    return [prof for prof in browser.list_profiles(db, workspace_id) if sharing.may_use(db, SHARE_KIND, prof, user.id)]


def create_profile(db: Session, user: User, workspace_id: str, *, name: str, proxy: str | None) -> BrowserProfile:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return browser.create_profile(db, workspace_id=workspace_id, name=name, owner=user, proxy=proxy)


def record_opened(db: Session, user: User, profile_id: str, url: str) -> BrowserProfile:
    """人在应用里用过这个档案:记下它停在哪一页(下次从这里开)和时间。"""
    prof = db.get(BrowserProfile, profile_id)
    if prof is None or not sharing.may_use(db, SHARE_KIND, prof, user.id):
        raise NotVisible("routeErr_browserProfileNotFound")
    ensure_workspace_perm(db, user, prof.workspace_id, "edit")
    prof.start_url = url
    prof.last_used_at = now()
    return prof


# ---------------- 会话 ----------------


def visible_session(db: Session, user: User, session_id: str) -> BrowserSession:
    """看得见的会话:在他能进的工作区里。只用来回答「这是谁开的」,不能拿它动手(动手见 operable_session)。"""
    session = db.get(BrowserSession, session_id)
    if session is None:
        raise NotVisible("routeErr_browserSessionNotFound")
    try:
        ensure_workspace_access(db, user, session.workspace_id)
    except NotVisible:
        raise NotVisible("routeErr_browserSessionNotFound") from None
    return session


# ---------------- 智能体的内联动作 ----------------


def operable_session(db: Session, user: User, workspace_id: str, session_id: str) -> BrowserSession:
    """已经开着、他能在上面动手的会话。

    池档案会话还要他自己能用那个档案 —— 拿到会话 id 不等于有权用别人已登录的浏览器
    (见 browser.attach_session,不能用抛 sharing.NotUsableError)。
    """
    ensure_workspace_perm(db, user, workspace_id, "edit")
    session = browser.attach_session(db, session_id, workspace_id=workspace_id, actor=user.id)
    if session is None:
        raise NotVisible("routeErr_browserSessionNotFound")
    return session


def close_session(db: Session, user: User, workspace_id: str, session_id: str) -> None:
    operable_session(db, user, workspace_id, session_id)
    browser.close_session(db, session_id)


#: 上传等多久(毫秒),调用方没给或给得不像数时用它。
UPLOAD_TIMEOUT_MS = 15_000


def act(db: Session, user: User, workspace_id: str, session_id: str, action: str, args: dict[str, Any]) -> Any:
    """在一个开着的会话上跑一个动作(智能体的 browser_* 工具,经 POST /api/agent-browser/act 或工具层直调)。

    闸只在这里:会话他能动手(`operable_session`)→ 上传的话来源要放行(`upload_into`)→ 交给执行器。
    此前这三步写在路由里,工作流执行器手抄了第二步、拦的错误还不一样多。只抛领域错误。
    """
    operable_session(db, user, workspace_id, session_id)
    if action != "upload":
        return browser.run_action(session_id, action, args)
    return upload_into(
        db,
        session_id,
        workspace_id=workspace_id,
        actor_id=user.id,
        asset_id=str(args.get("asset_id") or ""),
        path=str(args.get("path") or ""),
        selector=str(args.get("selector") or ""),
        frame=str(args.get("frame") or ""),
        timeout_ms=_timeout_ms(args.get("timeout_ms")),
    )


def upload_into(
    db: Session,
    session_id: str,
    *,
    workspace_id: str,
    actor_id: str | None,
    asset_id: str = "",
    path: str = "",
    selector: str = "",
    frame: str = "",
    timeout_ms: int = UPLOAD_TIMEOUT_MS,
    should_stop: Callable[[], bool] | None = None,
) -> Any:
    """往会话里的 <input type=file> 塞一个文件。素材和本机路径只能给一个,都经 domain/host_files 放行。

    不放行就把来源原样交给执行器的话,`{"path": "~/.ssh/id_rsa"}` 就能把这台电脑上的私钥塞进任意网页。
    拒绝抛 `HostFileError` / `HostFileNotAllowed` / `NotVisible`,执行失败抛 `BrowserDomainError` —— 调用方按类型分。
    会话能不能动手由调用方先过(智能体走 `act`,工作流的会话是这次运行自己开的)。
    """
    file = host_files.upload_source(db, workspace_id=workspace_id, asset_id=asset_id, path=path, actor=actor_id)
    return browser.upload_file(
        session_id, file, selector=selector, frame=frame, timeout_ms=timeout_ms, should_stop=should_stop
    )


def _timeout_ms(value: Any) -> int:
    try:
        return int(float(value or UPLOAD_TIMEOUT_MS))
    except (TypeError, ValueError):
        return UPLOAD_TIMEOUT_MS
