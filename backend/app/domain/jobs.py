from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, event, inspect, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent
from app.db.models import now as models_now

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("succeeded", "failed")

# 「当前正在执行的父任务」——工作流引擎在跑某个子任务节点时把父 workflow job id 设进来,
# create_job 据此自动给派生的子 job 打上 parent_job_id(见 workflows/engine.py)。用 contextvar
# 而非显式穿参:子任务创建函数(start_publish/start_export/…)散落各领域,都汇聚到 create_job,
# 在此一处捕获最省事;非工作流路径下取默认 None,即顶层任务。每个节点在自己的线程里 set/reset,
# 线程间天然隔离。
_current_parent_job: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mosael_current_parent_job", default=None
)


def set_parent_job(job_id: str | None) -> contextvars.Token:
    """标记「后续 create_job 派生的都是 job_id 的子任务」。返回的 token 用于 reset_parent_job。"""
    return _current_parent_job.set(job_id)


def reset_parent_job(token: contextvars.Token) -> None:
    _current_parent_job.reset(token)


def current_parent_job_id() -> str | None:
    """当前正在执行的父任务 id(工作流节点里 = 本工作流 job);无则 None。"""
    return _current_parent_job.get()


#: 「接下来建的任务,干完了把回执寄给谁」。和 _current_parent_job 同一个做法。
#:
#: 用上下文变量而不是给每个 start_* 加一个参数:确认卡执行的是发布/导出/生成三种不同的活儿,
#: 各自有各自的入口函数。逐个加参数意味着**每加一种能被智能体触发的任务,都要再改一处**,
#: 而漏掉的那一处不会报错 —— 只是那种任务的回执永远送不到。
_current_receipt: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "mosael_current_receipt", default=None
)


def set_receipt(receipt: dict[str, Any] | None) -> contextvars.Token:
    """标记「后续 create_job 建的任务,终态时按这份回执通知」。返回的 token 用于 reset_receipt。"""
    return _current_receipt.set(receipt)


def reset_receipt(token: contextvars.Token) -> None:
    _current_receipt.reset(token)

# Children (ffmpeg, ASR/TTS workers) belonging to a running job, so cancelling can actually
# stop the work. Without this, cancel only flipped a database row: ffmpeg ran to completion,
# burning CPU the user had asked to stop, and then the worker overwrote the cancellation with
# "succeeded" — the cancelled export reappeared in the library as if nothing had happened.
_CHILDREN: dict[str, Any] = {}
_CHILDREN_LOCK = threading.Lock()


def register_job_child(job_id: str, child: Any) -> None:
    """Associate a killable child (anything with .kill()) with a job for its lifetime."""
    with _CHILDREN_LOCK:
        _CHILDREN[job_id] = child


def unregister_job_child(job_id: str) -> None:
    with _CHILDREN_LOCK:
        _CHILDREN.pop(job_id, None)


def kill_job_child(job_id: str) -> bool:
    """Stop the child of a running job, if one is registered. True if something was killed."""
    with _CHILDREN_LOCK:
        child = _CHILDREN.get(job_id)
    if child is None:
        return False
    child.kill()
    return True


# Admission control for work that is heavy in CPU, GPU or memory. There was none: ten
# simultaneous exports meant ten x264 encoders plus up to eighty concurrent ffprobes, and ten
# transcribes meant ten torch interpreters — near-certain OOM on a laptop. Acquire a slot
# BEFORE opening a database session, never while holding one; see _run_proxy for what the other
# order costs. A sleeping thread is cheap, a pinned connection is not.
RENDER_SLOTS = threading.Semaphore(2)
ASR_SLOTS = threading.Semaphore(1)      # torch/funasr: one model in memory at a time
TTS_SLOTS = threading.Semaphore(1)
GENERATION_SLOTS = threading.Semaphore(4)  # mostly waiting on a remote API


def run_job_guarded(job_id: str, body: Callable[[], None], *, what: str = "job") -> None:
    """Run a worker body so that no failure can leave the job silently queued.

    Every worker began with `db.get(Job, job_id)` OUTSIDE its try. That is the call that checks
    a connection out of the pool, so when the pool was exhausted it raised, the daemon thread
    died, and the row stayed `queued` with no error — forever, since reconcile only runs at
    startup. A backfill of 60 videos produced 45 such jobs.

    Anything the body does not handle is recorded on the job here instead.
    """
    try:
        body()
    except Exception as exc:  # noqa: BLE001 — a worker thread must never die silently
        logger.exception("%s worker crashed (job=%s)", what, job_id)
        try:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job is not None and job.status not in TERMINAL_STATUSES:
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    say(job, "jobMsg_genericFailed", what=what)
                    db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"stage": "worker"}))
                    db.commit()
        except Exception:  # noqa: BLE001 — the DB is what failed; nothing left to try
            logger.exception("could not record the failure of %s %s", what, job_id)


def say(job: Job, key: str, **params: object) -> None:
    """给任务写一句「给人看的话」。**只有这一个入口。**

    同时写三样:key、参数、以及用缺省语言渲染出来的 message。
      ・key + 参数 → 接口按**请求方的语言**翻(见 core/i18n 与 JobOut);
      ・message → 给不翻译的消费者(工作流把子任务消息拼进自己的错误里、日志、直接读库的脚本)。

    为什么不只存 key:这一列**落库**,任务记录活得比一次请求久,写入时就翻会把语言冻死在那一刻 ——
    用户切成英文后历史任务仍是中文,而那正是这次要修的毛病。
    """
    from app.core.i18n import DEFAULT_LOCALE, t

    job.message_key = key
    job.message_params = {k: str(v) for k, v in params.items()}
    job.message = t(key, DEFAULT_LOCALE, **job.message_params)


def finish_job(db: Session, job: Job, **fields: Any) -> bool:
    """Write a terminal state unless the job already reached one.

    Workers held a Job loaded at the start of the run and assigned to it at the end, so a
    cancellation landing in between was silently clobbered. Re-read first and skip the write if
    the job is already settled; the caller uses the return value to skip the rest of its
    success path too (registering an export as an asset, emitting job.succeeded).
    """
    # **先看手里这一份**,再去库里对。只 refresh 的话,本次事务里还没提交的终态会被库里的
    # 旧值冲掉 —— 于是同一个 job 连着 finish 两次,两次都返回 True,最终状态由后一次说了算,
    # 而回执也会发两封(一封说成功、一封说失败)。refresh 要挡的是**别的会话**写进来的取消,
    # 它挡不了自己刚写的那一笔。
    if job.status in TERMINAL_STATUSES:
        return False
    db.refresh(job)
    if job.status in TERMINAL_STATUSES:
        return False
    for key, value in fields.items():
        setattr(job, key, value)
    status = fields.get("status")
    # 「这个任务慢」是最常见的一类反馈,而排查它需要的第一个数字就是耗时。此前这两行只有
    # id 和 kind:要知道一个转写跑了三分钟还是三十秒,只能自己去数据库里减两个时间戳。
    took = _elapsed(job)
    if status == "failed":
        logger.warning("job %s [%s] failed after %s: %s", job.id, job.kind, took,
                       fields.get("error") or fields.get("message") or "")
    elif status == "succeeded":
        logger.info("job %s [%s] succeeded in %s", job.id, job.kind, took)
    return True


#: 「这活儿干完了,回执寄给谁」。key 是收信方的种类,值是那一类怎么送。
#:
#: **任务这一层不认识收信方** —— 智能体自己在装配时登记(app/main.py),就像 tts_runtime_config
#: 那样。反过来写(在这里 import domain.agent)会让任务域依赖智能体域,而任务是更底下那一层:
#: 发布、导出、转写都建任务,它们没有一个该因为「智能体也许想知道」而认识智能体。
_RECEIPT_DELIVERERS: dict[str, Callable[[Session, Job, dict[str, Any]], None]] = {}


def register_receipt_deliverer(kind: str, deliver: Callable[[Session, Job, dict[str, Any]], None]) -> None:
    """登记一种回执的送法。同名后登记的覆盖先登记的。"""
    _RECEIPT_DELIVERERS[kind] = deliver


#: 这次事务里刚落终态、等着送回执的 job id。挂在 session.info 上而不是模块级 ——
#: 后台线程各有各的 session,模块级变量会让两个线程的回执串到一起。
_PENDING_RECEIPTS = "mosael_pending_receipts"


@event.listens_for(Session, "after_flush")
def _note_settled_jobs(session: Session, _flush_context: Any) -> None:
    """记下这次 flush 里**刚进终态**的任务。

    **挂在状态变化上,不挂在某个函数上。** 回执最初挂在 finish_job 里,而全仓库只有
    render.py 走它 —— 生成、发布、配音、代理、从链接导入全是直接 `job.status = ...`。
    于是回执挂在了一条几乎没人走的路上:智能体提交完生成、任务失败了,它一无所知。

    只认「**从非终态进终态**」这一次跳变:一个已经 failed 的行再被写一次别的字段,
    不该再发一封。
    """
    for obj in session.dirty:
        if not isinstance(obj, Job):
            continue
        history = inspect(obj).attrs.status.history
        if not history.has_changes():
            continue
        was = history.deleted[0] if history.deleted else None
        if obj.status in TERMINAL_STATUSES and was not in TERMINAL_STATUSES:
            session.info.setdefault(_PENDING_RECEIPTS, []).append(obj.id)


@event.listens_for(Session, "after_commit")
def _deliver_settled_receipts(session: Session) -> None:
    """提交之后才送。

    送信会写库(往对话里放一条消息)、还会叫醒一个智能体回合 —— 在 flush 里做的话,
    它看到的是一份还没提交的任务状态,而万一外层回滚,消息已经发出去了。
    """
    job_ids = session.info.pop(_PENDING_RECEIPTS, None)
    if not job_ids:
        return
    # 用**新的** session:调用方那个刚提交完,在它上面接着写会把这次送信卷进调用方的
    # 下一个事务里 —— 而调用方随时可能回滚。
    from app.core.db import SessionLocal

    with SessionLocal() as fresh:
        for job_id in job_ids:
            job = fresh.get(Job, job_id)
            if job is None:
                continue
            receipt = (job.payload or {}).get("receipt")
            if not isinstance(receipt, dict):
                continue
            deliver = _RECEIPT_DELIVERERS.get(str(receipt.get("kind") or ""))
            if deliver is None:
                continue
            try:
                deliver(fresh, job, receipt)
            except Exception:
                # 回执送不到**不能**把任务弄失败 —— 活儿已经干完了,产物已经在库里。
                # 吞掉但记下来:没有日志的话,「智能体不知道任务结束了」会查成一个玄学问题。
                logger.warning("job %s [%s] 回执没送到 (%s)", job.id, job.kind, receipt.get("kind"), exc_info=True)


def _elapsed(job: Job) -> str:
    """从建任务到现在。**含排队时间** —— 那正是"慢"最常见的去处。"""
    created = getattr(job, "created_at", None)
    if created is None:
        return "?"
    # models_now 是这个仓库里「现在」的唯一写法(naive UTC,和列里存的一致)。
    seconds = max(0.0, (models_now() - created).total_seconds())
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 90:
        return f"{seconds:.1f}s"
    return f"{int(seconds) // 60}m{int(seconds) % 60:02d}s"
# Retention (plan §12.3): active jobs keep every event; terminal jobs keep the
# most recent few; terminal jobs older than the window lose all detail events.
TERMINAL_KEEP_EVENTS = 5
EVENT_RETENTION_DAYS = 30


# ---------- 执行模式接缝 ----------
#
# 每种 job kind 声明由谁执行,两个适配器:
#
# - "in_process"(默认):领域模块 spawn 守护线程,进程死任务亡——重启时 reconcile 判失败。
# - "external":外部 worker 经 claim/report 协议(/api/jobs/worker/*,worker key 鉴权)驱动,
#   任务跨后端重启存活。发布器是第一个外部 worker;任何计算类 kind(render/transcribe…)
#   都可以经 MOSAEL_EXTERNAL_JOB_KINDS 或 register_external_kind() 翻成 external,
#   由团队服务器旁的独立 worker 机器认领——这是"多机"的接缝,不是新架构。
#
# publish 由 publish 领域自己注册(app/domain/publish/__init__.py);
# 任务总线不点名任何具体领域。
_EXECUTION_MODES: dict[str, str] = {}


def register_external_kind(kind: str) -> None:
    _EXECUTION_MODES[kind] = "external"


def execution_mode(kind: str) -> str:
    return _EXECUTION_MODES.get(kind, "in_process")


def external_kinds() -> tuple[str, ...]:
    return tuple(sorted(k for k, mode in _EXECUTION_MODES.items() if mode == "external"))


#: 每个在进程内跑的 job 线程都叫这个名字 —— 派发点只有 dispatch_job 一处,所以名字必然覆盖全部。
#: 见 `wait_for_idle_jobs` 及它在 tests/util.fresh_client 里的用处。
JOB_THREAD_NAME = "job-run"


def wait_for_idle_jobs(timeout: float = 5.0) -> bool:
    """Block until no in-process job thread is running. Returns False if `timeout` ran out.

    和 agent 的 `wait_for_idle_turns` 同一个道理,只是这里挡的是 job:请求返回时线程才刚起步,
    真正的活(转写、配音、导出、生成)全在返回之后。生产里无所谓——进程比 job 活得久;测试里
    下一步就要 drop_all,掉队的线程会撞进正在重建的库,炸成 `no such table: jobs`,而且这个异常
    会记在**当时恰好在跑的那条用例**头上,与真凶无关。典型的"单独跑绿、全量跑红、CI 更容易红"。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [t for t in threading.enumerate() if t.name == JOB_THREAD_NAME and t.is_alive()]
        if not alive:
            return True
        alive[0].join(timeout=max(0.0, deadline - time.monotonic()))
    return not any(t.name == JOB_THREAD_NAME and t.is_alive() for t in threading.enumerate())


def dispatch_job(db: Session, job: Job, thread_target: Callable[[], None]) -> bool:
    """按 kind 的执行模式派发一个刚创建的 job。

    in_process → 立刻 spawn 守护线程(现状不变);external → 什么都不做,留在
    queued 等外部 worker 认领。领域模块只描述「怎么跑」(thread_target),
    「由谁跑」是总线的决定——这样把一个 kind 挪到外部 worker 不需要改领域代码。
    Returns True when a thread was started in-process.
    """
    if execution_mode(job.kind) == "external":
        say(job, "jobMsg_waitingWorker")
        db.add(TaskEvent(job_id=job.id, type="job.awaiting_worker", payload={}))
        db.commit()
        logger.info("job %s [%s] queued for external worker", job.id, job.kind)
        return False
    db.commit()
    threading.Thread(target=thread_target, name=JOB_THREAD_NAME, daemon=True).start()
    logger.info("job %s [%s] dispatched in-process", job.id, job.kind)
    return True


def emit_job_event(db: Session, job_id: str, type: str, payload: dict[str, Any] | None = None) -> None:
    """在任务总线上发一条事件(不 commit,跟随调用方事务)。

    TaskEvent 行只在总线创建——领域模块经这里发事件,而不是自己 `db.add(TaskEvent(...))`
    (数据归属规约,见 ownership.py)。这也是未来把「job 终态 → 站内通知」做成事件
    消费者的挂点。
    """
    db.add(TaskEvent(job_id=job_id, type=type, payload=payload or {}))


def create_job(
    db: Session,
    *,
    workspace_id: str,
    kind: str,
    payload: dict[str, Any],
    created_by: str | None,
    message: str = "Queued",
    message_params: dict[str, Any] | None = None,
    parent_job_id: str | None = None,
) -> Job:
    """建一个后台任务。

    `created_by` 是**必填**关键字(可以是 None,但必须显式写出来):后台线程手里只有一个 job,
    它得能答出这活儿替谁干 —— 用谁的钥匙、花谁的额度。做成必填参数而不是可选,是因为漏掉的
    那个调用点会安静地建出一个无主任务,然后在运行时退回"随便找一把钥匙"。
    """
    # 显式传入优先;否则取当前工作流上下文(工作流节点里派生的子任务自动归到父 job 下)。
    parent = parent_job_id if parent_job_id is not None else _current_parent_job.get()
    receipt = _current_receipt.get()
    if receipt is not None and "receipt" not in payload:
        payload = {**payload, "receipt": receipt}
    job = Job(
        workspace_id=workspace_id, kind=kind, payload=payload,
        parent_job_id=parent, created_by=created_by,
    )
    # `message` 收的是 i18n 的 key(见 say 的说明);认不出来就当成字面量,原样存下 ——
    # "Queued" 这种缺省值、以及外部塞进来的自由文本都还能用。
    say(job, message, **(message_params or {}))
    db.add(job)
    db.flush()
    # 事件里存 **key + 参数 + 缺省语言渲染的那句**,不是光存 key:界面上「执行记录」直接显示
    # payload.message,只存 key 的话用户看到的就是 `jobMsg_ttsRunning` 这种东西(真出过)。
    # 三样都留着,出口才能按请求方的语言重翻,而不翻的消费者也有一句人话可读 —— 与 say 同构。
    db.add(TaskEvent(
        job_id=job.id,
        type="job.queued",
        payload={
            "message_key": job.message_key,
            "message_params": job.message_params,
            "message": job.message,
        },
    ))
    logger.info("job %s [%s] created (workspace=%s)", job.id, kind, workspace_id)
    return job


def current_actor(db: Session) -> str | None:
    """当前工作流 job 的操作人。

    工作流节点派生的子任务替的是**同一个人** —— 执行器签名是固定的 `(db, workflow, config)`,
    拿不到调用者,但父 job 上记着这活儿是替谁干的,而子任务与父任务的关系本来就是显式建立的
    (见 `_current_parent_job`)。
    """
    parent = _current_parent_job.get()
    job = db.get(Job, parent) if parent else None
    return job.created_by if job is not None else None


def reconcile_orphaned_jobs(db: Session) -> int:
    """Fail in-process jobs left `queued`/`running` by a backend restart.

    Their daemon-thread workers cannot survive the process, so they would
    otherwise sit frozen at their last progress forever. Publish jobs are exempt
    (external worker). Returns the number of jobs reconciled.
    """
    stale = db.scalars(
        select(Job)
        .where(Job.status.in_(("queued", "running")))
        .where(Job.kind.notin_(external_kinds()))
    ).all()
    for job in stale:
        job.status = "failed"
        say(job, "jobMsg_interrupted")
        job.error = "后端重启导致任务中断,请重新发起"
        db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"reason": "backend_restart"}))
    if stale:
        db.commit()
    return len(stale)


def _cancel_job_row(db: Session, job: Job) -> bool:
    """把单个 job 落取消态 + 掐子进程 + 撤发布单(不 commit)。返回它是否原本还在跑。"""
    if job.status not in ("queued", "running"):
        return False
    job.status = "failed"
    job.error = "已取消"
    say(job, "jobMsg_cancelled")
    db.add(TaskEvent(job_id=job.id, type="job.cancelled", payload={}))
    # Stop the actual work, not just the row describing it.
    if kill_job_child(job.id):
        db.add(TaskEvent(job_id=job.id, type="job.child_killed", payload={}))
    if job.kind == "publish":
        from app.db.models import PublishTask

        task = db.scalar(select(PublishTask).where(PublishTask.job_id == job.id))
        if task is not None and task.status not in ("success", "failed", "cancelled"):
            task.status = "cancelled"  # 桌面发布器下次 report/heartbeat 读到 cancelled 即中止自动化
    return True


def cancel_job(db: Session, job: Job) -> Job:
    """用户主动取消:job 落终态,发布任务同步撤单,工作流在节点边界停下。

    线程内正在执行的节点无法安全掐断;engine 每个节点边界都会重读 job 状态,看到已取消
    就不再继续——"停止中断"语义是节点粒度的。**级联**到工作流派生的子任务(发布/导出/转写/生成/
    配音):否则父流取消了,发布子任务还在桌面发布器里跑(见 parent_job_id 链)。
    """
    if job.status not in ("queued", "running"):
        raise ValueError("任务已结束,无法取消")
    _cancel_job_row(db, job)
    # 广度遍历后代,连嵌套子工作流一并取消。
    frontier, seen = [job.id], {job.id}
    while frontier:
        parent_id = frontier.pop()
        children = db.scalars(
            select(Job).where(Job.parent_job_id == parent_id, Job.status.in_(("queued", "running")))
        ).all()
        for child in children:
            if child.id in seen:
                continue
            seen.add(child.id)
            _cancel_job_row(db, child)
            frontier.append(child.id)
    db.commit()
    db.refresh(job)
    logger.info("job %s [%s] cancelled by user (cascaded %d descendants)", job.id, job.kind, len(seen) - 1)
    return job


# ---------- 通用 worker 协议(claim / report) ----------
#
# 发布器验证过的拉取模式,推广给所有 external kind:worker 主动认领(CAS 原子翻
# running)、富状态回报、后端从不反向连接 worker。publish 因历史契约仍走
# /api/publish/worker/*(任务粒度是 PublishTask);其余 external kind 走这里。

CLAIMABLE_STATUSES = ("queued",)


def claim_next_job(db: Session, *, kinds: list[str] | None = None, worker: str = "") -> Job | None:
    """认领最老的一条可认领 job 并原子翻成 running。

    只允许认领 external 模式的 kind——in_process 的 kind 已有线程在跑,被外部
    worker 抢走会双跑。CAS(status 仍是 queued 才更新)保证并发认领不重复。
    """
    allowed = set(external_kinds())
    if kinds:
        allowed &= set(kinds)
    if not allowed:
        return None
    while True:
        job = db.scalars(
            select(Job)
            .where(Job.status.in_(CLAIMABLE_STATUSES), Job.kind.in_(sorted(allowed)))
            .order_by(Job.created_at)
            .limit(1)
        ).first()
        if job is None:
            return None
        # 这里走的是 UPDATE 语句(不是 ORM 对象),所以不能用 say();两栏一起写,含义与它一致。
        from app.core.i18n import DEFAULT_LOCALE, t

        claimed = db.execute(
            Job.__table__.update()
            .where(Job.id == job.id, Job.status.in_(CLAIMABLE_STATUSES))
            .values(
                status="running",
                message_key="jobMsg_claimed",
                message=t("jobMsg_claimed", DEFAULT_LOCALE),
            )
        ).rowcount
        if claimed:
            db.add(TaskEvent(job_id=job.id, type="job.claimed", payload={"worker": worker}))
            db.commit()
            db.refresh(job)
            logger.info("job %s [%s] claimed by worker=%s", job.id, job.kind, worker or "?")
            return job
        db.rollback()  # 另一个 worker 抢先了;重试下一条


def report_job(
    db: Session,
    job: Job,
    *,
    status: str,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> Job:
    """外部 worker 回报:running 更新进度,succeeded/failed 落终态。

    与发布器同一条规则:已终态(含用户取消)的 job 不给后到的回报复活——
    worker 是在为一个已经不存在的意图干活,结果只能丢弃。
    """
    if status not in ("running", "succeeded", "failed"):
        raise ValueError(f"未知回报状态: {status}")
    db.refresh(job)
    if job.status in TERMINAL_STATUSES:
        return job
    if status == "running":
        if progress is not None:
            job.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            say(job, message)
        db.add(TaskEvent(job_id=job.id, type="job.progress", payload={"progress": job.progress}))
    else:
        job.status = status
        if message is not None:
            say(job, message)
        if status == "failed":
            job.error = (error or message or "worker 报告失败")[:500]
            logger.warning("job %s [%s] failed (external worker): %s", job.id, job.kind, job.error)
        else:
            job.progress = 1.0
            if result is not None:
                job.result = result
            logger.info("job %s [%s] succeeded (external worker)", job.id, job.kind)
        db.add(TaskEvent(job_id=job.id, type=f"job.{status}", payload={}))
    db.commit()
    db.refresh(job)
    return job


def prune_task_events(db: Session, *, now: datetime | None = None) -> int:
    """Apply the retention rules to task_events. Returns rows deleted."""
    reference = now or models_now()  # utcnow() is deprecated; models_now is the same naive UTC
    cutoff = reference - timedelta(days=EVENT_RETENTION_DAYS)
    removed = 0

    terminal_jobs = db.scalars(select(Job).where(Job.status.in_(TERMINAL_STATUSES))).all()
    for job in terminal_jobs:
        if job.updated_at < cutoff:
            result = db.execute(delete(TaskEvent).where(TaskEvent.job_id == job.id))
            removed += result.rowcount or 0
            continue
        keep_ids = list(
            db.scalars(
                select(TaskEvent.id)
                .where(TaskEvent.job_id == job.id)
                .order_by(TaskEvent.created_at.desc())
                .limit(TERMINAL_KEEP_EVENTS)
            )
        )
        result = db.execute(
            delete(TaskEvent).where(TaskEvent.job_id == job.id, TaskEvent.id.not_in(keep_ids))
        )
        removed += result.rowcount or 0
    db.commit()
    return removed


def clear_finished_jobs(db: Session, workspace_id: str) -> int:
    """Remove terminal jobs (their events cascade). Returns jobs deleted."""
    jobs = db.scalars(
        select(Job).where(Job.workspace_id == workspace_id, Job.status.in_(TERMINAL_STATUSES))
    ).all()
    for job in jobs:
        db.execute(delete(TaskEvent).where(TaskEvent.job_id == job.id))
        db.delete(job)
    db.commit()
    return len(jobs)
