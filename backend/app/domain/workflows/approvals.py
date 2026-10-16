"""工作流「等人确认」:跑到 `await_approval` 节点就**落库停下**,等一个决定。

## 引擎现在有没有"可持久化的暂停 + 从暂停那一节点恢复"?

**此前没有。** 执行内核(engine.run_graph)是一轮同步跑完的:节点在各自线程里跑,跑完写上下文、
发事件、按 `waits_for` 往下派;唯一的"停"是**取消**(每一拍重读任务状态,见 is_cancelled / run_scope)
和节点失败。两者都是终态 —— 任务落了终态就再也回不来,没有"先停下、之后从这一步接着跑"这回事
(引擎里 `checkpoint` / `resume` 零命中)。所以本任务的核心工作量就是**把这一条补出来**。

## 暂停是持久化的,而且从暂停的那一个节点接着跑

暂停**不是**"在线程里 sleep 等人点":那一套进程一重启就丢,而一次运行可能已经烧了钱
(起过的浏览器会话、生成过的素材、付过的模型调用)。这里的做法是把一轮图**拆成两半**:

1. 跑到 `await_approval` 时执行器建好这张单(或认出重启前那张),然后抛 `AwaitingApproval`;
   引擎捕获它 —— **不立停的信号、不记失败**,等还在飞的兄弟节点各自落定,再把"已经落定的现场"
   (`GraphResume`:上下文 + 跑过的 + 跳过的)交回上层。`engine.run_workflow` 把现场写进
   `WorkflowRunApproval.checkpoint`,发一条「等你确认」的站内通知(和飞书卡片),然后**不落终态**:
   任务留在 `running`,线程在这里结束 —— 连接、派发名额全都还回去(一个等 24 小时的门不该占着
   一条线程和一个名额)。
2. 决定下来时(飞书卡片 / 应用内 / 超时)按 checkpoint **重新进 run_graph**:`done` 里的节点直接
   跳过、**不执行**,上下文从 checkpoint 播种。于是前面烧过钱的节点不会重跑一遍。跑到
   `await_approval` 这个节点时它认出决定已下,就地交回那一格产物,下游接着走。

**重启之后仍在等。** 任务那一行是 `running`,重启收尾(reconcile_orphaned_jobs)本来会把它判成
"被中断、请重新发起",而工作流在总线上登记了一个 resumer(见 `register_seams`):**只有**手里有
一张待批单的那种才接着跑(没决定的接着等,已决定的接着往下),其余的照旧判失败 —— 既有语义不变。

## 两条路汇到一处

飞书卡片和应用内那两处**不各写一套决定**:都调 `decide()`,它用一条 CAS(pending → 决定)保证
"谁先到谁说了算",赢了的那一个才负责 `wake()`(把那次运行接着派发出去)。所以:
同一个门不会因为两条路都点了而跑两遍,也不会因为先点的那条没提交就不算数。

## 超时

到点由后台那一拍处理(workers/scheduler.tick → `expire_due`),按节点上写的办:
`abort` 中止这次运行(去掉决定后接着跑,执行器抛出`wfErr_awaitApprovalTimedOut`)、
`continue` 当成 `timeout` 继续往下、`remind` 只再提醒一次并把下一次提醒的时刻往后推一格。
**三种都再通知一次** —— 一个门禁悄悄过期等于没装。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.i18n import DEFAULT_LOCALE, t
from app.core.unit_of_work import after_commit, unit_of_work
from app.db.models import FeishuBinding, FeishuBot, Job, User, Workflow, WorkflowRunApproval, now
from app.domain.notifications import notify
from app.domain.workflows import WorkflowDomainError, as_text

logger = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
TIMED_OUT = "timeout"
CANCELLED = "cancelled"

#: 决定那一格交给下游的三个值(节点输出 `decision`)。**三值文字而不是布尔**:条件节点里
#: `equals approved` 一条就说清,不受大小写 / 语言影响(见 node_types 的说明)。
DECISIONS = (APPROVED, REJECTED, TIMED_OUT)

#: 超时之后怎么办。
TIMEOUT_ABORT = "abort"
TIMEOUT_CONTINUE = "continue"
TIMEOUT_REMIND = "remind"
TIMEOUT_ACTIONS = (TIMEOUT_ABORT, TIMEOUT_CONTINUE, TIMEOUT_REMIND)

#: 节点上没写超时小时数时用这个(和声明里的 default 同一个数)。
DEFAULT_TIMEOUT_HOURS = 24.0
#: 超时最多能填多久 / 最少:按小时填,但一格 100000 小时的等待没有意义,只会拖着一个 running 的任务。
MAX_TIMEOUT_HOURS = 24 * 365.0


# ---------------- 建单 / 读单 ----------------


def timeout_of(config: dict[str, Any]) -> int | None:
    """节点上写的超时(小时)→ 秒;0 / 空 / 认不出 = 一直等。"""
    raw = config.get("timeout_hours")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        hours = DEFAULT_TIMEOUT_HOURS
    else:
        try:
            hours = float(str(raw).strip())
        except (TypeError, ValueError):
            hours = DEFAULT_TIMEOUT_HOURS
    if hours <= 0:
        return None
    return int(min(hours, MAX_TIMEOUT_HOURS) * 3600)


def on_timeout_of(config: dict[str, Any]) -> str:
    value = str(config.get("on_timeout") or TIMEOUT_ABORT).strip()
    return value if value in TIMEOUT_ACTIONS else TIMEOUT_ABORT


def wants_note(config: dict[str, Any]) -> bool:
    """要不要留一格备注输入框。没写 = 要(卡片上多一格,批的人可以顺手说一句)。"""
    raw = config.get("allow_note")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return True
    return str(raw).strip().lower() not in ("no", "false", "0")


def prepare(
    db: Session, *, job: Job, workflow_id: str, node_id: str, node_name: str, config: dict[str, Any]
) -> WorkflowRunApproval:
    """这一次等待的那张单:已经有(重启后重新进到这一步、或并行的两个节点)就接着用那一张,不新发卡。

    **不提交**:调用方(执行器)自己开事务、自己提交,提交之后再发卡片 —— 卡片指向一张还没落库的单
    是发不出去的(点回来只会说"这张确认卡已经不存在了")。
    """
    existing = find(db, job.id, node_id)
    if existing is not None:
        return existing
    title = as_text(config.get("title")).strip()
    if not title:
        raise WorkflowDomainError("wfErr_notifyTitleEmpty")
    seconds = timeout_of(config)
    row = WorkflowRunApproval(
        workspace_id=job.workspace_id,
        workflow_id=workflow_id,
        job_id=job.id,
        node_id=node_id,
        node_name=node_name or node_id,
        title=title[:200],
        body=as_text(config.get("body")),
        approve_label=as_text(config.get("approve_label")).strip()[:40],
        reject_label=as_text(config.get("reject_label")).strip()[:40],
        allow_note=wants_note(config),
        timeout_seconds=seconds,
        on_timeout=on_timeout_of(config),
        status=PENDING,
        expires_at=(now() + timedelta(seconds=seconds)) if seconds else None,
    )
    db.add(row)
    db.flush()
    return row


def find(db: Session, job_id: str, node_id: str) -> WorkflowRunApproval | None:
    return db.scalar(
        select(WorkflowRunApproval).where(
            WorkflowRunApproval.job_id == job_id, WorkflowRunApproval.node_id == node_id
        )
    )


def for_job(db: Session, job_id: str) -> list[WorkflowRunApproval]:
    return list(
        db.scalars(
            select(WorkflowRunApproval)
            .where(WorkflowRunApproval.job_id == job_id)
            .order_by(WorkflowRunApproval.created_at)
        )
    )


def pending_for_job(db: Session, job_id: str) -> WorkflowRunApproval | None:
    return db.scalar(
        select(WorkflowRunApproval)
        .where(WorkflowRunApproval.job_id == job_id, WorkflowRunApproval.status == PENDING)
        .order_by(WorkflowRunApproval.created_at)
    )


def pending_for_workspace(db: Session, workspace_id: str) -> list[WorkflowRunApproval]:
    """这个工作区此刻在等确认的那些单(任务中心 / 运行详情那两处列表读它)。"""
    return list(
        db.scalars(
            select(WorkflowRunApproval)
            .where(
                WorkflowRunApproval.workspace_id == workspace_id,
                WorkflowRunApproval.status == PENDING,
            )
            .order_by(WorkflowRunApproval.created_at.desc())
        )
    )


def pending_for_workflow(db: Session, workflow_id: str) -> list[WorkflowRunApproval]:
    return list(
        db.scalars(
            select(WorkflowRunApproval)
            .where(
                WorkflowRunApproval.workflow_id == workflow_id,
                WorkflowRunApproval.status == PENDING,
            )
            .order_by(WorkflowRunApproval.created_at.desc())
        )
    )


# ---------------- 落检查点 / 恢复 ----------------


def record_checkpoint(db: Session, approval: WorkflowRunApproval, checkpoint: dict[str, Any]) -> None:
    """把暂停那一刻的现场写进这张单。**不提交**(跟着 run_workflow 那次事务)。"""
    approval.checkpoint = checkpoint
    approval.updated_at = now()


# ---------------- 决定 ----------------


class ApprovalError(Exception):
    """这个决定做不了(单不在了 / 已经决定过了 / 这个运行已经不在了)。带一句给人看的话。"""


def decide(
    db: Session,
    approval: WorkflowRunApproval,
    *,
    decision: str,
    user_id: str | None = None,
    user_name: str = "",
    note: str = "",
    via: str = "app",
) -> bool:
    """落一个决定。**返回是不是我落的** —— 两条路(飞书 / 应用内)同时点只有一个赢。

    一条 CAS(pending → 决定)是这件事的全部:赢了的那一个才去唤醒那次运行,所以同一次等待
    不会被唤醒两遍。不提交,调用方提交 —— 提交之后才 `wake`(见 decide_and_wake)。
    """
    if decision not in (APPROVED, REJECTED):
        raise ApprovalError(f"unknown decision {decision!r}")
    changed = db.execute(
        update(WorkflowRunApproval)
        .where(WorkflowRunApproval.id == approval.id, WorkflowRunApproval.status == PENDING)
        .values(
            status=decision,
            decision=decision,
            decided_by=user_id,
            decided_by_name=user_name[:120],
            note=(note or "")[:2000],
            decided_via=via,
            decided_at=now(),
            updated_at=now(),
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    if not changed:
        db.refresh(approval)
        return False
    db.refresh(approval)
    return True


def decide_and_wake(
    db: Session,
    approval: WorkflowRunApproval,
    *,
    decision: str,
    user_id: str | None = None,
    user_name: str = "",
    note: str = "",
    via: str = "app",
) -> bool:
    """落决定并在**提交之后**叫醒那次运行。飞书卡片和应用内那两处唯一该调的入口。"""
    if not decide(db, approval, decision=decision, user_id=user_id, user_name=user_name, note=note, via=via):
        return False
    wake(db, approval)
    return True


def wake(db: Session, approval: WorkflowRunApproval) -> None:
    """把停在这张单上的那次运行接着派发出去(提交之后才真的起线程 —— 见 jobs.dispatch_job 的说明)。"""
    job_id = approval.job_id
    after_commit(db, lambda: dispatch_resume(job_id))


def dispatch_resume(job_id: str) -> bool:
    """重新进引擎把这次运行接着跑。返回是否真的派发了。

    认的是**这张单的检查点**:没有它就恢复不了(那是"这道门装出来之前就停下的一次运行"),
    这时什么都不做 —— 交给重启收尾 / 任务本身去说。
    """
    from app.domain.workflows.engine import continue_workflow_job

    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running":
            return False
        approval = _resumable(db, job_id)
        if approval is None:
            return False
        continue_workflow_job(db, job, approval.checkpoint or {})
        logger.info("workflow job %s resumed from approval %s", job_id, approval.id)
        return True


def _resumable(db: Session, job_id: str) -> WorkflowRunApproval | None:
    """这一次运行该接着跑吗:手里有一张带检查点的单、而且它的决定已经下来了(或者还在等)。

    还在等也接着跑:重启把它打断了,重新进去还是停在同一个节点上等 —— 卡片和单都不会重发。
    """
    rows = for_job(db, job_id)
    return next((row for row in rows if row.checkpoint and row.status != CANCELLED), None)


# ---------------- 取消 ----------------


def cancel_for_job(db: Session, job: Job) -> None:
    """这次运行被停下了:它名下还在等的单一起撤掉 —— 否则卡片还点得动、列表里还挂着一条永远没人处理的等待。

    和取消**同一个事务**(见 jobs.register_cancel_listener):任务落了取消,这张单也就撤了。
    """
    changed = db.execute(
        update(WorkflowRunApproval)
        .where(WorkflowRunApproval.job_id == job.id, WorkflowRunApproval.status == PENDING)
        .values(status=CANCELLED, decided_via="cancel", decided_at=now(), updated_at=now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed:
        logger.info("cancelled %d pending approval(s) of job %s", changed, job.id)


# ---------------- 超时 ----------------


def expire_due(db: Session, *, moment: datetime | None = None) -> int:
    """到点的待批单按节点上写的办。返回处理了几张。**不提交**(跟着后台那一拍的事务)。

    - `abort`:落 `timeout` 决定并唤醒 —— 执行器看到它按"中止"抛出,这次运行失败,原因说清是超时;
    - `continue`:落 `timeout` 决定并唤醒 —— 节点交出 `decision=timeout`,下游接着走;
    - `remind`:不落决定,**把下一次提醒的时刻往后推一格**并再通知一次 —— 还在等的人知道这件事还欠着。
    """
    reference = moment or now()
    due = list(
        db.scalars(
            select(WorkflowRunApproval).where(
                WorkflowRunApproval.status == PENDING,
                WorkflowRunApproval.expires_at.is_not(None),
                WorkflowRunApproval.expires_at <= reference,
            )
        )
    )
    handled = 0
    for row in due:
        if row.on_timeout == TIMEOUT_REMIND:
            row.expires_at = reference + timedelta(seconds=row.timeout_seconds or 0)
            row.reminded_at = reference
            row.updated_at = reference
            _notify_timeout(db, row, "wfNotice_awaitApprovalTimeoutRemind")
            handled += 1
            continue
        changed = db.execute(
            update(WorkflowRunApproval)
            .where(WorkflowRunApproval.id == row.id, WorkflowRunApproval.status == PENDING)
            .values(status=TIMED_OUT, decision=TIMED_OUT, decided_via="timeout", decided_at=reference,
                    updated_at=reference)
            .execution_options(synchronize_session=False)
        ).rowcount
        if not changed:
            continue
        db.refresh(row)
        handled += 1
        _notify_timeout(
            db, row,
            "wfNotice_awaitApprovalTimeoutContinue" if row.on_timeout == TIMEOUT_CONTINUE
            else "wfNotice_awaitApprovalTimeoutAbort",
        )
        wake(db, row)
    return handled


def _notify_timeout(db: Session, row: WorkflowRunApproval, key: str) -> None:
    notify(
        db,
        row.workspace_id,
        type="workflow",
        title=t("wfNotice_awaitApproval", DEFAULT_LOCALE, title=row.title),
        body=t(key, DEFAULT_LOCALE, title=row.title),
        link="#/workflows",
        payload={"approval_id": row.id, "job_id": row.job_id, "workflow_id": row.workflow_id},
    )


# ---------------- 通知(站内那条路) ----------------


def announce(db: Session, approval: WorkflowRunApproval) -> None:
    """把这次等待说出去:先站内通知(没有飞书也照样等),再尽力发一张飞书卡片。

    **站内那一条是兜底,不是补充**:没有飞书绑定、飞书没配好、卡片能力没开,这次运行都照旧在等
    (需求里那句"不许因为没有飞书就报错或直接放行")。所以通知先写、卡片后发,卡片失败一律降级。

    **发给整个工作区**(和"工作流失败"那条通知同一个范围):一个门禁最坏的失败是没人看见。
    待批列表本来就是全工作区可见的(谁能批在决定那一步按成员校验),通知也就不挑人。

    **只在检查点落库之后调**(见 engine._park_at_approval):先发卡、后落现场的话,手快的人在
    现场写下去之前点了确认,那次运行会卡在一个永远唤醒不了的等待上。
    """
    notify(
        db,
        approval.workspace_id,
        type="workflow",
        title=t("wfNotice_awaitApproval", DEFAULT_LOCALE, title=approval.title),
        body=t(
            "wfNotice_awaitApprovalBody", DEFAULT_LOCALE,
            workflow=_workflow_name(db, approval.workflow_id), node=approval.node_name or approval.node_id,
        ),
        link="#/workflows",
        payload={"approval_id": approval.id, "job_id": approval.job_id, "workflow_id": approval.workflow_id},
    )
    _announce_feishu(db, approval)


def _workflow_name(db: Session, workflow_id: str) -> str:
    workflow = db.get(Workflow, workflow_id)
    return workflow.name if workflow is not None else workflow_id


def _announce_feishu(db: Session, approval: WorkflowRunApproval) -> None:
    """把确认卡推到飞书。**一律降级、绝不抛**(和工具确认卡同一条规矩):飞书那边出问题不该让这次运行跑不下去。

    **实现由集成层在组装根登记**(见 `use_run_card_sender` 与 app.main._wire_seams):领域层不认识
    飞书 —— 飞书是**调用领域的一方**,不是领域要用的外部能力(见 tests/test_import_layering)。
    没人登记就是没接飞书:站内那条路已经发过了,这次运行照旧在等。
    """
    send = _RUN_CARD_SENDER
    if send is None:
        return
    try:
        send(db, approval)
    except Exception:  # noqa: BLE001 — 见 docstring
        logger.exception("feishu approval card failed approval=%s", getattr(approval, "id", "?"))


#: 「这一次等待说给飞书听」的实现。集成层在组装根登记;领域层只认"有人会替我发"。
_RUN_CARD_SENDER: Callable[[Session, WorkflowRunApproval], None] | None = None


def use_run_card_sender(send: Callable[[Session, WorkflowRunApproval], None]) -> None:
    """登记"把待批单发到飞书"的实现(见 integrations/feishu/approvals.announce_run_approval)。"""
    global _RUN_CARD_SENDER
    _RUN_CARD_SENDER = send


def announce_parked(approval_id: str) -> None:
    """**提交之后**才说:站内通知 + 飞书卡片(engine._park_at_approval 用 after_commit 排到这一刻)。

    自己开一个会话、自己提交:排进来的那一刻调用方的事务已经落了库,而通知 / 卡片那几笔要单独落
    —— 它们失败也不该把已经提交的暂停现场带回去。
    """
    try:
        with unit_of_work() as db:
            row = db.get(WorkflowRunApproval, approval_id)
            if row is None:
                return
            announce(db, row)
    except Exception:  # noqa: BLE001 —— 说出去这一步坏掉不该让这次运行跑不下去
        logger.exception("announce of parked approval failed approval=%s", approval_id)


# ---------------- 总线上的两条接缝 ----------------


def can_resume(db: Session, job: Job) -> bool:
    """重启之后这一类任务接得回来吗:**只有"手里有一张带检查点的待批单"的那种**。

    其余的(跑到一半被重启打断的普通运行)照旧判失败 —— 它们没有现场,接不回来,而不接回来
    硬重跑一遍就是重跑那些已经烧过钱的节点。
    """
    return _resumable(db, job.id) is not None


def resume_job(job_id: str) -> bool:
    """重启之后接着跑一个停在「等人确认」上的运行。"""
    return dispatch_resume(job_id)


def register_seams() -> None:
    """把这两条接缝登记到任务总线上。组装根调(app.main._wire_seams)—— 任务域不认识工作流。"""
    from app.domain.jobs import register_cancel_listener, register_resumer

    register_resumer("workflow", can_resume=can_resume, resume=resume_job)
    register_cancel_listener("workflow", cancel_for_job)


# ---------------- 列表出口用的小数据 ----------------


def requester_name(db: Session, job: Job | None) -> str:
    """这次运行是谁发起的(失败 / 等待的说明里要提到人时用)。"""
    user = db.get(User, job.created_by) if job is not None and job.created_by else None
    return (user.display_name or user.username) if user is not None else ""


def bot_for_user(db: Session, workspace_id: str, user_id: str | None) -> tuple[FeishuBot, str] | None:
    """这个人在这个工作区绑了哪个 open_id、用哪个机器人给他发私聊(没有就 None)。

    这是"工作区绑了飞书机器人"那条路:这次运行**不是**从飞书会话来的,但负责人绑过账号 ——
    卡片当私聊发给他。飞书允许按 open_id 直接发(`receive_id_type=open_id`)。
    """
    if not user_id:
        return None
    bot = db.scalar(
        select(FeishuBot)
        .where(FeishuBot.workspace_id == workspace_id, FeishuBot.enabled.is_(True))
        .order_by(FeishuBot.created_at)
    )
    if bot is None:
        return None
    open_id = db.scalar(
        select(FeishuBinding.open_id).where(
            FeishuBinding.workspace_id == workspace_id, FeishuBinding.user_id == user_id
        )
    )
    return (bot, open_id) if open_id else None
