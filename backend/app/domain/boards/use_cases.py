"""画板的读用例:谁看得见哪些画板、画板上能用哪些产出者(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

写(建、改、跑格子)的闸暂时还在路由里,随后按同一条规矩迁过来(tests/test_use_case_boundaries_ratchet)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Board, User
from app.domain.boards import producers
from app.domain.boards.canvas import get_board, list_boards
from app.domain.permissions import ensure_workspace_access, owning_workspace


def list_all(db: Session, user: User, workspace_id: str) -> list[Board]:
    ensure_workspace_access(db, user, workspace_id)
    return list_boards(db, workspace_id)


def read(db: Session, user: User, board_id: str, workspace_id: str | None = None) -> Board:
    """`workspace_id` 可选 —— 画板自带归属;带上时仍按它查(跨工作区的 id 读不出来)。"""
    workspace_id = workspace_id or owning_workspace(db, Board, board_id)
    ensure_workspace_access(db, user, workspace_id)
    return get_board(db, workspace_id, board_id)


def producers_for(db: Session, user: User, workspace_id: str, locale: str) -> list[dict[str, Any]]:
    """画板上**这个人**能用的产出者(插件工具只列他自己接的),按 `locale` 翻好。"""
    ensure_workspace_access(db, user, workspace_id)
    return producers.describe(db, user.id, locale)
