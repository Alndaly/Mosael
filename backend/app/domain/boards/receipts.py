"""在画板上生成:摆占位、服务端单格合并、任务落终态时把回执送回那一格。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.db.models import Board
from app.domain.boards.errors import BoardRevisionConflict
from app.domain.boards.outputs import _canvas_with_delivered_result, outputs_of
from app.domain.boards.persistence import get_board, update_board
from app.domain.boards.producer_ids import derives_outputs
from app.domain.boards.run_state import live_job


logger = logging.getLogger(__name__)


# ── 在画板上生成 ────────────────────────────────────────────────────────────
#
# 画板是生成能力的**第五个入口**(前四个:AI 工作台、定时任务、工作流节点、智能体)。
# 它不自己实现一遍生成 —— 照样汇进 create_generation_job 那条漏斗,于是描述符校验、
# 能力探测、计量记账、任务中心全都白拿。这一层只回答画板自己的那个问题:
# **产出该落回哪儿**。

#: 回执的种类名。任务落终态时,jobs 那边按这个名字找到下面的 deliver_generated。
RECEIPT_KIND = "board_item"


def receipt_to_item(board_id: str, item_id: str) -> dict[str, Any]:
    """建任务时写进 payload 的那一小块:这次的产出属于哪张板的哪一项。"""
    return {"kind": RECEIPT_KIND, "board_id": board_id, "item_id": item_id}


#: 服务端对**某一格**的合并(摆占位、写字、回执)在撞上并发写入时重试几次。
_MERGE_ATTEMPTS = 4


def _merge_into_latest(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    merge: Callable[[dict[str, Any]], dict[str, Any]],
    actor_id: str | None = None,
) -> Board:
    """把服务端的一次单格改动**合到最新的画布上**,冲突就重读再合。

    客户端存回来的是整份快照,它不知道别人刚改了什么,所以按 base_revision 挡回去是对的。
    服务端这几种写入不一样:它们只改自己那一格,从最新画布出发重做一遍 `merge` 就不会覆盖
    任何人。此前它们各自带着调用方的 base_revision 去 CAS —— 于是任务已经建好(钱已经在路上)
    之后,同一个人的一次自动保存恰好先落库,占位就撞 409:任务永远排着队,画布上什么都没有。
    版本该在**花钱之前**问(见 ensure_revision),花了之后只剩「把结果放对地方」。
    """
    for attempt in range(_MERGE_ATTEMPTS):
        board = get_board(db, workspace_id, board_id)
        db.refresh(board)
        canvas = merge(dict(board.canvas or {"items": [], "edges": []}))
        try:
            return update_board(
                db,
                workspace_id=workspace_id,
                board_id=board_id,
                canvas=canvas,
                base_revision=board.revision,
                actor_id=actor_id,
                server_write=True,
            )
        except BoardRevisionConflict:
            if attempt == _MERGE_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def place_pending(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item: dict[str, Any],
    actor_id: str | None = None,
    ability: tuple[str, dict[str, Any]] | None = None,
) -> Board:
    """把某一项的「正在生成」状态放到画布上,再去起任务。

    **顺序是这样的原因**:生成要几十秒,而用户点完就在看画布。先放一个占位,他立刻看得见
    "这儿在生成";等回执把 asset_id 填回来,占位就地变成图片/视频。反过来(先起任务、
    等成功再放)的话,这几十秒里画布上什么都没有,用户会以为自己没点中。

    **按 id 就地更新,不存在才追加。** 画板上的生成有两个入口:工具条上「放一个空槽去
    生成」是新建一项,而在已有的空槽里写完提示词点生成,那一项**早就在画布上**了 ——
    无脑追加会撞上同 id 的自己,用户只是点了生成,却收到一句「画板项 id 重复」。

    就地更新时**保留它已有的位置和大小**:调用方只知道「它开始生成了」,不知道用户把它
    拖到哪儿、拉多大 —— 拿请求里的默认坐标覆盖,会让节点自己跳回左上角。

    **不收 base_revision。** 调用方在建任务之前已经问过版本(ensure_revision);到这里任务
    已经建好,只剩把占位合到最新画布上(见 _merge_into_latest)。

    `ability`:这一轮跑的是宿主的一项能力(`(产出者, 那一项的设置)`)。设置合进宿主**此刻**表单的
    `abilities`(在最新画布上合,不拿调用方读到的那份覆盖 —— 这中间用户可能刚改了宿主的别的东西),
    宿主自己的产出者和别的几项能力的设置不动。
    """

    def merge(canvas: dict[str, Any]) -> dict[str, Any]:
        items = [dict(one) for one in (canvas.get("items") or [])]
        index = next((i for i, one in enumerate(items) if one.get("id") == item.get("id")), None)
        if index is None:
            items.append(item)
        else:
            #: 位置和大小、表单归画布(用户编辑出来的),状态归这里(任务起来了)。
            keep = {k: v for k, v in item.items() if k not in ("x", "y", "width", "height")}
            merged = {**items[index], **keep}
            if ability is not None:
                merged["form"] = _with_ability(items[index].get("form"), *ability)
            else:
                #: 能力的设置归宿主这一格,不归它自己这一轮 —— 重新生成、让 AI 改写照样带着它们。
                merged["form"] = _keeping_abilities(merged.get("form"), items[index].get("form"))
            #: 四个状态两两互斥 —— 重新生成时旧产出、上一次的失败都让位给这次的占位。
            #: 不清的话,一个项会同时带着 run.running 和 asset_id(画布不知道该画哪个),
            #: 或者一边转圈一边挂着上次的报错(用户以为这次也挂了)。派生落点的宿主不清:它的产出
            #: 在右边,它自己的 asset_id(比如音频格里那段音频)不是上一次的产出。
            if not derives_outputs(merged):
                merged.pop("asset_id", None)
            items[index] = merged
        return {**canvas, "items": items}

    board = _merge_into_latest(db, workspace_id=workspace_id, board_id=board_id, merge=merge, actor_id=actor_id)
    return _deliver_if_already_settled(db, board, item)


def _keeping_abilities(form: Any, stored: Any) -> Any:
    """`form` 没写能力的设置时,带上 `stored` 里的那一份(排在产出者前面)。"""
    abilities = stored.get("abilities") if isinstance(stored, dict) else None
    if not abilities or not isinstance(form, dict) or "abilities" in form:
        return form
    own = {key: value for key, value in form.items() if key != "producer"}
    return {**own, "abilities": abilities, **({"producer": form["producer"]} if "producer" in form else {})}


def _with_ability(form: Any, producer: str, settings: dict[str, Any]) -> dict[str, Any]:
    """宿主的表单,`abilities[producer]` 换成这一份。键的先后:原有的草稿、`abilities`、产出者排最后
    (和 actions._pending 写的一样,前端按 JSON 比对表单)。"""
    current = dict(form) if isinstance(form, dict) else {}
    own = current.pop("producer", None)
    abilities = dict(current.pop("abilities", None) or {})
    abilities[producer] = settings
    return {**current, "abilities": abilities, **({"producer": own} if own is not None else {})}


def _deliver_if_already_settled(db: Session, board: Board, item: dict[str, Any]) -> Board:
    """占位落下时,它等的那个任务若已经结束,当场补送回执。

    念字、截取是「建任务即派发」:任务线程和摆占位的请求赛跑。很短的合成、源文件已经不在的截取,
    会在占位落下之前就落终态 —— 那封回执到的时候这一格还不是这一轮,被放过了(见
    _canvas_with_delivered_result),而这个任务不会再有第二封。不补的话那一格永远转圈。
    和正常送到的那封撞在一起也没关系:先落库的收掉这一轮,后到的那封就不再是「这一轮」了。
    """
    from app.db.models import Job
    from app.domain.jobs import TERMINAL_STATUSES

    job_id = live_job(item)
    job = db.get(Job, job_id) if job_id else None
    if job is None:
        return board
    db.refresh(job)
    if job.status not in TERMINAL_STATUSES:
        return board
    deliver_generated(db, job, receipt_to_item(board.id, str(item.get("id"))))
    return get_board(db, board.workspace_id, board.id)


def _asset_facts(db: Session, workspace_id: str, outputs: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """产出里那些素材的种类和名字。**只认这个工作区里的** —— 别处的 id 当它不存在,不落到画布上。"""
    from app.db.models import Asset

    ids = {str(one.get("asset_id")) for one in outputs if one.get("type") == "asset" and one.get("asset_id")}
    if not ids:
        return {}
    rows = db.scalars(select(Asset).where(Asset.id.in_(ids), Asset.workspace_id == workspace_id))
    return {row.id: (str(row.kind or ""), str(row.name or row.id)) for row in rows}


def deliver_generated(db: Session, job: Any, receipt: dict[str, Any]) -> None:
    """任务落终态 → 把产出填进画板上那一项(能力:新建成右边的几格,见 _canvas_with_delivered_result)。

    **成功和失败都要处理。** 失败时保留可重试的节点并结束转圈状态。

    **一次可能出多张。** 第一张落进占位，其余产出挨着它向右排列。

    **回执也遵守乐观并发。** 用户可能在任务完成的同一刻移动节点；冲突时重新读取最新画布，
    只把任务终态合并进去再 CAS，既不覆盖用户编辑，也不让已完成的结果丢失。
    """
    from app.domain.jobs import was_cancelled

    board_id = str(receipt.get("board_id") or "")
    item_id = str(receipt.get("item_id") or "")
    if not board_id or not item_id:
        return

    job_status = str(job.status)
    actor_id = getattr(job, "created_by", None)
    outputs = outputs_of(job)
    #: 这一格为什么没拿到产出。任务成功结束却什么都没交回,原因就是这句话本身 —— 任务那一侧
    #: 没有 error 可给;失败/取消用任务自己记下的原因。
    reason = tr("boardErr_noOutput") if job_status == "succeeded" else str(getattr(job, "error", "") or "")

    board = db.get(Board, board_id)
    if board is None:
        return
    assets = _asset_facts(db, board.workspace_id, outputs)
    #: 这封回执有没有落到那一格(那一格此刻跑的是这个任务)。合并撞车会重来,以最后落库的那一次为准。
    landed = {"yes": False}

    def merge(canvas: dict[str, Any]) -> dict[str, Any]:
        item = next((one for one in canvas.get("items") or [] if one.get("id") == item_id), None)
        landed["yes"] = live_job(item) == str(job.id)
        return _canvas_with_delivered_result(
            canvas, item_id=item_id, job_id=str(job.id), outputs=outputs, reason=reason,
            cancelled=was_cancelled(job), succeeded=job_status == "succeeded", assets=assets,
        )

    merged = _merge_into_latest(db, workspace_id=board.workspace_id, board_id=board.id, merge=merge, actor_id=actor_id)
    if landed["yes"] and job_status == "succeeded":
        _append_to_connected_timelines(db, merged, item_id)
    logger.info("board %s item %s -> %s", board_id, item_id,
                ", ".join(one.get("asset_id") or f"({one['type']})" for one in outputs) or "(failed)")


def _append_to_connected_timelines(db: Session, board: Board, item_id: str) -> None:
    """产出落进了连着时间线格的那一格:接到时间线末尾(见 timelines.append_filled_media)。接不上不挡回执。"""
    from app.domain.boards.timelines import append_filled_media

    try:
        if append_filled_media(db, board.workspace_id, board.canvas or {}, item_id):
            db.commit()
    except Exception:  # noqa: BLE001 — 回执已经落下;接时间线是顺带的一步
        db.rollback()
        logger.exception("board %s item %s: could not append the output to its timelines", board.id, item_id)


def install() -> None:
    """把画板的回执登记进任务总线。

    **方向是反的**:任务不认识画板,是画板认识任务 —— 和智能体那条回执同一个做法
    (见 domain/agent/receipts 开头那段)。登记在组合层(app/main._wire_seams)的**导入期**,
    不在 lifespan 里:不跑 lifespan 的入口(TestClient、脚本)照样要能把产出填回画布。
    """
    from app.domain.jobs import register_receipt_deliverer

    register_receipt_deliverer(RECEIPT_KIND, deliver_generated)
