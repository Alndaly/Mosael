"""画板上的时间线格(ADR 0030):格子背后是一条正常的 Mosael 时间线。

智能体(edit_board)也能放一格新的时间线、把格子连进来接到末尾:建时间线和接片段都是批准之后才做的事,
算子本身是纯的(boards.ops),见下面的 create_pending_sequences / append_connected_media。

时间线必须属于一个项目,画板没有项目 —— 维护者拍板:**每张画板第一次放时间线格时建一个同名项目**,记在画板上
(`boards.project_id`,画板改名不丢),之后这张画板的时间线格都放进去。项目被删了就再建一个。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Sequence
from app.domain.boards.canvas import board_project, get_board

#: 新时间线的默认画幅:横屏 1080p、30 帧。第一段接进来时画幅跟着它走(sequences.append)。
DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS = 1920, 1080, 30.0


def create_board_sequence(db: Session, workspace_id: str, board_id: str, *, copy_of: str | None = None) -> Sequence:
    """给这张画板建一条新时间线(放进画板的项目),交回它。名字按画板上的第几条起。

    `copy_of`:照着这条时间线复制一条(画板上复制一格时间线格)。**副本不和原件共用一条** —— 共用的话在副本里
    剪一刀,原件那一格跟着变,两边的撤销还会互相撤掉对方的步骤;和整板复制(persistence._copy_timelines)同一条。
    """
    from app.domain.boards.errors import BoardDomainError
    from app.domain.sequences import copy_sequence, create_sequence_scaffold

    board = get_board(db, workspace_id, board_id)
    project = board_project(db, board)
    if copy_of:
        source = db.get(Sequence, copy_of)
        if source is None or source.workspace_id != workspace_id:
            raise BoardDomainError("boardErr_sequenceNotInWorkspace")
        copy = copy_sequence(db, source, project, name=source.name)
        db.flush()
        db.refresh(copy)
        return copy
    count = sum(1 for _ in project.sequences) if project.sequences is not None else 0
    scaffold = create_sequence_scaffold(db, project, name=f"{board.name} · 时间线 {count + 1}",
                                        width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fps=DEFAULT_FPS)
    db.flush()
    db.refresh(scaffold.sequence)
    return scaffold.sequence


def pending_sequence_ops(operations: list[Any]) -> list[dict[str, Any]]:
    """这一批算子里「放一格新的时间线」的那几条:`add_item` 时间线格、没带 `sequence_id`(智能体的 edit_board)。"""
    return [op for op in operations if isinstance(op, dict) and op.get("kind") == "add_item"
            and op.get("type") == "sequence" and not str(op.get("sequence_id") or "").strip()]


def create_pending_sequences(db: Session, workspace_id: str, board_id: str, operations: list[Any]) -> list[Any]:
    """给这一批里「放一格新的时间线」的每一条先建好时间线(放进画板的项目,和界面上「新建 → 时间线」同一个函数),
    把 id 写进算子;没起名的格子用时间线的名字。**只在批准之后调** —— 干跑不建行(见 without_pending_sequences)。"""
    written = [dict(op) if isinstance(op, dict) else op for op in operations]
    for op in pending_sequence_ops(written):
        sequence = create_board_sequence(db, workspace_id, board_id)
        op["sequence_id"] = sequence.id
        if not op.get("text"):
            op["text"] = sequence.name
    return written


def without_pending_sequences(canvas: dict[str, Any]) -> dict[str, Any]:
    """干跑用的画布:还没建时间线的新时间线格(和连着它的线)先拿掉 —— 它们的时间线批准之后才建,别的都照常查。"""
    pending = {str(item.get("id")) for item in canvas.get("items") or []
               if item.get("kind") == "sequence" and not item.get("sequence_id")}
    if not pending:
        return canvas
    return {
        **canvas,
        "items": [item for item in canvas.get("items") or [] if str(item.get("id")) not in pending],
        "edges": [edge for edge in canvas.get("edges") or []
                  if str(edge.get("source")) not in pending and str(edge.get("target")) not in pending],
    }


def append_connected_media(db: Session, workspace_id: str, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """新连进时间线格的视频 / 图片 / 音频格:把它的素材接到那条时间线末尾 —— 和界面上拉一根线同一件事(ADR 0030 §3)。
    原来就连着的不再接一遍;空槽(还没有素材)没什么可接。交回接上的片段 id。"""
    from app.domain.sequences.append import append_asset

    old = {(str(edge.get("source")), str(edge.get("target"))) for edge in before.get("edges") or []}
    by_id = {str(item.get("id")): item for item in after.get("items") or []}
    placed: list[str] = []
    for edge in after.get("edges") or []:
        pair = (str(edge.get("source")), str(edge.get("target")))
        source, target = by_id.get(pair[0]), by_id.get(pair[1])
        if pair in old or not source or not target or target.get("kind") != "sequence" or not target.get("sequence_id"):
            continue
        if source.get("kind") not in ("video", "image", "audio") or not source.get("asset_id"):
            continue
        sequence = db.get(Sequence, str(target["sequence_id"]))
        if sequence is None or sequence.workspace_id != workspace_id:
            continue
        placed.append(append_asset(db, sequence.id, str(source["asset_id"])).id)
    return placed
