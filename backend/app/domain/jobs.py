from __future__ import annotations

import contextvars
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, event, inspect, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.i18n import DEFAULT_LOCALE, LocalizedError, t
from app.db.models import Job, TaskEvent
from app.db.models import now as models_now

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("succeeded", "failed")


def was_cancelled(job: Any) -> bool:
    """这个任务是不是被人取消的。

    总线把「被取消」记成 failed + jobErr_cancelled(见 _cancel_job_row),没有单独的状态。
    对外要分开说的地方(外部钩子、画板上那一格)都问这一处 —— 各自判一遍的话,哪天取消换了
    记法,漏改的那一处就把「我自己停掉的」说成「跑挂了」。
    """
    return getattr(job, "status", None) == "failed" and getattr(job, "error_key", None) == "jobErr_cancelled"

# 「当前正在执行的父任务」:之后 create_job 建出来的任务,都挂在它下面(ADR-0018)。
#
# 两个来源,强弱不同:
# - **strict** —— 工作流引擎每个节点、定时调度:父任务一旦结束(比如被取消),就拒绝再派生;
# - **derived** —— 任务自己的执行体(dispatch_job 设的):父任务刚结束也照样挂上去 ——
#   导出在收尾时登记产物、顺手排代理转码,那一刻导出已经是 succeeded。
#
# 用 contextvar 而非显式穿参:派生任务的入口(start_publish/start_export/…)散落各领域,都汇聚到
# create_job,在此一处捕获。**线程不继承 contextvar**,所以每个起线程的地方都要自己设 ——
# dispatch_job 替所有任务设了;工作流节点和循环在各自的线程池里设。
@dataclass(frozen=True)
class _ParentJob:
    job_id: str
    strict: bool


_current_parent_job: contextvars.ContextVar[_ParentJob | None] = contextvars.ContextVar(
    "mosael_current_parent_job", default=None
)


def set_parent_job(job_id: str | None, *, strict: bool = True) -> contextvars.Token:
    """标记「后续 create_job 派生的都是 job_id 的子任务」。返回的 token 用于 reset_parent_job。"""
    return _current_parent_job.set(_ParentJob(job_id, strict) if job_id else None)


def reset_parent_job(token: contextvars.Token) -> None:
    _current_parent_job.reset(token)


def current_parent_job_id() -> str | None:
    """当前正在执行的父任务 id;无则 None。"""
    parent = _current_parent_job.get()
    return parent.job_id if parent else None


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


#: 这一次 HTTP 请求里建出来的任务。中间件在请求开始时放一个空列表进来,create_job 往里记,
#: 请求结束时有记录就在响应头上告诉前端(见 app/api/middleware 的 AnnounceNewJobs)。
#:
#: 为什么在总线上记,而不是让每个「开始 xx」的按钮自己去刷新任务中心:建任务的接口有几十个,
#: 返回的也不都是 job(生成返回会话、画板返回画板、确认卡返回确认卡)。此前只有少数几处记得
#: 刷新,其余的(人声分离、转写、导出……)要等任务中心下一轮轮询 —— 空闲时 8 秒一次,
#: 用户看到的就是「点了开始,好几秒后任务才进队列」。
#:
#: 后台线程里派生的子任务不会记进来:新线程不继承 contextvar,而那时请求早已结束。
_request_new_jobs: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "mosael_request_new_jobs", default=None
)


def watch_new_jobs() -> tuple[list[str], contextvars.Token]:
    """从现在起记下建出来的任务 id。返回那份列表和用于 stop_watching_new_jobs 的 token。"""
    created: list[str] = []
    return created, _request_new_jobs.set(created)


def stop_watching_new_jobs(token: contextvars.Token) -> None:
    _request_new_jobs.reset(token)

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
    # Cancellation may have committed before the subprocess existed.
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            child.kill()


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
                if job is not None and finish_job(db, job, status="failed", error=str(exc)[:500]):
                    say(job, "jobMsg_genericFailed", what=what)
                    db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"stage": "worker"}))
                    db.commit()
        except Exception:  # noqa: BLE001 — the DB is what failed; nothing left to try
            logger.exception("could not record the failure of %s %s", what, job_id)


def run_job_inline(
    db: Session,
    job: Job,
    body: Callable[[], dict[str, Any]],
    *,
    running: str,
    done: str,
) -> bool:
    """在调用方自己的线程里把一个任务跑完 —— 给「几秒就回、调用方等着要结果」的活儿(画板上写字)。

    收尾和派发出去的任务是同一套:起步、成功、**任何一种异常**都经 finish_job 落终态,回执随
    状态跳变送出(见 _after_jobs_settled)。执行体抛出的异常在任务落成失败**之后**原样抛回,
    调用方照旧按类型翻成 HTTP —— 没有哪条异常路径能把任务(和挂着它的那一格)留在「运行中」。
    进程在中途没了的,重启时 reconcile_orphaned_jobs 同样收掉它。

    `body` 回任务的 result。返回 True 表示成功落了终态;False 表示跑之前或跑的时候被取消了
    (这时结果作废,终态由取消那一侧写)。
    """
    if not finish_job(db, job, status="running"):
        db.commit()
        return False
    say(job, running)
    emit_job_event(db, job.id, "job.running", {})
    db.commit()
    try:
        result = body()
    except BaseException as exc:
        # 执行体可能把会话留在一个坏掉的事务里 —— 先回滚,再在同一个会话上落失败。
        db.rollback()
        try:
            if finish_job(db, job, status="failed", **blame(exc)):
                emit_job_event(db, job.id, "job.failed", {"stage": "inline"})
            db.commit()
        except Exception:  # noqa: BLE001 — 库本身出了问题;原来那个异常更要紧
            logger.exception("could not record the failure of job %s", job.id)
        raise
    if not finish_job(db, job, status="succeeded", progress=1.0, result=result):
        db.commit()
        return False
    say(job, done)
    emit_job_event(db, job.id, "job.succeeded", {})
    db.commit()
    return True


class JobError(LocalizedError, ValueError):
    """任务这一层说不行(已结束、租约不对)。带文案 key(`jobErr_*`);是 ValueError,调用方照旧翻成 409。"""


def say(job: Job, key: str, **params: object) -> None:
    """给任务写一句「给人看的话」。**只有这一个入口。**

    同时写三样:key、参数、以及用缺省语言渲染出来的 message。
      ・key + 参数 → 接口按**请求方的语言**翻(见 core/i18n 与 JobOut);
      ・message → 给不翻译的消费者(工作流把子任务消息拼进自己的错误里、日志、直接读库的脚本)。

    为什么不只存 key:这一列**落库**,任务记录活得比一次请求久,写入时就翻会把语言冻死在那一刻 ——
    用户切成英文后历史任务仍是中文,而那正是这次要修的毛病。
    """
    from app.core.i18n import DEFAULT_LOCALE, is_message_key, render_message

    #: 有几处传进来的是一句现成的话(子任务转述的消息、第三方的原话)。它不是 key,不该当 key
    #: 落库 —— 否则读的时候会被当模板再填一遍(见 core/i18n.is_message_key)。
    job.message_key = key if is_message_key(key) else ""
    job.message_params = {k: str(v) for k, v in params.items()}
    job.message = render_message(key, DEFAULT_LOCALE, job.message_params)


def blame(exc: Exception) -> dict[str, Any]:
    """一个异常 → 写进任务失败原因的那三样(`error` / `error_key` / `error_params`)。

    和 `say` 同构,只是另一半:**落库的那句话不该冻住语言**。领域异常带 key 的(见
    workflows.WorkflowDomainError)就把 key 和参数一起记上,接口按读的人的语言翻;
    不带 key 的(第三方库、别的领域)只留那句话 —— 那是它自己的文本,我们翻不了。

    传给 `finish_job(**blame(exc))` 用,所以返回的是字段名对得上的一份字典。
    """
    from app.core.i18n import is_message_key

    key = str(getattr(exc, "key", "") or "")
    params = getattr(exc, "params", None)
    return {
        "error": str(exc)[:500],
        #: 不截断:截断的 key 就不是 key 了。此前的 `[:80]` 正是一句 403 报错被切成"半截 key"的地方。
        "error_key": key if is_message_key(key) else "",
        "error_params": {k: str(v) for k, v in (params or {}).items()},
    }


def lock_active_job(db: Session, job: Job) -> bool:
    """Acquire the SQLite write transaction before reading/changing an active job.

    The conditional no-op update closes the refresh→commit cancellation race while
    keeping ORM status history (and terminal receipts) intact. Caller commits promptly.
    """
    if job.status in TERMINAL_STATUSES:
        return False
    with db.no_autoflush:
        changed = db.execute(
            Job.__table__.update().where(Job.id == job.id, Job.status.in_(("queued", "running")))
            .values(status=Job.status, updated_at=Job.updated_at)
        ).rowcount
        # Preserve this transaction's pending changes, including ORM terminal-state receipts.
        if not changed:
            db.refresh(job)
    return bool(changed)


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
    if not lock_active_job(db, job):
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


#: 「任务落了终态,谁要跟着收拾」。和回执同一道缝、同一个方向:任务这一层不认识那些**随某个
#: 任务而生**的资源(工作流这次运行开的浏览器会话……),是持有它们的那一域在装配时登记进来
#: (app/main.py)。
#:
#: 挂在同一个状态跳变上,所以成功、失败、**取消**都走得到。取消不经过执行体的收尾代码 ——
#: 执行体那时可能正阻塞在某个等待里 —— 能在那一刻接住它的只有这里。
_SETTLE_LISTENERS: dict[str, Callable[[Session, Job], None]] = {}


def register_settle_listener(name: str, listener: Callable[[Session, Job], None]) -> None:
    """登记一个「任务落终态之后」的收拾动作。同名后登记的覆盖先登记的。"""
    _SETTLE_LISTENERS[name] = listener


#: 这次事务里刚落终态的 job id(等着收拾、送回执)。挂在 session.info 上而不是模块级 ——
#: 后台线程各有各的 session,模块级变量会让两个线程的回执串到一起。
_PENDING_SETTLED = "mosael_pending_settled_jobs"


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
            session.info.setdefault(_PENDING_SETTLED, []).append(obj.id)


@event.listens_for(Session, "after_commit")
def _after_jobs_settled(session: Session) -> None:
    """提交之后才收拾、才送。

    送信会写库(往对话里放一条消息)、还会叫醒一个智能体回合 —— 在 flush 里做的话,
    它看到的是一份还没提交的任务状态,而万一外层回滚,消息已经发出去了。收拾同理。
    """
    job_ids = session.info.pop(_PENDING_SETTLED, None)
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
            for name, listener in list(_SETTLE_LISTENERS.items()):
                try:
                    listener(fresh, job)
                except Exception:
                    # 收拾不成**不能**反过来改写任务的终态 —— 那一笔已经提交了。记下来。
                    fresh.rollback()
                    logger.warning("job %s [%s] 落终态后的收拾没做成 (%s)", job.id, job.kind, name, exc_info=True)
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
#: 这句话曾经有 4 个反例(workflow / proxy / video_to_gif / trim 各自裸起线程),现在由
#: tests/test_jobs_are_dispatched_by_the_bus.py 守着 —— 措辞守不住不变量,会红的检查才行。
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
    job_id = job.id

    def run_as_job() -> None:
        # 执行体里建出来的任务都归这个任务(ADR-0018)。新线程不继承 contextvar ——
        # 此前字幕配音逐句建的合成、导出收尾排的代理转码,全都成了顶层任务,各自弹一条"完成"。
        token = set_parent_job(job_id, strict=False)
        try:
            thread_target()
        finally:
            reset_parent_job(token)

    threading.Thread(target=run_as_job, name=JOB_THREAD_NAME, daemon=True).start()
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
    # 显式传入优先(按 strict);否则取上下文里的父任务(见 _ParentJob)。
    context = _current_parent_job.get()
    parent = parent_job_id if parent_job_id is not None else (context.job_id if context else None)
    strict = parent_job_id is not None or (context.strict if context else True)
    if parent and strict:
        parent_job = db.get(Job, parent)
        if parent_job is not None and not lock_active_job(db, parent_job):
            raise JobError("jobErr_parentFinished")
    elif parent and db.scalar(select(Job.status).where(Job.id == parent)) == "failed":
        # derived 放宽的只是「父任务**成功**收尾之后」(导出收尾时登记产物、排代理转码)。
        # 父任务被取消或失败了就不再起新活:取消级联停得住正在跑的那一个子任务,可执行体的
        # 循环会接着派下一个 —— 字幕配音逐句合成,每一句都是一次付费调用。读库里的状态,
        # 不读身份映射里那一份:取消是别的会话写进来的。
        raise JobError("jobErr_parentFinished")
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
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=created_by,
        action="job.created",
        subject_type="job",
        subject_id=job.id,
        summary="发起了任务",
        payload={"kind": kind, "status": job.status},
        source_type="job",
        source_id=job.id,
    )
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
    watching = _request_new_jobs.get()
    if watching is not None:
        watching.append(job.id)
    logger.info("job %s [%s] created (workspace=%s)", job.id, kind, workspace_id)
    return job


def current_actor(db: Session) -> str | None:
    """当前工作流 job 的操作人。

    工作流节点派生的子任务替的是**同一个人** —— 执行器签名是固定的 `(db, workflow, config)`,
    拿不到调用者,但父 job 上记着这活儿是替谁干的,而子任务与父任务的关系本来就是显式建立的
    (见 `_current_parent_job`)。
    """
    parent = current_parent_job_id()
    job = db.get(Job, parent) if parent else None
    return job.created_by if job is not None else None


@dataclass(frozen=True)
class _Resumer:
    can_resume: Callable[[Session, Job], bool]
    resume: Callable[[str], bool]


#: kind → 重启之后"接着干"的办法。总线不认识任何一类活,只认识"这一类有办法接着干"。
_RESUMERS: dict[str, _Resumer] = {}


def register_resumer(
    kind: str, *, can_resume: Callable[[Session, Job], bool], resume: Callable[[str], bool]
) -> None:
    """登记:这一类任务被重启打断时,如果 `can_resume` 说行,就 `resume(job_id)` 接着干。

    为什么要有这一条:有些活在进程外**继续发生**。生成视频提交给供应商之后,远端照样在生成、
    照样扣费 —— 把它判成"中断,请重新发起",用户照做就是再付一次,而第一次那条成片永远没人去取。
    """
    _RESUMERS[kind] = _Resumer(can_resume=can_resume, resume=resume)


def reconcile_orphaned_jobs(db: Session) -> int:
    """Settle in-process jobs left `queued`/`running` by a backend restart.

    Their daemon-thread workers cannot survive the process, so they would otherwise sit frozen at
    their last progress forever. Publish jobs are exempt (external worker). A kind that registered
    a resumer (see `register_resumer`) and says it can pick the job up is **resumed** instead of
    failed. Returns the number of jobs failed.
    """
    stale = db.scalars(
        select(Job)
        .where(Job.status.in_(("queued", "running")))
        .where(Job.kind.notin_(external_kinds()))
    ).all()
    resumable = [job for job in stale if job.kind in _RESUMERS and _RESUMERS[job.kind].can_resume(db, job)]
    failed = [job for job in stale if job not in resumable]
    for job in failed:
        job.status = "failed"
        say(job, "jobMsg_interrupted")
        #: **失败原因和任务消息同一条规矩**:落库的话存 key,出口按读的人的语言翻。
        #: 此前这一句是写死的中文,于是英文用户的任务列表里它永远是中文 —— 而
        #: `error_key` / `error_params` 这套东西早就齐了,只是总线自己没用。
        job.error_key = "jobErr_backendRestart"
        job.error = t("jobErr_backendRestart", DEFAULT_LOCALE)
        db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"reason": "backend_restart"}))
    if stale:
        db.commit()
    #: 先落库那些失败的,再接着干能接的 —— resume 自己开会话,不能夹在这个事务中间。
    for job in resumable:
        if not _RESUMERS[job.kind].resume(job.id):
            logger.warning("job %s [%s] said it could resume but did not", job.id, job.kind)
    if resumable:
        logger.info("resumed %d job(s) whose remote work outlived the restart", len(resumable))
    return len(failed) + expire_worker_leases(db)


def _cancel_job_row(db: Session, job: Job) -> bool:
    """把单个 job 落取消态 + 掐子进程 + 撤发布单(不 commit)。返回它是否原本还在跑。"""
    if job.status not in ("queued", "running") or not lock_active_job(db, job):
        return False
    job.status = "failed"
    job.error_key = "jobErr_cancelled"
    job.error = t("jobErr_cancelled", DEFAULT_LOCALE)
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


def _cancel_descendants(db: Session, job_id: str) -> set[str]:
    frontier, seen = [job_id], {job_id}
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
    return seen


def cancel_job(db: Session, job: Job) -> Job:
    """用户主动取消:job 落终态,发布任务同步撤单,工作流在节点边界停下。

    线程内正在执行的节点无法安全掐断;engine 每个节点边界都会重读 job 状态,看到已取消
    就不再继续——"停止中断"语义是节点粒度的。**级联**到工作流派生的子任务(发布/导出/转写/生成/
    配音):否则父流取消了,发布子任务还在桌面发布器里跑(见 parent_job_id 链)。
    """
    if job.status not in ("queued", "running"):
        raise JobError("jobErr_alreadyFinished")
    if not _cancel_job_row(db, job):
        db.rollback()
        raise JobError("jobErr_alreadyFinished")
    # 广度遍历后代,连嵌套子工作流一并取消。
    seen = _cancel_descendants(db, job.id)
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
WORKER_LEASE_SECONDS = 60


def claim_next_job(db: Session, *, kinds: list[str] | None = None, worker: str = "") -> Job | None:
    """认领最老的一条可认领 job 并原子翻成 running。

    只允许认领 external 模式的 kind——in_process 的 kind 已有线程在跑,被外部
    worker 抢走会双跑。CAS(status 仍是 queued 才更新)保证并发认领不重复。
    """
    expire_worker_leases(db)
    # PublishTask has its own ownership/recovery protocol.
    allowed = set(external_kinds()) - {"publish"}
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
                lease_token=secrets.token_hex(24),
                lease_worker=worker[:64],
                lease_expires_at=models_now() + timedelta(seconds=WORKER_LEASE_SECONDS),
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


def expire_worker_leases(db: Session) -> int:
    """Settle abandoned work; never automatically repeat a potentially billable side effect."""
    now = models_now()
    #: **判据只有一条:租约到点了。** 此前这里还有一条 `lease_expires_at IS NULL` 的兼容分支,
    #: 伺候"租约列还不存在时就已经 running 的行"—— 而那本该由迁移一次性了结的
    #: (`_migrate_job_worker_leases` 现在把它们直接判失败)。迁移停在最后一环之前,
    #: 剩下的半步就会变成读路径上一条永久的税:每加一个判据都要问"那条老分支下它该怎么办",
    #: 而那条分支平时没人走、坏了也没人发现。
    candidates = db.scalars(
        select(Job).where(Job.status == "running", Job.lease_expires_at <= now)
    ).all()
    expired = 0
    for job in candidates:
        if not lock_active_job(db, job):
            continue
        db.refresh(job, ["lease_expires_at", "updated_at"])
        # A heartbeat may have renewed after the candidate query but before our write lock.
        if job.lease_expires_at is None or job.lease_expires_at > now:
            continue
        if finish_job(
            db, job, status="failed",
            error=t("jobErr_leaseExpired", DEFAULT_LOCALE), error_key="jobErr_leaseExpired",
        ):
            say(job, "jobMsg_leaseExpired")
            db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"reason": "worker_lease_expired"}))
            _cancel_descendants(db, job.id)
            expired += 1
    db.commit()
    return expired


def renew_worker_leases(db: Session, *, worker: str, claims: list[dict[str, str]]) -> list[str]:
    expire_worker_leases(db)
    now = models_now()
    renewed = []
    for claim in claims:
        count = db.execute(Job.__table__.update().where(
            Job.id == claim["job_id"], Job.status == "running", Job.lease_worker == worker,
            Job.lease_token == claim["lease_token"], Job.lease_expires_at > now,
        ).values(lease_expires_at=now + timedelta(seconds=WORKER_LEASE_SECONDS))).rowcount
        if count:
            renewed.append(claim["job_id"])
    db.commit()
    return renewed


def report_job(
    db: Session,
    job: Job,
    *,
    status: str,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
    lease_token: str | None = None,
) -> Job:
    """外部 worker 回报:running 更新进度,succeeded/failed 落终态。

    与发布器同一条规则:已终态(含用户取消)的 job 不给后到的回报复活——
    worker 是在为一个已经不存在的意图干活,结果只能丢弃。
    """
    if status not in ("running", "succeeded", "failed"):
        raise JobError("jobErr_badReportStatus", status=status)
    expire_worker_leases(db)
    if not lock_active_job(db, job):
        db.commit()
        return job
    db.refresh(job, ["status", "lease_token", "lease_expires_at", "lease_worker"])
    if not job.lease_token or not secrets.compare_digest(job.lease_token, lease_token or ""):
        db.rollback()
        raise JobError("jobErr_badLease")
    if job.lease_expires_at is None or job.lease_expires_at <= models_now():
        db.rollback()
        expire_worker_leases(db)
        db.refresh(job)
        return job
    job.lease_expires_at = models_now() + timedelta(seconds=WORKER_LEASE_SECONDS)
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
        # 工作流历史靠 started/finished/failed 事件配对还原每一个节点。通用的“只留最后 5 条”
        # 会稳定地裁掉前半程，让失败运行看起来只执行了最后一个报错节点。30 天窗口已经给存储
        # 设了明确上限；窗口内保留完整工作流事件，才能让“执行历史”名副其实。
        if job.kind == "workflow":
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
