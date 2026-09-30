"""画板的读写:列出、读取、版本检查、新建、复制、比较并交换的保存、删除。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import references
from app.db.models import Board, now
from app.domain.boards.errors import BoardDomainError, BoardNotFound, BoardRevisionConflict
from app.domain.boards.run_state import _keep_server_owned_state, live_job
from app.domain.boards.shape import normalize_canvas
from app.domain.boards.validation import _validate_references, check_canvas


def list_boards(db: Session, workspace_id: str) -> list[Board]:
    return list(
        db.scalars(
            select(Board).where(Board.workspace_id == workspace_id).order_by(Board.updated_at.desc())
        )
    )


def get_board(db: Session, workspace_id: str, board_id: str) -> Board:
    board = db.get(Board, board_id)
    # 按工作区再验一次:拿到别的工作区的 id 也不该读得出来。
    if board is None or board.workspace_id != workspace_id:
        raise BoardNotFound("boardErr_notFound")
    return board


def ensure_revision(board: Board, base_revision: int | None) -> None:
    """调用方看到的是不是最新的这张板。**起任务之前**就要问 —— 等占位落地时才发现冲突,
    任务已经起了、钱已经花了,而产出没有地方放。"""
    if base_revision is not None and base_revision != board.revision:
        raise BoardRevisionConflict(base_revision, board.revision)


def create_board(
    db: Session,
    *,
    workspace_id: str,
    name: str,
    canvas: Any = None,
    actor_id: str | None = None,
    copied_from: dict[str, Any] | None = None,
) -> Board:
    """`copied_from`:这张板照着哪份画布复制来的。那份上已有的引用算已知(见 _validate_references)。"""
    board = Board(
        workspace_id=workspace_id,
        name=(name or "").strip() or "新画板",
        canvas=check_canvas(db, workspace_id, canvas, copied_from),
    )
    db.add(board)
    db.flush()
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="board.created",
        subject_type="board",
        subject_id=board.id,
        summary="创建了无限画布",
        payload={"revision": board.revision},
    )
    db.refresh(board)
    return board


def board_project(db: Session, board: Board) -> Any:
    """这张画板的项目(放它的时间线格的时间线,ADR 0030):记着的那个还在就用它,不在就建一个同名的。"""
    from app.db.models import Project
    from app.domain.projects import create_project

    existing = db.get(Project, board.project_id) if board.project_id else None
    if existing is not None and existing.workspace_id == board.workspace_id:
        return existing
    project = create_project(db, board.workspace_id, board.name)
    board.project_id = project.id
    return project


def _copy_timelines(db: Session, board: Board) -> None:
    """副本上的时间线格各自复制一条时间线,放进副本自己的项目。**不和原板共用**:共用的话在副本里剪一刀,
    原板那一格跟着变,两边的撤销还会互相撤掉对方的步骤。原来那条已经不在的格子照原样留着(和原板一样是空的)。"""
    from app.db.models import Sequence
    from app.domain.sequences import copy_sequence

    canvas = json.loads(json.dumps(board.canvas or {}))
    copied: dict[str, str] = {}
    for item in canvas.get("items") or []:
        old = str(item.get("sequence_id") or "") if item.get("kind") == "sequence" else ""
        if not old:
            continue
        if old not in copied:
            source = db.get(Sequence, old)
            if source is None or source.workspace_id != board.workspace_id:
                continue
            copied[old] = copy_sequence(db, source, board_project(db, board), name=source.name).id
        item["sequence_id"] = copied[old]
    if copied:
        board.canvas = canvas
        db.flush()
        db.refresh(board)


def duplicate_board(
    db: Session, *, workspace_id: str, board_id: str, name: str = "", actor_id: str | None = None
) -> Board:
    """复制一张画板:同样的项、连线和标记,落成新的一张。

    **在跑的那几格不带过去。** 生成任务的回执认的是原板(见 receipt_to_item,board_id 写死在
    任务的 payload 里),便签写作也只写回原板那一格;副本里留着「在跑」的话,那一格永远等不到
    结束 —— 框里一直转圈,底下的提交键一直按不动。判据是**状态**(排队/运行中),不是有没有
    job_id:客户端的快照里在跑的那一格不一定带着 job_id,照样只落回原件。它们在副本里退回空槽:提示词和参数都还在,
    想要的话再点一次。前端「复制选中项」是同一条规则(boardItemState.copiedItem)。

    评论不跟着走:它们是对**那一张**的讨论,挂在原板的 subject_id 上。名字由调用方给(「× 副本」
    是界面语言里的一句话,这一层不替它挑语言);没给就沿用原名。

    时间线格背后的时间线复制一份放进副本自己的项目(见 `_copy_timelines`),不和原板共用。
    """
    source = get_board(db, workspace_id, board_id)
    canvas = json.loads(json.dumps(source.canvas or {}))
    for item in canvas.get("items") or []:
        run = item.get("run")
        if isinstance(run, dict) and run.get("status") in ("queued", "running"):
            item.pop("run")
    board = create_board(
        db,
        workspace_id=workspace_id,
        name=(name or "").strip() or source.name,
        canvas=canvas,
        actor_id=actor_id,
        copied_from=source.canvas,
    )
    _copy_timelines(db, board)
    return board


def update_board(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    name: str | None = None,
    canvas: Any = None,
    base_revision: int | None = None,
    actor_id: str | None = None,
    server_write: bool = False,
) -> Board:
    """改名和改画布是同一个入口,因为它们都是"这张板变了"。

    **两者都可以单独传**:自动保存只发 canvas,重命名只发 name —— 各发各的那一半,
    另一半不该被 None 覆盖掉。

    `server_write`:这一次写入是服务端**自己对某一格的合并**(摆生成占位、便签开始写、回执),
    不是客户端存回来的快照。那种写入不过 `_keep_server_owned_state` —— 那道闸防的是客户端
    拿着旧快照改动运行态,而服务端这几种写入本来就是在改运行态:重新生成时库里正好是上一轮的
    终态,新一轮的 running 会被当成旧快照打回去(后端新任务照常跑、照常扣钱,画布上却还挂着
    上次的失败);回执要把 running 收成终态,同样不能被「运行态归服务端」挡住。
    """
    board = get_board(db, workspace_id, board_id)
    expected = board.revision if base_revision is None else base_revision
    if expected != board.revision:
        raise BoardRevisionConflict(expected, board.revision)
    next_name = board.name
    next_canvas = board.canvas
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BoardDomainError("boardErr_nameEmpty")
        next_name = cleaned
    if canvas is not None:
        normalized = normalize_canvas(canvas)
        #: 替客户端补回服务端归属的字段之后**再过一遍形状**:补回来的东西和客户端这一份拼在一起,也得是一份
        #: 合法的画布 —— 否则落了库,这张板以后每一次保存都被 normalize 拒掉,用户什么都存不下。
        next_canvas = normalized if server_write else normalize_canvas(_keep_server_owned_state(board.canvas, normalized))
        _validate_references(db, workspace_id, next_canvas, board.canvas, assets=not server_write)
    if next_name == board.name and next_canvas == board.canvas:
        return board
    revived = {} if server_write or canvas is None else _revived_runs(board.canvas, next_canvas)
    result = db.execute(
        update(Board)
        .where(
            Board.id == board_id,
            Board.workspace_id == workspace_id,
            Board.revision == expected,
        )
        .values(name=next_name, canvas=next_canvas, revision=Board.revision + 1, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if int(result.rowcount or 0) != 1:
        db.rollback()
        current = get_board(db, workspace_id, board_id)
        raise BoardRevisionConflict(expected, current.revision)
    references.resync(db, "board", board_id)
    from app.domain.collaboration import record_activity

    action = "board.renamed" if name is not None and canvas is None else "board.updated"
    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        subject_type="board",
        subject_id=board_id,
        summary="重命名了无限画布" if action == "board.renamed" else "编辑了无限画布",
        payload={"base_revision": expected, "revision": expected + 1},
    )
    # 这一次提交暂时留着:比较并交换撞车时上面要 rollback 重读,而任务总线送画板回执
    # (jobs._after_jobs_settled → deliver_generated)调完不替送信方提交 —— 两处都靠这里落库。
    db.commit()
    db.expire_all()
    if revived:
        _settle_revived_runs(db, workspace_id, board_id, revived)
    return get_board(db, workspace_id, board_id)


def _revived_runs(stored: Any, saved: dict[str, Any]) -> dict[str, str]:
    """这一次保存**由客户端带回来**的在跑的格子:`{格子 id: 任务 id}`。库里那一格此前不在跑这个任务(多半是
    整格不在 —— 删掉之后撤销回来的)。"""
    before = {str(item.get("id")): live_job(item) for item in ((stored or {}).get("items") or [])}
    return {
        str(item["id"]): job
        for item in saved.get("items") or []
        if (job := live_job(item)) and before.get(str(item.get("id"))) != job
    }


def _settle_revived_runs(db: Session, workspace_id: str, board_id: str, revived: dict[str, str]) -> None:
    """客户端带回来的在跑的格子,任务其实**已经结束**:当场补送那封回执。

    删掉一格在跑的,任务结束时回执找不到那一格,就丢了(outputs._canvas_with_delivered_result 只收它自己那一轮);
    之后撤销把那一格带回来,它就永远转圈 —— 没有第二封回执。这里按任务此刻的终态补送:成功的产出落回来,
    失败 / 取消的写上原因。和 receipts._deliver_if_already_settled(占位落下时任务已经结束)是同一件事。
    只认这个工作区里的任务:画布是客户端写的,别处任务的产出(一段写出来的字)不能借一个任务号落进来。
    """
    from app.db.models import Job
    from app.domain.boards.receipts import deliver_generated, receipt_to_item
    from app.domain.jobs import TERMINAL_STATUSES

    jobs = {job.id: job for job in db.scalars(
        select(Job).where(Job.id.in_(set(revived.values())), Job.workspace_id == workspace_id)
    )}
    for item_id, job_id in revived.items():
        job = jobs.get(job_id)
        if job is not None and job.status in TERMINAL_STATUSES:
            deliver_generated(db, job, receipt_to_item(board_id, item_id))


def delete_board(db: Session, workspace_id: str, board_id: str, *, actor_id: str | None = None) -> None:
    board = get_board(db, workspace_id, board_id)
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="board.deleted",
        subject_type="board",
        subject_id=board_id,
        summary="删除了无限画布",
        payload={"name": board.name, "revision": board.revision},
    )
    db.delete(board)
