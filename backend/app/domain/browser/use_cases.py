"""浏览器档案与智能体浏览器会话的用例:按工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看档案列表不点名权限;建、改、删档案、记下打开过、在会话上跑动作 / 关会话点名 edit。
档案存的是**某人已登录的浏览器**,能不能用还要过 sharing 的归属判据;改、删只认主人,那道闸
(`browser.update_profile` / `delete_profile`,actor 必填)由路由直接点名。不提交事务
(底下的 close_session 仍自己提交:关会话是收尾,不能随调用方回滚)。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import BrowserProfile, BrowserSession, User, now
from app.domain import browser, sharing
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
