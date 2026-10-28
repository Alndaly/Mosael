"""一条消息进来之后:谁认它、认了之后起哪一次运行、怎么留痕(ADR 0065 §3–§5)。

**入口只有三个**,顺序也固定:

    claimable(db, message)              → 谁认这条消息(只读、便宜、用来决定"要不要去下载附件")
    unrecorded_claims(db, message, …)   → 认领的那些里,哪些**还没为这条消息留过痕**(重投的去重)
    …集成层在这里把图片/文件/视频收进素材库…
    fire(db, message, …)                → 去重、限流、起运行、落事件、给出要回群的那句话

分成两步是因为**附件下载很贵**(要调飞书、落盘、探测、生成缩略图):没有触发器认这条消息时
一个字节都不该去下。而两步之间那条消息没有变 —— 认领的触发器 id 原样带到第二步。

`unrecorded_claims` 是第三步之前的那一问:去重的判据是 `(trigger_id, message_id)` 上的事件行,
而**附件入库自己 commit**(见 assets.importer),所以飞书重投时如果等到 `fire` 里那道去重才拦,
运行是挡住了,素材却已经白多了一份。

这一层**不提交事务**:调用方(集成层的入站入口)用一次事务包住,和全仓"用例只改对象"同一条规矩
(见 tests/test_use_case_boundaries_ratchet.py)。也**不认识飞书**:回来的 `Outcome.receipt`
是一句已经翻好的话,谁去发是谁的事。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import t
from mosael_formats.i18n import DEFAULT_LOCALE
from app.db.models import Workflow, WorkflowTrigger, WorkflowTriggerEvent, now
from app.domain.jobs import blame, create_job, finish_job
from app.domain.notifications import notify
from app.domain.triggers import matching
from app.domain.triggers.matching import IncomingMessage

logger = logging.getLogger(__name__)

#: 一条消息最多被几条触发器认领(兜底,ADR 0065 §4)。正常配置下一条消息只该被一条认领。
MAX_CLAIMS_PER_MESSAGE = 3

#: 限流窗口与上限(每个触发器)。
RATE_WINDOW_SECONDS = 60
MAX_RUNS_PER_MINUTE = 60

STATUS_STARTED = "started"
STATUS_THROTTLED = "throttled"
STATUS_REFUSED = "refused"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

#: 一条消息被认领、但没能起运行时的状态 —— 通知靠它去重(见 `_notified_recently`)。
_BAD_STATUSES = (STATUS_REFUSED, STATUS_FAILED)


@dataclass(frozen=True)
class Outcome:
    """一条触发器对这条消息的结论。`receipt` 非空 = 这条要在群里说一句(已经翻好、按缺省语言)。"""

    trigger_id: str
    trigger_name: str
    status: str
    job_id: str | None = None
    error: str = ""
    receipt: str = ""
    bot_id: str = ""
    chat_id: str = ""


# ---------------- 第一步:谁认这条消息 ----------------


def claimable(db: Session, message: IncomingMessage) -> tuple[list[str], list[str]]:
    """认这条消息的启用触发器:`(前 N 条认领,超出上限落选的)`。

    按创建时间排队(先配的先跑),`MAX_CLAIMS_PER_MESSAGE` 是兜底 —— 一句话不该起十次运行。
    落选的也交回去,是要在事件表里留一行 `skipped`:面板上看得见"它本来也认,只是没轮到"。

    同一刻创建的两条(`created_at` 只到微秒,批量导入的触发器常常撞上)按 id 兜底:没有
    tiebreaker 时"前三条认领、后两条落选"由数据库的返回顺序说了算,那是随机的。
    """
    if not message.kind:
        # 触发器认不了这种消息(语音、表情……):连查都不查。
        return [], []
    rows = list(
        db.scalars(
            select(WorkflowTrigger)
            .where(
                WorkflowTrigger.workspace_id == message.workspace_id,
                WorkflowTrigger.enabled.is_(True),
            )
            .order_by(WorkflowTrigger.created_at, WorkflowTrigger.id)
        )
    )
    matched = [row for row in rows if not matching.decide(row, message)]
    return (
        [row.id for row in matched[:MAX_CLAIMS_PER_MESSAGE]],
        [row.id for row in matched[MAX_CLAIMS_PER_MESSAGE:]],
    )


def recorded_claims(db: Session, message: IncomingMessage, claimed: list[str]) -> dict[str, str]:
    """`claimed` 里已经为这条消息留过痕的触发器 → 那行事件的状态。

    去重和“这条消息是不是已经有人认领过”是同一份事实;分开查会漂移。
    """
    if not claimed:
        return {}
    rows = db.execute(
        select(WorkflowTriggerEvent.trigger_id, WorkflowTriggerEvent.status).where(
            WorkflowTriggerEvent.message_id == message.message_id,
            WorkflowTriggerEvent.trigger_id.in_(claimed),
        )
    ).all()
    return {str(trigger_id): str(status) for trigger_id, status in rows}


def unrecorded_claims(db: Session, message: IncomingMessage, claimed: list[str]) -> list[str]:
    """`claimed` 里**还没为这条消息写过事件行**的那些 —— 飞书重投时这一条会是空的。

    判据和 `_record` 同一个(`(trigger_id, message_id)` 上的那一行),只是问得**更早**:
    在下载、入库之前。入库会调飞书、落盘、探测、生成缩略图,而 `import_binary_asset` 自己
    commit —— 等 `fire` 里那道去重把运行挡住时,素材已经白多了一份。

    只读、不改任何东西;真的并发重投仍然由 `_record` 的唯一约束兜底(宁可少跑一次)。
    """
    if not claimed:
        return []
    already = recorded_claims(db, message, claimed)
    return [trigger_id for trigger_id in claimed if trigger_id not in already]


# ---------------- 第二步:认领之后怎么了 ----------------


def fire(
    db: Session,
    message: IncomingMessage,
    claimed: list[str],
    *,
    skipped: list[str] | None = None,
) -> list[Outcome]:
    """把认领落成事:去重 → 限流 → 起运行 → 落事件。

    **去重先于一切**:先插事件行(`status` 先写成本次的结论),插不进去就是同一条消息的重复投递
    —— 那一次连运行都不起(见 ADR 0065 §4)。
    """
    outcomes: list[Outcome] = []
    for trigger_id in skipped or ():
        trigger = db.get(WorkflowTrigger, trigger_id)
        if trigger is None or not trigger.enabled:
            continue
        event = _record(db, trigger, message, status=STATUS_SKIPPED, error="too_many_triggers")
        if event is not None:
            outcomes.append(_outcome(trigger, message, STATUS_SKIPPED, error="too_many_triggers"))
    for trigger_id in claimed:
        outcome = _fire_one(db, trigger_id, message)
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes


def _outcome(
    trigger: WorkflowTrigger, message: IncomingMessage, status: str, *, job_id: str | None = None,
    error: str = "", receipt: str = "",
) -> Outcome:
    return Outcome(
        trigger_id=trigger.id,
        trigger_name=_name_of(trigger),
        status=status,
        job_id=job_id,
        error=error,
        receipt=receipt,
        bot_id=message.bot_id,
        chat_id=message.chat_id,
    )


def _name_of(trigger: WorkflowTrigger) -> str:
    return (trigger.name or "").strip() or trigger.id


def _fire_one(db: Session, trigger_id: str, message: IncomingMessage) -> Outcome | None:
    trigger = db.get(WorkflowTrigger, trigger_id)
    if trigger is None or not trigger.enabled:
        # 两步之间被关掉/删掉了:这一次就算了(它不是"这条消息"的事,不值得留一行)。
        return None

    workflow = db.get(Workflow, trigger.workflow_id)
    if workflow is None or workflow.workspace_id != trigger.workspace_id:
        # 工作流被删了。删的那一刻本该停用它(见 `stop_triggers_bound_to_workflow`),走到这里
        # 就是那个竞态 —— 顺手停掉,免得每来一条消息都白试一次。
        trigger.enabled = False
        reason = t("triggerRefused_workflowGone", DEFAULT_LOCALE)
        return _refuse(db, trigger, message, reason=reason, workflow_name="")

    if _runs_last_minute(db, trigger) >= _limit_of(trigger):
        # 限流:**留一行**,但不通知(通知本身就是另一种风暴,见 ADR 0065 §4)。
        event = _record(db, trigger, message, status=STATUS_THROTTLED, error="rate_limited")
        return _outcome(trigger, message, STATUS_THROTTLED, error="rate_limited") if event is not None else None

    params = _params_for(trigger, workflow, message)
    actor = trigger.owner_user_id

    #: **先判跑不跑得起来再建任务**:不然每一条消息都留下一个注定失败的排队任务
    #: (和定时任务 `ensure_runnable` 同一个道理)。这一次的入参是**按这条消息算出来的**,
    #: 所以只有到这一刻才判得了。
    try:
        from app.domain.workflows.engine import check_runnable

        check_runnable(db, workflow, params, actor)
    except Exception as exc:  # noqa: BLE001 —— 认得出原因的当拒绝,认不出的也是拒绝
        from app.domain.workflows.errors import WorkflowDomainError

        reason = (
            t("triggerRefused_notRunnable", DEFAULT_LOCALE, workflow=workflow.name, reason=str(exc))
            if isinstance(exc, WorkflowDomainError)
            else t("triggerRefused_failed", DEFAULT_LOCALE, reason=str(exc))
        )
        return _refuse(db, trigger, message, reason=reason, workflow_name=workflow.name)

    event = _record(db, trigger, message, status=STATUS_STARTED)
    if event is None:
        # 这条消息已经来过了(飞书重放 + 进程重启)。**到此为止** —— 一个字节的活儿都不干。
        logger.info("trigger %s: duplicate delivery of message %s", trigger.id, message.message_id)
        return None

    job = create_job(
        db,
        workspace_id=trigger.workspace_id,
        kind="workflow",
        #: **替触发器的主人跑**:用他的钥匙和额度,和定时任务同一条规矩(ADR 0065 §1)。
        created_by=actor,
        payload={
            "subject": workflow.name,
            #: 运行历史据此说得出"这次是触发器起的";它把这一次运行和那条消息连起来,
            #: 也让 `channel=origin` 的飞书节点/等人确认知道消息从哪个群来(而不是退回 owner 私聊)。
            "trigger_id": trigger.id,
            "trigger_event_id": event.id,
            "trigger_bot_id": message.bot_id,
            "trigger_chat_id": message.chat_id,
        },
        message="jobMsg_workflowQueued",
        message_params={"name": workflow.name},
    )
    event.job_id = job.id
    try:
        from app.domain.workflows.engine import start_workflow_job

        start_workflow_job(db, workflow, created_by=actor, params=params, job=job)
    except Exception as exc:  # noqa: BLE001 —— 起不来就是起不来,但要把这件事记下来
        logger.warning("trigger %s: run refused (%s)", trigger.id, exc, exc_info=True)
        reason = t("triggerRefused_failed", DEFAULT_LOCALE, reason=str(exc))
        #: 「要不要喊」在这一行变成坏状态**之前**判:变成 failed 之后 `_notified_recently` 看到的
        #: 就是它自己(和 `_refuse` 同一条规矩 —— 否则群里连丢十条,主人收到十条通知)。
        should_warn = not _notified_recently(db, trigger)
        event.status = STATUS_FAILED
        event.error = reason
        event.job_id = None
        finish_job(db, job, status="failed", **blame(exc))
        if should_warn:
            _notify_owner(db, trigger, workflow_name=workflow.name, reason=reason, job_id=job.id)
        return _outcome(trigger, message, STATUS_FAILED, error=reason)

    trigger.last_fired_at = now()
    return _outcome(
        trigger, message, STATUS_STARTED, job_id=job.id,
        receipt=(
            t("triggerReceipt", DEFAULT_LOCALE, trigger=_name_of(trigger), workflow=workflow.name)
            if trigger.reply_in_chat
            else ""
        ),
    )


def _refuse(
    db: Session, trigger: WorkflowTrigger, message: IncomingMessage, *, reason: str, workflow_name: str
) -> Outcome:
    """这一次没起运行:留一行、**必要时**喊一次主人。群里不喊配置错误(ADR 0065 §5)。"""
    #: 「要不要喊」在写这一行**之前**判 —— 写下去之后 `_notified_recently` 看到的就是它自己。
    should_warn = not _notified_recently(db, trigger)
    event = _record(db, trigger, message, status=STATUS_REFUSED, error=reason)
    if event is None:
        # 同一条消息的重复投递:上一次已经留过痕、也喊过了。
        return _outcome(trigger, message, STATUS_REFUSED, error=reason)
    if should_warn:
        _notify_owner(db, trigger, workflow_name=workflow_name, reason=reason, job_id=None)
    return _outcome(trigger, message, STATUS_REFUSED, error=reason)


# ---------------- 下面几件小事 ----------------


def _limit_of(trigger: WorkflowTrigger) -> int:
    try:
        limit = int(trigger.max_runs_per_minute)
    except (TypeError, ValueError):
        return 6  # 列是整型:读不出数说明库被手改过,退回默认而不是崩在入站链路上
    return max(1, min(MAX_RUNS_PER_MINUTE, limit))


def _runs_last_minute(db: Session, trigger: WorkflowTrigger) -> int:
    """最近一分钟**真的起跑了**几次(被限流、被拒的不算)。数在库里:重启不清零。"""
    horizon = now() - timedelta(seconds=RATE_WINDOW_SECONDS)
    return int(
        db.scalar(
            select(func.count())
            .select_from(WorkflowTriggerEvent)
            .where(
                WorkflowTriggerEvent.trigger_id == trigger.id,
                WorkflowTriggerEvent.status == STATUS_STARTED,
                WorkflowTriggerEvent.created_at >= horizon,
            )
        )
        or 0
    )


def _params_for(trigger: WorkflowTrigger, workflow: Workflow, message: IncomingMessage) -> dict[str, Any]:
    return matching.render_params(
        trigger.params,
        matching.start_param_names(workflow.graph),
        matching.values_of(message),
    )


def _record(
    db: Session,
    trigger: WorkflowTrigger,
    message: IncomingMessage,
    *,
    status: str,
    error: str = "",
) -> WorkflowTriggerEvent | None:
    """写下"这条消息被这条触发器认领过"。**已经写过就是重复投递**,返回 None、什么都不插。

    去重的判据是 `(trigger_id, message_id)` 上的唯一约束(ADR 0065 §4);这里先读一次是为了
    让常见的重复投递**不撞约束** —— 撞了会把整个事务打进"需要回滚"的状态,而那个事务里还有
    别的事(附件入库的记录、别的触发器的认领)。真的并发撞上时,唯一约束仍然是最后那道门
    (后果是这一次整个回滚:宁可少跑一次,绝不付费跑两次)。
    """
    exists = db.scalar(
        select(WorkflowTriggerEvent.id)
        .where(
            WorkflowTriggerEvent.trigger_id == trigger.id,
            WorkflowTriggerEvent.message_id == message.message_id,
        )
        .limit(1)
    )
    if exists is not None:
        return None
    event = WorkflowTriggerEvent(
        trigger_id=trigger.id,
        workspace_id=trigger.workspace_id,
        message_id=message.message_id,
        bot_id=message.bot_id,
        chat_id=message.chat_id,
        sender_open_id=message.sender_open_id,
        message_type=message.message_type,
        text_preview=matching.preview(message.text),
        asset_ids=list(message.asset_ids),
        status=status,
        error=error,
    )
    db.add(event)
    db.flush()
    return event


def _notified_recently(db: Session, trigger: WorkflowTrigger) -> bool:
    """这个触发器最近一分钟已经喊过主人了 —— 配置错误不该按每一条消息各提醒一次。"""
    horizon = now() - timedelta(seconds=RATE_WINDOW_SECONDS)
    return (
        db.scalar(
            select(WorkflowTriggerEvent.id)
            .where(
                WorkflowTriggerEvent.trigger_id == trigger.id,
                WorkflowTriggerEvent.status.in_(_BAD_STATUSES),
                WorkflowTriggerEvent.created_at >= horizon,
            )
            .limit(1)
        )
        is not None
    )


def _notify_owner(
    db: Session, trigger: WorkflowTrigger, *, workflow_name: str, reason: str, job_id: str | None
) -> None:
    """拒绝 / 失败时**在站内**喊主人(群里不喊配置错误,见 ADR 0065 §5)。

    最频繁每分钟一条:调用方按 `_notified_recently` 在写下这一次的坏事件**之前**判 ——
    一个配错的触发器被群里连丢十条视频,主人收到一条通知,不是十条。
    """
    notify(
        db,
        trigger.workspace_id,
        type="system",
        title=t("triggerNotice_refusedTitle", DEFAULT_LOCALE, trigger=_name_of(trigger)),
        body=t("triggerNotice_refusedBody", DEFAULT_LOCALE, workflow=workflow_name or "—", reason=reason),
        link="#/workflows",
        payload={"trigger_id": trigger.id, **({"job_id": job_id} if job_id else {})},
        user_id=trigger.owner_user_id,
    )
