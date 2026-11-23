"""浏览器档案「给人看的那一张卡」:档案本身 + 绑在它上面的发布账号 + 这是不是我的、共享了没有。

浏览器池页面与智能体的 list_browser_profiles 读的是同一份(此前这段组装长在路由里,智能体工具只能
借道调路由函数本体)。档案存的是**某人已登录的浏览器**,列表默认只有主人看得见(见 domain/sharing)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import BrowserProfile, User
from app.domain import publish, sharing
from app.domain.browser.use_cases import SHARE_KIND, list_profiles


def card(db: Session, prof: BrowserProfile, user: User, shared: set[str]) -> dict[str, Any]:
    """一张卡。`shared` 是这个工作区里共享出来的档案 id(调用方查一次,列表里每张共用)。"""
    account = publish.account_on_profile(db, prof.id)
    return {
        "id": prof.id,
        "workspace_id": prof.workspace_id,
        "name": prof.name,
        "partition": prof.partition,
        "proxy": prof.proxy,
        "enabled": prof.enabled,
        "last_used_at": prof.last_used_at,
        "start_url": prof.start_url,
        "identity": prof.identity,
        "created_at": prof.created_at,
        # 被发布账号绑着的档案,池页面据此标注平台 / 账号,和通用档案区分开。
        "platform": account.platform if account else None,
        "bound_account_id": account.id if account else None,
        "binding_status": account.binding_status if account else None,
        "last_checked_at": account.last_checked_at if account else None,
        "last_error": account.last_error if account else None,
        "is_mine": prof.owner_user_id == user.id,
        "shared": prof.id in shared,
    }


def card_of(db: Session, prof: BrowserProfile, user: User) -> dict[str, Any]:
    """单独一张(建、改、记下打开过之后回给界面)。"""
    return card(db, prof, user, sharing.shared_ids(db, SHARE_KIND, prof.workspace_id))


def list_cards(db: Session, user: User, workspace_id: str) -> list[dict[str, Any]]:
    """他在这个工作区里看得见的档案。"""
    shared = sharing.shared_ids(db, SHARE_KIND, workspace_id)
    return [card(db, prof, user, shared) for prof in list_profiles(db, user, workspace_id)]
