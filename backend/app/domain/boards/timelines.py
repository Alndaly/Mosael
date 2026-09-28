"""画板上的时间线格(ADR 0030):格子背后是一条正常的 Mosael 时间线。

时间线必须属于一个项目,画板没有项目 —— 维护者拍板:**每张画板第一次放时间线格时建一个同名项目**,记在画板上
(`boards.project_id`,画板改名不丢),之后这张画板的时间线格都放进去。项目被删了就再建一个。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Board, Project, Sequence
from app.domain.boards.canvas import get_board
from app.domain.projects import create_project

#: 新时间线的默认画幅:横屏 1080p、30 帧。第一段接进来时画幅跟着它走(sequences.append)。
DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS = 1920, 1080, 30.0


def board_project(db: Session, board: Board) -> Project:
    """这张画板的项目:记着的那个还在就用它,不在就建一个同名的。"""
    existing = db.get(Project, board.project_id) if board.project_id else None
    if existing is not None and existing.workspace_id == board.workspace_id:
        return existing
    project = create_project(db, board.workspace_id, board.name)
    board.project_id = project.id
    return project


def create_board_sequence(db: Session, workspace_id: str, board_id: str) -> Sequence:
    """给这张画板建一条新时间线(放进画板的项目),交回它。名字按画板上的第几条起。"""
    from app.domain.sequences import create_sequence_scaffold

    board = get_board(db, workspace_id, board_id)
    project = board_project(db, board)
    count = sum(1 for _ in project.sequences) if project.sequences is not None else 0
    scaffold = create_sequence_scaffold(db, project, name=f"{board.name} · 时间线 {count + 1}",
                                        width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fps=DEFAULT_FPS)
    db.commit()
    db.refresh(scaffold.sequence)
    return scaffold.sequence
