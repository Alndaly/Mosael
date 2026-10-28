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
**三种都再通知一次** —— 一个门禁悄悄过期等于没装。提醒这一档**飞书那边也说一声**
(同一张卡就地换成"还在等,已提醒过一次",见 `remind_feishu_card`;没发出去过就跳过)。

## 决定 / 超时 / 提醒**只在现场落库之后**才成立

单是执行器自己一个事务先提交的(它必须比卡片先落库),检查点由引擎随后写进 `_park_at_approval`
那次事务。那一段窗口里这张单是 `pending`、检查点还是空的:**批它只会落一个决定,而没有现场可恢复**,
那次运行永远醒不过来。两头都堵上 —— 列表不列还没有现场的单(`pending_for_*` 见 `ready_to_decide`),
后台那一拍也不处理它们;引擎写完现场会**复查**这道门是不是已经被决定了,是就自己再排一次恢复
(见 engine._park_at_approval)。

## 拒绝

拒绝是**一个人真的做了决定**,不是超时那种"没人做"。按节点上的 `on_reject` 办:
`abort`(默认)把这次运行判失败(执行器抛出`wfErr_awaitApprovalRejected`,和超时 + `abort`
同一个失败口径),决定不交到下游;`branch` 则把 `rejected` 当成一个决定交给下游
(condition 接 `decision="rejected"`)。

## 到底发到飞书没有(投递结果)

「先站内通知、再尽力发飞书卡片」这条链上有三件不同的事,此前只有日志分得开:
(见 ADR 0069)

1. **发到了**(`sent`):卡片成了,或者卡片失败之后退成的那段文字成了 —— 飞书里的人确实收到了东西;
2. **这次本来就没打算发**(`not_attempted`):路由那一层就解不出收件人(节点上写了「仅站内」、
   工作区没有机器人、发起人没绑定)。**那要么是用户明说的选择、要么是这次运行没有可发的去处,
   不是失败** —— 记成失败,下一步就会有人给它加"重试";
3. **发失败了**(`failed`):卡片和降级的文字都没出去(断网、机器人没权限)。

三件事写在那张单的 `feishu_delivery` / `feishu_delivery_reason` / `feishu_message_id` 上。
第 3 种除了既有的「在等人确认」,**再写一条站内通知**说清"只能在站内批"并带上那张单的 id ——
用户正等着群里那张卡,而它不会来了。第 1、2 种不喊。

## 取消 / 超时之后,飞书那边不留一张死卡

发出去过(`feishu_message_id` 非空)就把那条消息**就地收回成结果态**(已取消 / 超时),
让群里的人知道别再点了;没发出去过就跳过。这件事**在落库之后尽力做**(`after_commit`)——
取消必须是第一优先:更新卡片失败只记日志,不许把"单被撤销"这个结果弄回去。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.i18n import DEFAULT_LOCALE, t
from app.core.unit_of_work import after_commit, unit_of_work
from app.db.models import Job, User, Workflow, WorkflowRevision, WorkflowRunApproval, now
from app.domain.notifications import notify
from app.domain.workflows import WorkflowDomainError, as_text

logger = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
TIMED_OUT = "timeout"
CANCELLED = "cancelled"

#: 这一次等待**发到飞书没有**(那张单上 `feishu_delivery` 那一格,见模块说明)。
DELIVERY_SENT = "sent"
DELIVERY_FAILED = "failed"
DELIVERY_NOT_ATTEMPTED = "not_attempted"
DELIVERIES = (DELIVERY_SENT, DELIVERY_FAILED, DELIVERY_NOT_ATTEMPTED)

#: 决定那一格交给下游的三个值(节点输出 `decision`)。**三值文字而不是布尔**:条件节点里
#: `equals approved` 一条就说清,不受大小写 / 语言影响(见 node_types 的说明)。
DECISIONS = (APPROVED, REJECTED, TIMED_OUT)

#: 超时之后怎么办。
TIMEOUT_ABORT = "abort"
TIMEOUT_CONTINUE = "continue"
TIMEOUT_REMIND = "remind"
TIMEOUT_ACTIONS = (TIMEOUT_ABORT, TIMEOUT_CONTINUE, TIMEOUT_REMIND)

#: 拒绝之后怎么办。
REJECT_ABORT = "abort"
REJECT_BRANCH = "branch"
REJECT_ACTIONS = (REJECT_ABORT, REJECT_BRANCH)

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


def on_reject_of(config: dict[str, Any]) -> str:
    """拒绝之后怎么办。没写 = 中止(和超时同一个失败口径)。"""
    value = str(config.get("on_reject") or REJECT_ABORT).strip()
    return value if value in REJECT_ACTIONS else REJECT_ABORT


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
        on_reject=on_reject_of(config),
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


def ready_to_decide(row: WorkflowRunApproval) -> bool:
    """这张单**此刻批得动**吗:恢复现场(`checkpoint`)已经落库。

    执行器建单时**自己一个事务先提交**(它必须比卡片先落库,见 executors/approval),检查点由引擎在
    兄弟节点都落定之后写进 `_park_at_approval` 那次事务。这两件事之间有一段窗口:单是 `pending`、
    检查点还是空的 —— 这时批它只是落一个决定,而**没有现场可恢复**,那次运行醒不过来
    (决定赢了、运行永远停着;见 engine._park_at_approval 那道复查)。

    列表不列它,是因为在这段窗口里批它对谁都没有意义:`pending_for_*` 用它过滤。
    """
    return bool(row.checkpoint)


def pending_for_job(db: Session, job_id: str) -> WorkflowRunApproval | None:
    return next(
        (
            row
            for row in db.scalars(
                select(WorkflowRunApproval)
                .where(WorkflowRunApproval.job_id == job_id, WorkflowRunApproval.status == PENDING)
                .order_by(WorkflowRunApproval.created_at)
            )
            if ready_to_decide(row)
        ),
        None,
    )


def pending_for_workspace(db: Session, workspace_id: str) -> list[WorkflowRunApproval]:
    """这个工作区此刻在等确认的那些单(任务中心 / 运行详情那两处列表读它)。

    只列**已经可以批**的(见 `ready_to_decide`):单是执行器自己一个事务先提交的,检查点由引擎随后写
    —— 那一段窗口里这张单任何人都还没法批,列出来只是给人一个点了没反应的按钮。
    """
    return [
        row
        for row in db.scalars(
            select(WorkflowRunApproval)
            .where(
                WorkflowRunApproval.workspace_id == workspace_id,
                WorkflowRunApproval.status == PENDING,
            )
            .order_by(WorkflowRunApproval.created_at.desc())
        )
        if ready_to_decide(row)
    ]


def pending_for_workflow(db: Session, workflow_id: str) -> list[WorkflowRunApproval]:
    return [
        row
        for row in db.scalars(
            select(WorkflowRunApproval)
            .where(
                WorkflowRunApproval.workflow_id == workflow_id,
                WorkflowRunApproval.status == PENDING,
            )
            .order_by(WorkflowRunApproval.created_at.desc())
        )
        if ready_to_decide(row)
    ]


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
    """落决定并在**提交之后**叫醒那次运行。飞书卡片和应用内那两处唯一该调的入口。

    **赢下 CAS 的那一个还负责把飞书那张卡收回**(提交之后尽力做):在应用里批的那一下,群里那张
    卡如果还留着两个按钮,别人会以为这件事还欠着 —— 两处点哪个都算数,但卡片得跟着结果走。
    `via == "feishu"` 时跳过:那条路的**回调响应本身**就是把这张卡换成结果态(见
    integrations/feishu/approvals._handle_run_approval),再收一次是多余的。
    """
    if not decide(db, approval, decision=decision, user_id=user_id, user_name=user_name, note=note, via=via):
        return False
    if via != "feishu":
        approval_id = approval.id
        after_commit(db, lambda: retire_feishu_card(approval_id, decision))
    wake(db, approval)
    return True


def wake(db: Session, approval: WorkflowRunApproval) -> None:
    """把停在这张单上的那次运行接着派发出去(提交之后才真的起线程 —— 见 jobs.dispatch_job 的说明)。

    **带上这张单的 id。** 一次运行里可以有好几张单(图里串着两道门):不带 id 的时候"该从哪一张的
    现场接着跑"只能猜,而猜错就是从**上一道门**的现场重跑中间那些节点(见 `_resumable`)。

    这里顺手把这张单"已经派过一次恢复"的标记放下:决定是新的,这一次唤醒就该派得出去。
    """
    job_id = approval.job_id
    approval_id = approval.id
    _forget_resume(job_id, approval_id)
    after_commit(db, lambda: dispatch_resume(job_id, approval_id=approval_id))


def dispatch_resume(job_id: str, *, approval_id: str | None = None) -> bool:
    """重新进引擎把这次运行接着跑。返回是否真的派发了。

    认的是**这张单的检查点**:没有它就恢复不了(那是"这道门装出来之前就停下的一次运行"),
    这时什么都不做 —— 交给重启收尾 / 任务本身去说。`approval_id` 给定时认**那一张**
    (人的决定 / 超时走这条路);不给就是"**最新**那一张"(重启接回一个还在等的运行走这条路)。

    **同一个运行的一次等待只派一次**(`_RESUMED`):两条唤醒路(人的决定、重启 resumer)在毫秒级
    窗口里撞上时,第二次派发直接退回去。派出去就是同一张图在两条线程里各跑一遍,而检查点只记得住
    上次落定的那些节点 —— 两道门之间那些节点会**重跑**(实测:下游节点建了两行、按次计费的那一步
    付了两次)。

    **派发那一步由引擎自己登记进来**(见 `use_resume_dispatcher`):这个模块不许 import engine ——
    那就成了"引擎 ⇄ 工作流领域"的环(tests/test_import_layering 一个环都不许有)。
    方向反过来就干净了:引擎认识工作流的领域,领域不认识引擎。
    """
    dispatch = _RESUME_DISPATCHER
    if dispatch is None:  # pragma: no cover —— 引擎一被 import 就登记了
        logger.warning("no resume dispatcher registered; job %s stays parked", job_id)
        return False
    claimed = ""
    try:
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "running":
                return False
            approval = _resumable(db, job_id, approval_id=approval_id)
            if approval is None:
                return False
            if not _claim_resume(job_id, approval.id):
                logger.info(
                    "workflow job %s was already resumed from approval %s; this wake is ignored",
                    job_id, approval.id,
                )
                return False
            claimed = approval.id
            dispatch(db, job, approval.checkpoint or {})
            logger.info("workflow job %s resumed from approval %s", job_id, approval.id)
            return True
    except BaseException:  # 派发没成:标记还回去,否则这个运行再也唤不醒
        if claimed:
            _forget_resume(job_id, claimed)
        raise


#: 「这一次等待的恢复**已经派出去了**」的 per (运行, 单) 标记(进程内)。
#:
#: 它挡住的是"同一个等待被唤醒两次":人的决定与重启 resumer 撞上、或一次决定被重复投递。
#: 不用库里的格子记这件事,是因为这里要挡的正是**两次派发之间**那一段毫秒级窗口 —— 那一段里
#: 库里还没有任何可写的状态(派出去的那条线程还没跑到任何一步)。
#:
#: 标记在**恢复的那条运行落终态之后**放下(`resume_finished`,引擎在收尾时调):这样
#: "同一次等待"只派一次。下一道门是另一张单(approval id 不同),不需要先清掉旧标记。
_RESUMED: set[tuple[str, str]] = set()
_RESUMED_LOCK = threading.Lock()


def _claim_resume(job_id: str, approval_id: str) -> bool:
    with _RESUMED_LOCK:
        key = (job_id, approval_id)
        if key in _RESUMED:
            return False
        _RESUMED.add(key)
        return True


def _forget_resume(job_id: str, approval_id: str) -> None:
    with _RESUMED_LOCK:
        _RESUMED.discard((job_id, approval_id))


def resume_finished(job_id: str) -> None:
    """这次运行的恢复**已经收尾**:只在任务不再 `running` 时把标记放下。

    不能一律放下:恢复线程「跑完」和任务行落终态之间还隔着一次提交,而另一条唤醒路可能正好
    在这条缝里进来 —— 看到任务仍是 `running`,标记却已经被清掉,于是同一个等待被派第二次
    (此前在整套测试的负载下真的撞上过)。任务停在下一道门上时也仍是 `running`:那张新单的
    approval id 不同,旧标记留着不挡它,反而正好挡住「同一个等待」被重复派发。
    """
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is not None and job.status == "running":
            return
    with _RESUMED_LOCK:
        for key in [one for one in _RESUMED if one[0] == job_id]:
            _RESUMED.discard(key)


#: 「把暂停的运行接着派发出去」的实现 —— 引擎登记(engine.continue_workflow_job)。
_RESUME_DISPATCHER: Callable[[Session, Job, dict[str, Any]], None] | None = None


def use_resume_dispatcher(dispatch: Callable[[Session, Job, dict[str, Any]], None]) -> None:
    """登记"怎么把一次暂停的运行重新派发出去"。引擎是唯一知道这件事的人(见 dispatch_resume)。"""
    global _RESUME_DISPATCHER
    _RESUME_DISPATCHER = dispatch


def _resumable(db: Session, job_id: str, *, approval_id: str | None = None) -> WorkflowRunApproval | None:
    """这一次运行该接着跑吗:手里有一张带检查点的单、而且它的决定已经下来了(或者还在等)。

    还在等也接着跑:重启把它打断了,重新进去还是停在同一个节点上等 —— 卡片和单都不会重发。

    **`approval_id` 给定时认的就是那一张**(人的决定、“就这一张”的那次唤醒)。不给时认**最新**
    那一张:重启接回一个还在等的运行,眼前那道门就是它。

    **这里错一次,代价是重跑。** 一次运行里可以有好几张单(A → 门1 → B → 门2 → C):此前这里取的是
    "最早那张有检查点的",于是批第二道门时从**第一道门**的现场恢复 —— 门1 与门2 之间的 B 又跑了一遍
    (实测:Project 落 3 行而不是 2 行、B 起两次),而任务照样 succeeded,重跑被掩盖在"成功"里。
    检查点里本来就写着"已经落定到哪一步",取哪一张不能靠猜。
    """
    if approval_id:
        row = db.get(WorkflowRunApproval, approval_id)
        if row is None or row.job_id != job_id or row.status == CANCELLED or not row.checkpoint:
            return None
        return row
    rows = db.scalars(
        select(WorkflowRunApproval)
        .where(WorkflowRunApproval.job_id == job_id)
        .order_by(WorkflowRunApproval.created_at.desc())
    )
    return next((row for row in rows if row.checkpoint and row.status != CANCELLED), None)


# ---------------- 取消 ----------------


def cancel_for_job(db: Session, job: Job) -> None:
    """这次运行被停下了:它名下还在等的单一起撤掉 —— 否则卡片还点得动、列表里还挂着一条永远没人处理的等待。

    和取消**同一个事务**(见 jobs.register_cancel_listener):任务落了取消,这张单也就撤了。

    **飞书群里那张卡另说**:撤单是立刻的(同一个事务),把卡收回是**提交之后**尽力做的一步
    (`retire_feishu_card`)—— 顺序反过来就会让"改卡片"这件事有机会把取消本身弄失败,而取消必须
    是第一优先。发出去过才收;没发出去过就跳过。
    """
    retiring = list(
        db.scalars(
            select(WorkflowRunApproval.id).where(
                WorkflowRunApproval.job_id == job.id, WorkflowRunApproval.status == PENDING
            )
        )
    )
    changed = db.execute(
        update(WorkflowRunApproval)
        .where(WorkflowRunApproval.job_id == job.id, WorkflowRunApproval.status == PENDING)
        .values(status=CANCELLED, decided_via="cancel", decided_at=now(), updated_at=now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if not changed:
        return
    logger.info("cancelled %d pending approval(s) of job %s", changed, job.id)
    for approval_id in retiring:
        after_commit(db, lambda one=approval_id: retire_feishu_card(one, CANCELLED))


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
        if not ready_to_decide(row):
            #: 检查点还没落库:"这张单在等"这件事还没成立(见 ready_to_decide)。到点了也不能由
            #: 后台那一拍替它落一个决定 —— 没有现场,唤醒不了;等现场落下来的下一拍再处理它。
            continue
        if row.on_timeout == TIMEOUT_REMIND:
            #: **提醒也要走 CAS。** 直接改 ORM 对象的话,人到点前一刻批了、这一拍在同一瞬间把
            #: "还在等,已提醒"喊出去 —— 那条通知和外层那个决定自相矛盾,而且提醒的时刻还写回了行上。
            #: 一条 `WHERE status='pending'` 的 UPDATE:只有还真的在等才提醒。
            changed = db.execute(
                update(WorkflowRunApproval)
                .where(WorkflowRunApproval.id == row.id, WorkflowRunApproval.status == PENDING)
                .values(
                    expires_at=reference + timedelta(seconds=row.timeout_seconds or 0),
                    reminded_at=reference,
                    updated_at=reference,
                )
                .execution_options(synchronize_session=False)
            ).rowcount
            if not changed:
                continue
            db.refresh(row)
            handled += 1
            _notify_timeout(db, row, "wfNotice_awaitApprovalTimeoutRemind")
            #: **站内说了,飞书那边也要说一声。** 一个门禁悄悄地过期等于没装(ADR 0064 的原话:
            #: 三种都会再通知一次)—— 而只提醒站内的话,群里那张卡看上去还在等人点,那边的人不知
            #: 道这件事已经欠了一格。发出去过才收(没发出去过就跳过),失败只记日志、不影响"已提醒"。
            after_commit(db, lambda one=row.id: remind_feishu_card(one))
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
        #: 这一次等待结束了:发出去过的那张卡也该收回(提交之后尽力做,见 retire_feishu_card)。
        after_commit(db, lambda one=row.id: retire_feishu_card(one, TIMED_OUT))
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
    """把这次等待说出去:先站内通知(没有飞书也照样等),再尽力发一张飞书卡片,最后**记下投递结果**。

    **站内那一条是兜底,不是补充**:没有飞书绑定、飞书没配好、卡片能力没开,这次运行都照旧在等
    (需求里那句"不许因为没有飞书就报错或直接放行")。所以通知先写、卡片后发,卡片失败一律降级。

    **发给整个工作区**(和"工作流失败"那条通知同一个范围):一个门禁最坏的失败是没人看见。
    待批列表本来就是全工作区可见的(谁能批在决定那一步按成员校验),通知也就不挑人。

    **发不出去就再喊一声**:卡片和降级的文字都没出去时,除上面那条「在等人确认」之外**再写一条**
    (说清"只能在站内批"、带上那张单的 id,见 `_record_delivery`)—— 否则用户在群里等一张永远
    不会来的卡,而站内那条通知还在说"在飞书里点卡片也一样"。

    **只在检查点落库之后调**(见 engine._park_at_approval):先发卡、后落现场的话,手快的人在
    现场写下去之前点了确认,那次运行会卡在一个永远唤醒不了的等待上。

    **同一个等待只说一遍。** 重启把一次运行接回来时会**重新进到暂停那一步**(同一个节点、同一张单),
    引擎照样走到这里 —— 再说一遍就是第二条站内通知 + 第二张卡,而群里那张旧卡从此收不回来
    (`feishu_message_id` 被新的那张覆盖,取消 / 超时只会去收后来那张)。所以已经有投递记录的
    **只更新现场、不再说第二遍**:现场是引擎写的,这里直接退回去。
    空着(第一次暂停、或者上次还没说到就跑挂了)才说 —— 没说过的话,该说的还得说。
    """
    if approval.feishu_delivery or approval.feishu_message_id:
        logger.info(
            "approval %s was already announced (%s); not saying it again",
            approval.id, approval.feishu_delivery or approval.feishu_message_id,
        )
        return
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
    _record_delivery(db, approval, _announce_feishu(db, approval))


def _record_delivery(db: Session, approval: WorkflowRunApproval, delivery: Delivery) -> None:
    """把这一次投递的结果写在那张单上;发失败了就再写一条站内通知(见模块说明)。

    写在这张单上是**唯一出处**:界面照它说「已发飞书 / 仅站内(原因) / 发飞书失败(原因)」,
    取消和超时照 `feishu_message_id` 决定要不要去收回群里那张卡。
    """
    approval.feishu_delivery = delivery.status
    approval.feishu_delivery_reason = delivery.reason[:200]
    if delivery.status == DELIVERY_SENT and not approval.feishu_message_id:
        #: **最早那张卡的 id 不覆盖。** 取消 / 超时照它去收群里那张卡;后来真又发出去过一张的话,
        #: 至少原来那张收得回来 —— 覆盖掉就是"发了两张,一张也收不回来"。
        approval.feishu_message_id = delivery.message_id[:120]
    approval.updated_at = now()
    if delivery.status != DELIVERY_FAILED:
        return
    logger.warning("workflow approval %s never reached feishu: %s", approval.id, delivery.reason)
    notify(
        db,
        approval.workspace_id,
        type="workflow",
        title=t("wfNotice_awaitApprovalUndelivered", DEFAULT_LOCALE, title=approval.title),
        body=t(
            "wfNotice_awaitApprovalUndeliveredBody", DEFAULT_LOCALE,
            title=approval.title, approval=approval.id,
        ),
        link="#/workflows",
        payload={
            "approval_id": approval.id, "job_id": approval.job_id,
            "workflow_id": approval.workflow_id, "delivery": DELIVERY_FAILED,
        },
    )


def _workflow_name(db: Session, workflow_id: str) -> str:
    workflow = db.get(Workflow, workflow_id)
    return workflow.name if workflow is not None else workflow_id


@dataclass(frozen=True)
class Delivery:
    """这一次投递的结果:发到飞书了吗、为什么、发出去那条消息的 id。

    集成层(飞书那一侧)回答这三个问题 —— 只有它知道卡片和降级那段文字各自成没成、
    路由那一层解出来的又是什么。
    """

    status: str
    reason: str = ""
    message_id: str = ""


def _announce_feishu(db: Session, approval: WorkflowRunApproval) -> Delivery:
    """把确认卡推到飞书,并交回**结果**。**一律降级、绝不抛**(和工具确认卡同一条规矩):
    飞书那边出问题不该让这次运行跑不下去 —— 界面上要说清"没发出去",运行照旧在等。

    **实现由集成层在组装根登记**(见 `use_run_card_sender` 与 app.main._wire_seams):领域层不认识
    飞书 —— 飞书是**调用领域的一方**,不是领域要用的外部能力(见 tests/test_import_layering)。
    没人登记就是没接飞书:站内那条路已经发过了,这次运行照旧在等。
    """
    send = _RUN_CARD_SENDER
    if send is None:
        return Delivery(DELIVERY_NOT_ATTEMPTED, reason="not-wired")
    try:
        return send(db, approval) or Delivery(DELIVERY_FAILED, reason="发送这一步没有交回结果(实现没接上?)")
    except Exception as exc:  # noqa: BLE001 — 见 docstring
        logger.exception("feishu approval card failed approval=%s", getattr(approval, "id", "?"))
        return Delivery(DELIVERY_FAILED, reason=_reason_of(exc))


def _reason_of(exc: BaseException) -> str:
    """失败的原因:一句话,认不出别的就退到类名(空字符串在界面上什么也说不出来)。"""
    said = str(exc).strip()
    return said or type(exc).__name__


#: 「这一次等待说给飞书听」的实现。集成层在组装根登记;领域层只认"有人会替我发"。
#: 它**交回投递结果**(见 Delivery)—— 发没发出去是集成层知道的事,而"要不要在站内再喊一声"是领域的事。
_RUN_CARD_SENDER: Callable[[Session, WorkflowRunApproval], Delivery | None] | None = None


def use_run_card_sender(send: Callable[[Session, WorkflowRunApproval], Delivery | None]) -> None:
    """登记"把待批单发到飞书"的实现(见 integrations/feishu/approvals.announce_run_approval)。"""
    global _RUN_CARD_SENDER
    _RUN_CARD_SENDER = send


#: 「把飞书那条消息收回成结果态」的实现,同样由集成层在组装根登记
#: (见 integrations/feishu/approvals.settle_run_approval)。领域层只认"有人会替我改"。
_RUN_CARD_SETTLER: Callable[[Session, WorkflowRunApproval, str], None] | None = None


def use_run_card_settler(settle: Callable[[Session, WorkflowRunApproval, str], None]) -> None:
    """登记"把已经发出去的那张卡收回成结果态"的实现。

    `outcome` 是 `cancelled` / `timeout`(决定那一格的取值,集成层照它挑卡片标题),`remind` 那一档
    也走这里(见 `remind_feishu_card`:同一张卡换成"还在等,已提醒过一次")。
    领域这一侧只决定**什么时候**要收(取消 / 超时 / 提醒、而且发出去过),怎么收是集成层的事。
    """
    global _RUN_CARD_SETTLER
    _RUN_CARD_SETTLER = settle


def retire_feishu_card(approval_id: str, outcome: str) -> None:
    """这一次等待结束了,把飞书那张卡收回 —— **提交之后**尽力做,失败只记日志。

    自己有会话、自己提交(和 `announce_parked` 同一个理由:排进来的那一刻调用方的事务已经落了库,
    而这一步要读到那张单最新的样子),而且**整段包住**:更新卡片失败不许影响"单被撤销 / 已超时"
    这个已经落库的结果 —— 要收回的那张卡已经过期了,不是一个还要拦人的门。

    没发出去过就跳过(没有消息 id 可改,也不该为此报错):写了「仅站内」的单走的就是这一条。
    """
    _settle_feishu_card(approval_id, outcome, what="retiring")


def remind_feishu_card(approval_id: str) -> None:
    """`on_timeout=remind` 到点了:**在飞书那边也说一声这件事还在等**。

    和取消 / 超时走同一套原语(同一条消息就地更新),但 outcome 是 `remind` 那一档 —— 集成层照它
    **只补一句话、不把那张卡换成没有按钮的结果态**:门还开着,卡上那两个按钮还得点得动,
    换成"已拒绝 / 超时"那样一张卡会让人以为门已经过了,比不提醒更糟(见
    integrations/feishu/approvals.settle_run_approval)。

    ADR 0064 那句原话是"三种都会再通知一次 —— 一个门禁悄悄过期等于没装":只提醒站内的话,群里那张
    卡看上去还在等人点,那边的人不知道这件事已经欠了一格。

    没发出去过就跳过;失败只记日志,**不许影响"已提醒"这个已经落库的结果**(和取消 / 超时同一条规矩)。
    """
    _settle_feishu_card(approval_id, TIMEOUT_REMIND, what="reminding")


def _settle_feishu_card(approval_id: str, outcome: str, *, what: str) -> None:
    settle = _RUN_CARD_SETTLER
    if settle is None:
        return
    try:
        with unit_of_work() as db:
            row = db.get(WorkflowRunApproval, approval_id)
            if row is None or not row.feishu_message_id:
                return
            settle(db, row, outcome)
    except Exception:  # noqa: BLE001 —— 见 docstring:这一步坏掉不许把已经落库的结果弄回去
        logger.exception("%s feishu card of approval %s failed", what, approval_id)


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


def pinned_node(db: Session, job: Job, node_id: str) -> dict[str, Any]:
    """这个节点在**这次运行钉住的那一版修订**里长什么样(不是工作流当前那一版 —— 图可能已经改了)。

    「等人确认」的标题、以及**飞书那一面那三格**(channel / bot / to)都从这儿读:发卡发生在
    执行器那一轮过去很久之后(after_commit),那时手里只有这张单,而单上没有存配置的地方。
    读钉住的那一版而不是当前那一版,是因为**发出去的通知要照这次运行实际跑的那张图**。
    """
    revision_id = str((job.payload or {}).get("workflow_revision_id") or "")
    revision = db.get(WorkflowRevision, revision_id) if revision_id else None
    graph = revision.graph if revision is not None else {}
    return next(
        (
            one
            for one in (graph.get("nodes") or [])
            if isinstance(one, dict) and str(one.get("id")) == node_id
        ),
        {},
    )


def node_config(db: Session, approval: WorkflowRunApproval) -> dict[str, Any]:
    """这张待批单对应的那个节点当时是怎么配的(见 `pinned_node`)。找不到就是空配置。"""
    job = db.get(Job, approval.job_id)
    if job is None:
        return {}
    config = pinned_node(db, job, approval.node_id).get("config")
    return dict(config) if isinstance(config, dict) else {}
