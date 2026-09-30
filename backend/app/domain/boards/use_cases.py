"""画板的用例:谁看得见哪些画板、谁能建改删、画板上能跑哪些产出者(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看只要是成员;建、改、删、复制、放时间线格都要 `edit`;跑一个产出者要什么由产出者自己声明。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Board, Sequence, User
from app.domain.boards import producers
from app.domain.boards.canvas import create_board, delete_board, duplicate_board, get_board, list_boards, update_board
from app.domain.boards.persistence import board_summary
from app.domain.boards.receipts import revived_runs, settle_revived_runs
from app.domain.boards.timelines import create_board_sequence
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm, owning_workspace


def list_all(db: Session, user: User, workspace_id: str) -> list[dict[str, Any]]:
    """清单:每张板一份摘要(见 board_summary),整份画布打开时由详情接口给。"""
    ensure_workspace_access(db, user, workspace_id)
    return [board_summary(board) for board in list_boards(db, workspace_id)]


def read(db: Session, user: User, board_id: str, workspace_id: str | None = None) -> Board:
    """`workspace_id` 可选 —— 画板自带归属;带上时仍按它查(跨工作区的 id 读不出来)。"""
    workspace_id = workspace_id or owning_workspace(db, Board, board_id)
    ensure_workspace_access(db, user, workspace_id)
    return get_board(db, workspace_id, board_id)


def producers_for(db: Session, user: User, workspace_id: str, locale: str) -> list[dict[str, Any]]:
    """画板上**这个人**能用的产出者(插件工具只列他自己接的),按 `locale` 翻好。"""
    ensure_workspace_access(db, user, workspace_id)
    return producers.describe(db, user.id, locale)


# ---------------- 写 ----------------


def create(db: Session, user: User, workspace_id: str, *, name: str, canvas: dict[str, Any] | None) -> Board:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return create_board(db, workspace_id=workspace_id, name=name, canvas=canvas, actor_id=user.id)


def create_timeline(db: Session, user: User, workspace_id: str, board_id: str, *, copy_of: str | None = None) -> Sequence:
    """放一格时间线格之前先建好它那条时间线(放进这张画板的项目,ADR 0030);复制一格时是照原件复制一条。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return create_board_sequence(db, workspace_id, board_id, copy_of=copy_of)


def duplicate(db: Session, user: User, workspace_id: str, board_id: str, *, name: str) -> Board:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return duplicate_board(db, workspace_id=workspace_id, board_id=board_id, name=name, actor_id=user.id)


def update(
    db: Session,
    user: User,
    workspace_id: str,
    board_id: str,
    *,
    name: str | None,
    canvas: dict[str, Any] | None,
    base_revision: int,
) -> Board:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    before = get_board(db, workspace_id, board_id).canvas
    board = update_board(
        db,
        workspace_id=workspace_id,
        board_id=board_id,
        name=name,
        canvas=canvas,
        base_revision=base_revision,
        actor_id=user.id,
    )
    #: 客户端带回来的「在跑」(删掉又撤销回来的格子),任务其实已经结束:当场补送回执(见 receipts.settle_revived_runs)。
    revived = revived_runs(before, board.canvas) if canvas is not None else {}
    if revived:
        settle_revived_runs(db, workspace_id, board_id, revived)
        board = get_board(db, workspace_id, board_id)
    return board


def delete(db: Session, user: User, workspace_id: str, board_id: str) -> None:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    delete_board(db, workspace_id, board_id, actor_id=user.id)


def run(db: Session, user: User, workspace_id: str, board_id: str, *, producer: str, **request: Any) -> Board:
    """在画板上跑一个产出者(见 producers.run)。跑它要什么权限由产出者声明;插件工具用的是**这个人**自己的连接。"""
    chosen = producers.get_producer(db, producer, user.id)
    ensure_workspace_perm(db, user, workspace_id, chosen.permission)
    return producers.run(
        db,
        producers.RunRequest(
            workspace_id=workspace_id, board_id=board_id, actor_id=user.id, producer=chosen.id, **request
        ),
    )
