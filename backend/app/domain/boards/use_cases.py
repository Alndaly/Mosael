"""画板的用例:谁看得见哪些画板、谁能建改删、画板上能跑哪些产出者(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看只要是成员;建、改、删、复制、放时间线格都要 `edit`;跑一个产出者要什么由产出者自己声明。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Board, Sequence, User
from app.domain.boards import producers
from app.domain.boards.canvas import (
    BoardRevisionConflict, create_board, delete_board, duplicate_board, get_board, list_boards, update_board,
)
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


#: 追加撞上并发写入时重读当前画布再落几次。追加一格和别处的编辑可交换,重读就能解决;给上限只是不在病态争用下打转。
APPEND_RETRIES = 4


def append_note(
    db: Session, user: User, workspace_id: str, board_id: str, *, text: str, source_note: dict[str, Any] | None,
) -> tuple[Board, str]:
    """往画板上追加一张便签(笔记选区工具条的「加到画板」),返回 (画板, 新那一格的 id)。

    **落在当前画布上**,不拿调用方手里的一份快照:笔记页根本没打开这张板,它手里的版本号只会把一次可以并存的
    追加判成冲突。位置照 add_item 的缺省 —— 摆在所有格子的右边,不压住任何一格。写入本身仍是带版本号的条件写
    (update_board),撞上真正的并发写就重读再追加。
    """
    from app.domain.boards.ops import apply_board_ops

    ensure_workspace_perm(db, user, workspace_id, "edit")
    for attempt in range(APPEND_RETRIES):
        board = get_board(db, workspace_id, board_id)
        before = board.canvas or {}
        canvas = apply_board_ops(before, [{"kind": "add_item", "type": "note", "text": text}])
        added = canvas["items"][-1]
        if source_note is not None:
            added["source_note"] = source_note
        try:
            board = update_board(db, workspace_id=workspace_id, board_id=board_id, canvas=canvas,
                                 base_revision=board.revision, actor_id=user.id)
        except BoardRevisionConflict:
            if attempt == APPEND_RETRIES - 1:
                raise
            db.expire_all()
            continue
        return board, str(added["id"])
    raise AssertionError("unreachable")  # pragma: no cover


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
