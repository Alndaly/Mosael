from __future__ import annotations

import contextvars
import functools
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, event, func, inspect, select, union_all
from sqlalchemy.orm import Session

from app.core import abort
from app.core.db import SessionLocal
from app.core.unit_of_work import after_commit, unit_of_work
from app.core.i18n import DEFAULT_LOCALE, LocalizedError, fragment, t
from app.db.models import Job, TaskEvent
from app.db.models import now as models_now
from app.domain import job_catalog

logger = logging.getLogger(__name__)

#: 被停下的任务落的状态(ADR 0049):人点了停止 / 取消,或者 Mosael 替人做的决定 —— 父任务被取消了、等它的那一轮停了。
#: 它是终态,而且**进去就出不来**(见 _terminal_is_terminal)。租约过期、重启打断、父任务失败照旧是 failed:那不是谁的决定。
CANCELLED = "cancelled"
TERMINAL_STATUSES = ("succeeded", "failed", CANCELLED)
#: 「被停下了」的那句话(「已取消」)。任务本身不再用它记取消(见 CANCELLED);还用它的:执行体发现自己没人要了时抛的
#: JobCancelled、工作流节点事件里那一步「被停下」、生成记录上抄下的「已停止」(generation.runner.record_failure)。
CANCELLED_ERROR_KEY = "jobErr_cancelled"
#: 「后端重启时它还在跑、接不回来」的记法:failed + 这个 key(见 reconcile_orphaned_jobs)。
RESTART_ERROR_KEY = "jobErr_backendRestart"


def was_cancelled(job: Any) -> bool:
    """这个任务是不是被停下的(状态是 `cancelled`,ADR 0049)。"""
    return getattr(job, "status", None) == CANCELLED

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


#: 「这一步走到哪了」的上报口。
#:
#: 一个长活(插件跑一张 ComfyUI 工作流、下一个大文件)在某个**更大的活**里面跑 —— 工作流的一个节点。
#: 做活的那一方知道进度,听的那一方(工作流引擎要把它记成那个节点的事件)不该被它认识,反过来也一样。
#: 所以在总线上留一个口:谁在跑一段活,谁就压一个听众进来(`listening_for_progress`);做活的一方只管
#: `report_progress`,没人听就什么都不发生。和 _current_parent_job 同一个做法:线程不继承上下文变量,
#: 起线程的地方自己带过去(工作流节点在线程池里带着 copy_context 跑)。
_progress_listener: contextvars.ContextVar[Callable[[float, str], None] | None] = contextvars.ContextVar(
    "mosael_progress_listener", default=None
)


def listening_for_progress(listener: Callable[[float, str], None] | None) -> contextvars.Token:
    """从现在起,`report_progress` 报给 `listener`。返回的 token 用于 stop_listening_for_progress。"""
    return _progress_listener.set(listener)


def stop_listening_for_progress(token: contextvars.Token) -> None:
    _progress_listener.reset(token)


def report_progress(fraction: float, message: str) -> None:
    """报一次进度(0..1 加一句话)。**听的那一方出错不外抛** —— 进度是锦上添花,不该让活本身失败。"""
    listener = _progress_listener.get()
    if listener is None:
        return
    try:
        listener(max(0.0, min(1.0, float(fraction))), str(message or "")[:200])
    except Exception:  # noqa: BLE001 — 见上
        logger.exception("进度上报失败")


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

# Children (ffmpeg, ASR/TTS workers, plugin tools) belonging to a running job, so cancelling can
# actually stop the work. Without this, cancel only flipped a database row: ffmpeg ran to completion,
# burning CPU the user had asked to stop, and then the worker overwrote the cancellation with
# "succeeded" — the cancelled export reappeared in the library as if nothing had happened.
#
# A job can own several at once: a workflow runs plugin nodes in parallel, and every one of their
# processes belongs to the workflow job (see plugins/runtime.execute_tool).
_CHILDREN: dict[str, list[Any]] = {}
_CHILDREN_LOCK = threading.Lock()
#: 取消已经掐过、而执行体还在跑的任务。取消在**提交之前**就掐子进程(_cancel_job_row),执行体却可能恰好在那一刻起一个
#: 新的子进程:它登记时去库里查,取消还没提交,查到的仍是 running —— 于是这个新来的没人掐,插件照跑到底(取消落在插件
#: 刚要起进程的那一下就是这样)。记在内存里,登记时先看这里;执行体结束时(run_as_job)忘掉。
_KILLED: set[str] = set()


def register_job_child(job_id: str, child: Any) -> None:
    """Associate a killable child (anything with .kill()) with a job for its lifetime."""
    with _CHILDREN_LOCK:
        _CHILDREN.setdefault(job_id, []).append(child)
        already_killed = job_id in _KILLED
    if already_killed:
        child.kill()
        return
    # Cancellation may have committed before the subprocess existed.
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            child.kill()


def detach_job_child(job_id: str, child: Any) -> None:
    """This one child is done; the job's other children stay registered."""
    with _CHILDREN_LOCK:
        children = _CHILDREN.get(job_id)
        if children is None:
            return
        _CHILDREN[job_id] = [each for each in children if each is not child]
        if not _CHILDREN[job_id]:
            del _CHILDREN[job_id]


def unregister_job_child(job_id: str) -> None:
    """The job's run is over: forget every child it registered."""
    with _CHILDREN_LOCK:
        _CHILDREN.pop(job_id, None)


def kill_job_child(job_id: str) -> bool:
    """Stop the children of a running job, if any are registered. True if something was killed.

    执行体还在跑的(登记过东西的)记进 _KILLED:之后才登记的子进程当场掐掉,不等取消提交。"""
    with _CHILDREN_LOCK:
        children = list(_CHILDREN.get(job_id, ()))
        if children:
            _KILLED.add(job_id)
    for child in children:
        child.kill()
    return bool(children)


def forget_job_kill(job_id: str) -> None:
    """这个任务的执行体结束了:不再需要记着它被取消过(见 _KILLED)。"""
    with _CHILDREN_LOCK:
        _KILLED.discard(job_id)


# Admission control for work that is heavy in CPU, GPU or memory. There was none: ten
# simultaneous exports meant ten x264 encoders plus up to eighty concurrent ffprobes, and ten
# transcribes meant ten torch interpreters — near-certain OOM on a laptop. Acquire a slot
# BEFORE opening a database session, never while holding one; see _run_proxy for what the other
# order costs. A sleeping thread is cheap, a pinned connection is not.
RENDER_SLOTS = threading.Semaphore(2)
ASR_SLOTS = threading.Semaphore(1)      # torch/funasr: one model in memory at a time
TTS_SLOTS = threading.Semaphore(1)
#: 同时在跑的插件工具调用。每一次都是一个新进程(进程插件起一个解释器,MCP·stdio 起一个 server),
#: 大多在等第三方接口 —— 但工作流里一个循环 × 并行分支就能同时拉起几十个。见 plugins/tools.invoke。
PLUGIN_SLOTS = threading.Semaphore(4)


class JobCancelled(LocalizedError, RuntimeError):
    """这件活已经没人要了(被取消了,或者它所在的那个任务失败了)。执行体在登记产出、改时间线、写逐字稿……
    这些**副作用之前**经 `ensure_wanted` 抛它;派发处的兜底(run_job_guarded)认得它,不把它说成「出错」。"""


def ensure_wanted() -> None:
    """登记产出 / 改别人的东西之前问一句:这件活还有人要吗。不要了抛 `JobCancelled`。

    问的是**上下文里正在跑的那个任务**(dispatch_job 给每个执行体设好了;工作流的节点认的是工作流那个任务)——
    所以分离、降噪这类既被自己的任务调、也被工作流节点调的函数,在自己体内问一句就两边都管到。不在任何任务里
    (请求线程、脚本)就什么都不查。

    两个来源,先看快的:取消在**提交之前**就拉下了这件活的开关(见 _cancel_job_row → kill_job_child);
    开关没拉下的,再读库里的那一份(取消是别的会话写进来的,不读身份映射里的)。
    """
    scope = abort.current()
    if scope is not None and scope.aborted:
        raise JobCancelled(CANCELLED_ERROR_KEY)
    job_id = current_parent_job_id()
    if job_id is None:
        return
    with SessionLocal() as db:
        status = db.scalar(select(Job.status).where(Job.id == job_id))
    #: 只认被停下、或它所在的任务失败了。succeeded 的父任务照样能派生收尾的活(见 _ParentJob 的 derived)。
    if status in ("failed", CANCELLED):
        raise JobCancelled(CANCELLED_ERROR_KEY)


def run_job_guarded(job_id: str, body: Callable[[], None], *, what: object = "job") -> None:
    """Run a worker body so that no failure can leave the job silently queued.

    Every worker began with `db.get(Job, job_id)` OUTSIDE its try. That is the call that checks
    a connection out of the pool, so when the pool was exhausted it raised, the daemon thread
    died, and the row stayed `queued` with no error — forever, since reconcile only runs at
    startup. A backfill of 60 videos produced 45 such jobs.

    Anything the body does not handle is recorded on the job here instead. **dispatch_job 替每个派发出去的
    执行体套上它** —— 此前要每个执行体自己记得套,七个没套。`what` 是这类活叫什么(一个文案片段,读的时候按
    读的人的语言翻;直接调它的地方也可以给一句话)。
    """
    try:
        body()
    except JobCancelled:
        # 执行体自己发现没人要了(ensure_wanted):正常情况下取消那一侧已经落了终态,这里什么都不改;
        # 取消没能提交的那种(开关拉下了、事务回滚了)由这里收成「已取消」,不让它停在 running。
        logger.info("job %s stopped: no longer wanted", job_id)
        _record_crash(job_id, what, cancelled=True)
    except Exception as exc:  # noqa: BLE001 — a worker thread must never die silently
        logger.exception("%s worker crashed (job=%s)", what, job_id)
        _record_crash(job_id, what, exc=exc)


def _record_crash(job_id: str, what: object, *, exc: Exception | None = None, cancelled: bool = False) -> None:
    try:
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if cancelled:
                if finish_job(db, job, status=CANCELLED, error=None, error_key="", error_params={}):
                    say(job, "jobMsg_cancelled")
                    db.add(TaskEvent(job_id=job.id, type="job.cancelled",
                                     payload={"by": None, "cascaded_from": None, "stage": "worker"}))
                return
            if finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_genericFailed", what=what)
                db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"stage": "worker"}))
                #: 异常带着现场(「这一版要主人认可」的 attest,见 domain/authority):留在任务上,等它的工作流 / 定时任务
                #: 从这里抄过去给「认可这一版」(executors.common.wait_for_job、scheduler.sync_run_states)。
                #: 一个工作流里的生成任务撞上这道闸,就是从这里走的 —— 它在自己的线程里解析连接。
                failure = failure_payload(exc) if exc is not None else {}
                if failure.get("details"):
                    job.result = {**(job.result or {}), "failure": failure}
    except Exception:  # noqa: BLE001 — the DB is what failed; nothing left to try
        logger.exception("could not record the failure of %s %s", what, job_id)


def run_job_inline(
    db: Session,
    job: Job,
    body: Callable[[], dict[str, Any]],
    *,
    running: str,
    done: str,
    params: dict[str, object] | None = None,
) -> bool:
    """在调用方自己的线程里把一个任务跑完 —— 给「几秒就回、调用方等着要结果」的活儿(画板上写字)。

    收尾和派发出去的任务是同一套:起步、成功、**任何一种异常**都经 finish_job 落终态,回执随
    状态跳变送出(见 _after_jobs_settled)。执行体抛出的异常在任务落成失败**之后**原样抛回,
    调用方照旧按类型翻成 HTTP —— 没有哪条异常路径能把任务(和挂着它的那一格)留在「运行中」。
    进程在中途没了的,重启时 reconcile_orphaned_jobs 同样收掉它。

    `body` 回任务的 result。返回 True 表示成功落了终态;False 表示跑之前或跑的时候被取消了
    (这时结果作废,终态由取消那一侧写)。`params` 填进 `running` / `done` 那两句(「正在跑「{name}」」)——
    每句话都是整句重写,不带参数的话名字就成了空的「」。
    """
    if not finish_job(db, job, status="running"):
        db.commit()
        return False
    say(job, running, **(params or {}))
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
    say(job, done, **(params or {}))
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
    from app.core.i18n import DEFAULT_LOCALE, is_message_key, render_message, stored_param

    #: 有几处传进来的是一句现成的话(子任务转述的消息、第三方的原话)。它不是 key,不该当 key
    #: 落库 —— 否则读的时候会被当模板再填一遍(见 core/i18n.is_message_key)。
    job.message_key = key if is_message_key(key) else ""
    #: 参数里的文案片段(`fragment`,比如任务种类的名字)原样留着,读的时候按读的人的语言翻;其余写成字。
    job.message_params = {k: stored_param(v) if isinstance(v, dict) else str(v) for k, v in params.items()}
    job.message = render_message(key, DEFAULT_LOCALE, job.message_params)


def blame(exc: Exception) -> dict[str, Any]:
    """一个异常 → 写进任务失败原因的那三样(`error` / `error_key` / `error_params`)。

    和 `say` 同构,只是另一半:**落库的那句话不该冻住语言**。领域异常带 key 的(见
    workflows.WorkflowDomainError)就把 key 和参数一起记上,接口按读的人的语言翻;
    不带 key 的(第三方库、别的领域)只留那句话 —— 那是它自己的文本,我们翻不了。

    传给 `finish_job(**blame(exc))` 用,所以返回的是字段名对得上的一份字典。

    **那句话不按位置截**:`error` 是 Text 列,长短是界面排版的事。此前的 `[:500]` 把长一点的
    原因切成半句话 —— 切掉的恰好是后半截,而原因往往就写在后半截。
    """
    from app.core.i18n import is_message_key, stored_param

    key = str(getattr(exc, "key", "") or "")
    if not is_message_key(key):
        #: 参数只跟着 key 才有意义。别处的异常也可能有个叫 `params` 的属性 —— SQLAlchemy 的
        #: 数据库错误把那条 SQL 的参数元组挂在上面,此前拿它当文案参数,失败现场自己先崩了。
        return {"error": str(exc), "error_key": "", "error_params": {}}
    params = getattr(exc, "params", None)
    return {
        "error": str(exc),
        #: 不截断:截断的 key 就不是 key 了。此前的 `[:80]` 正是一句 403 报错被切成"半截 key"的地方。
        "error_key": key,
        #: 参数里的文案片段(字段名之类,见 core/i18n.fragment)原样留着,读的时候一起翻。
        "error_params": {k: stored_param(v) for k, v in (params or {}).items()},
    }


def failure_payload(exc: Exception) -> dict[str, Any]:
    """把异常变成任务总线可持久化的失败现场(`job.result["failure"]`)。

    **和任务上的失败原因同一个形状**(见 blame):那句话本身、它的文案 key 和参数 —— 和节点事件的 `name` / `name_key`
    同构,出口可以按读的人的语言重翻。异常带着的 `details`(「这一版要主人认可」的 attest,见 domain/authority)
    跟着走:运行历史、定时任务的运行记录据此给「认可这一版」。
    """
    payload: dict[str, Any] = {key: value for key, value in blame(exc).items() if value}
    details = getattr(exc, "details", None)
    if isinstance(details, dict) and details:
        payload["details"] = details
    return payload


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


def start_job(db: Session, job: Job, **fields: Any) -> bool:
    """排队 → 在跑。**执行体起步只经这里。** 返回 False = 它在排队时已经落了终态(被取消了),执行体照此直接退出,
    什么都不做。

    此前几个执行体一上来直接 `job.status = "running"`:排队时(派发器名额满、等转码名额、等本机合成名额)被取消的
    任务,轮到它时被写回 running、照跑到底、最后记成成功 —— 付费的配音照样调用,落终态的收拾和回执各跑两遍。
    """
    return finish_job(db, job, status="running", **fields)


class JobStateError(RuntimeError):
    """有人想把一个已经落了终态的任务写回「进行中」。是代码错,不是用户能处理的情况 —— 见 _terminal_is_terminal。"""


@event.listens_for(Job.status, "set", active_history=True)
def _terminal_is_terminal(job: Job, value: Any, previous: Any, _initiator: Any) -> None:
    """**终态不回头。** 一个任务成功、失败、被取消之后,不许再被写回排队 / 在跑。

    守在 ORM 的属性上,不在某个函数里:状态的写法此前有好几种(finish_job、直接赋值、执行体自己的收尾),
    漏走 finish_job 的那一处在这里当场炸,而不是悄悄把一次取消改写掉(见 start_job)。终态之间的改写
    (发布器在超时判失败之后又回报了成功)不归这里管,那是 finish_job 的调用方自己的判断。
    """
    if previous in TERMINAL_STATUSES and value not in TERMINAL_STATUSES:
        raise JobStateError(f"job {job.id} is already {previous}; it cannot go back to {value}")
    #: **被停下的改不成别的终态**(ADR 0049 决定 2):停下是人的决定,迟到的「成功」也推翻不了它 —— 取消会停下进程、丢掉
    #: 产出,一个迟到的成功说明那一下没停住,要查的是为什么没停住,而不是把一个已经丢掉的结果记成成功。
    #: 失败 → 成功照旧可以(发布器被回收成失败之后又回报了成功)。
    if previous == CANCELLED and value != CANCELLED:
        raise JobStateError(f"job {job.id} was cancelled; it cannot become {value}")


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


@event.listens_for(Session, "after_flush")
def _note_settled_jobs(session: Session, _flush_context: Any) -> None:
    """记下这次 flush 里**刚进终态**的任务,登记成「提交之后再收拾、再送回执」。

    **挂在状态变化上,不挂在某个函数上。** 回执最初挂在 finish_job 里,而全仓库只有
    render.py 走它 —— 生成、发布、配音、代理、从链接导入全是直接 `job.status = ...`。
    于是回执挂在了一条几乎没人走的路上:智能体提交完生成、任务失败了,它一无所知。

    只认「**从非终态进终态**」这一次跳变:一个已经 failed 的行再被写一次别的字段,
    不该再发一封。

    **登记走 unit_of_work.after_commit,不自己记一份清单。** 此前这里往 session.info 里记 id、提交时取走,而回滚
    不清它:确认卡的执行体把一个任务写成终态、随后炸了,approve_confirmation 回滚掉执行体的改动(那个终态也一起
    没了),紧接着记「卡失败」的那次提交却把这份陈旧的清单取走 —— 对一个根本没落终态的任务跑收拾、送「已结束」
    的回执。after_commit 的钩子回滚就丢、保存点回滚只丢它里面登记的,正是这里要的语义。
    """
    settled = []
    for obj in session.dirty:
        if not isinstance(obj, Job):
            continue
        history = inspect(obj).attrs.status.history
        if not history.has_changes():
            continue
        was = history.deleted[0] if history.deleted else None
        if obj.status in TERMINAL_STATUSES and was not in TERMINAL_STATUSES:
            settled.append(obj.id)
    if settled:
        after_commit(session, lambda: _after_jobs_settled(settled))


def _after_jobs_settled(job_ids: list[str]) -> None:
    """提交之后才收拾、才送。

    送信会写库(往对话里放一条消息)、还会叫醒一个智能体回合 —— 在 flush 里做的话,
    它看到的是一份还没提交的任务状态,而万一外层回滚,消息已经发出去了。收拾同理。
    """
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
                    # 这里是收拾动作的入口:每一个收拾动作单独提交,前一个不被后一个的失败带走。
                    fresh.commit()
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

#: 同时**在干活**的进程内任务上限。此前每派发一个任务就起一个线程,不设上限:一次批量补字幕、一个
#: 工作流循环 × 并行分支,就是几百个线程同时在跑(或在各自的资源名额上睡着)。
MAX_ACTIVE_JOBS = 16


class JobRunner:
    """有上限的任务派发:名额满了就排队,有任务结束再放下一个进来。

    **不能是一个普通的定长线程池。** 工作流这类任务会等自己的子任务(workflows.executors.common.wait_until):
    池子被一群「等子任务」的父任务占满时,子任务永远排不上 —— 死锁。所以等的时候**把名额让出来**
    (`parked`),等完再拿回去(可以暂时超额:回来的父任务不该排在自己的子任务后面)。
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._active = 0
        self._queue: deque[tuple[str, Callable[[], None]]] = deque()
        self._running: set[str] = set()
        self._parked: dict[str, int] = {}

    def submit(self, job_id: str, body: Callable[[], None]) -> None:
        with self._lock:
            self._queue.append((job_id, body))
            admitted = self._admit_locked()
        self._start(admitted)

    def _admit_locked(self) -> list[tuple[str, Callable[[], None]]]:
        admitted = []
        while self._queue and self._active < self.limit:
            job_id, body = self._queue.popleft()
            self._active += 1
            self._running.add(job_id)
            admitted.append((job_id, body))
        return admitted

    def _start(self, admitted: list[tuple[str, Callable[[], None]]]) -> None:
        for job_id, body in admitted:
            # 目标是无参的:测试里有把 Thread 替成「同步调 target()」的替身,不传 args。
            threading.Thread(target=functools.partial(self._run, job_id, body), name=JOB_THREAD_NAME, daemon=True).start()

    def _run(self, job_id: str, body: Callable[[], None]) -> None:
        try:
            body()
        finally:
            with self._lock:
                self._running.discard(job_id)
                self._active -= 1
                admitted = self._admit_locked()
            self._start(admitted)

    @contextmanager
    def parked(self, job_id: str | None):
        """这个任务在等别的任务:等待期间不占名额。同一个任务的几条线程(并行节点)同时在等只让一次。"""
        with self._lock:
            holds = job_id is not None and job_id in self._running
            if holds:
                waiting = self._parked.get(job_id, 0)
                self._parked[job_id] = waiting + 1
                if waiting == 0:
                    self._active -= 1
            admitted = self._admit_locked() if holds else []
        self._start(admitted)
        try:
            yield
        finally:
            if holds:
                with self._lock:
                    self._parked[job_id] -= 1
                    if self._parked[job_id] == 0:
                        del self._parked[job_id]
                        self._active += 1

    def idle(self) -> bool:
        with self._lock:
            return not self._running and not self._queue


_runner = JobRunner(MAX_ACTIVE_JOBS)


def reset_runner() -> None:
    """换一个空的派发器。**给测试框架用**,和 wait_for_idle_jobs 同一个性质:替身线程不会执行
    任务体,它占的名额永远不还,不换的话会串到后面的测试里。生产里没有理由调它。"""
    global _runner
    _runner = JobRunner(MAX_ACTIVE_JOBS)


def waiting_on_other_jobs():
    """当前任务(按 contextvar 认)在等别的任务 —— 见 JobRunner.parked。"""
    return _runner.parked(current_parent_job_id())


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
        if not alive and _runner.idle():
            return True
        if alive:
            alive[0].join(timeout=max(0.0, min(0.5, deadline - time.monotonic())))
        else:
            time.sleep(0.01)  # 排着队、线程还没起来的那一小段
    return _runner.idle() and not any(t.name == JOB_THREAD_NAME and t.is_alive() for t in threading.enumerate())


def dispatch_job(db: Session, job: Job, thread_target: Callable[[], None]) -> bool:
    """按 kind 的执行模式派发一个刚创建的 job。

    in_process → 这次事务**提交之后**起线程;external → 什么都不做,留在 queued 等外部 worker 认领。
    领域模块只描述「怎么跑」(thread_target),「由谁跑」是总线的决定——这样把一个 kind 挪到外部
    worker 不需要改领域代码。Returns True when the job will run in-process.

    **这里不提交,起线程登记成 after_commit。** 此前这里先 `db.commit()` 再起线程:调用方事务里**在它之前**
    做的一切跟着落了库,任务线程也已经跑起来了 —— 而调用方可能还没做完。确认卡的执行体是一个用例一个
    事务、炸了整个回滚(见 agent.confirmations.approve_confirmation),对「起任务」的卡这句话就不成立:
    派发处已经替它提交了一半。提交归入口(core/unit_of_work 的约定);入口提交了,线程才起来(它要读刚写的
    行);入口回滚了,任务连同它的线程都不存在。调用方要保证这次事务之后会提交 —— 等子任务的节点在
    wait_for_job(release=db) 里交还会话时提交。

    **thread_target 只捏普通值。** 线程起来时调用方的会话还在用(可能回滚过、正在下一次提交),在线程里读
    `job.id` / `asset.id` 会拿那个会话回库加载。要用的 id 在派发前取成局部变量 ——
    tests/test_jobs_are_dispatched_by_the_bus.py 守着。
    """
    if execution_mode(job.kind) == "external":
        say(job, "jobMsg_waitingWorker")
        db.add(TaskEvent(job_id=job.id, type="job.awaiting_worker", payload={}))
        logger.info("job %s [%s] queued for external worker", job.id, job.kind)
        return False
    job_id = job.id
    kind = job.kind

    #: 兜底记失败时这类活叫什么:任务种类的名字(文案片段,读的时候按读的人的语言翻)。
    entry = job_catalog.JOB_KINDS.get(kind)
    what = fragment(entry.label_key if entry is not None else job_catalog.FALLBACK_LABEL_KEY)

    def run_as_job() -> None:
        # 执行体里建出来的任务都归这个任务(ADR-0018)。新线程不继承 contextvar ——
        # 此前字幕配音逐句建的合成、导出收尾排的代理转码,全都成了顶层任务,各自弹一条"完成"。
        token = set_parent_job(job_id, strict=False)
        # 取消要掐得掉**正在进行**的出站请求(大模型、配音、翻译……)和一次性子进程,不只是改一行状态(见 core/abort)。
        # 开关登记成这个任务的「子进程」:取消(连同级联到它的)经 kill_job_child 调到它的 kill()。
        stop = abort.AbortScope()

        def body() -> None:
            # 登记要碰库(看取消是不是已经提交了),所以也在兜底里面:连接池满了的那一下不能让线程无声地死掉。
            register_job_child(job_id, stop)
            thread_target()

        try:
            with abort.scope(stop):
                # **兜底在这里套一次,对每个派发出去的执行体都成立**:执行体在它自己的 try 之前抛出的任何东西
                # (连接池等满、库被锁、解密失败……)都落成这个任务的失败,不再停在 queued / running 等下次重启。
                run_job_guarded(job_id, body, what=what)
        finally:
            detach_job_child(job_id, stop)
            forget_job_kill(job_id)
            reset_parent_job(token)

    def submit() -> None:
        _runner.submit(job_id, run_as_job)
        logger.info("job %s [%s] dispatched in-process", job_id, kind)

    after_commit(db, submit)
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
    elif parent and db.scalar(select(Job.status).where(Job.id == parent)) in ("failed", CANCELLED):
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
        job.error_key = RESTART_ERROR_KEY
        job.error = t(RESTART_ERROR_KEY, DEFAULT_LOCALE)
        db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"reason": "backend_restart"}))
    #: **不在这里提交。** 重启收尾是一次用例(domain/restart.settle_previous_run):几张表一起收完、一起提交,提交钩子
    #: (落终态之后的收拾、送回执 —— 回执会在对话里起一轮)在**全部**收完之后才跑。此前这里自己提交,钩子当场就跑:
    #: 回执在空闲的对话里起了一轮,紧接着「把卡住的会话拨回 idle」把这一轮当成重启前的孤儿拨回去、还补了一句「已中断」。
    #: 接着干的那几个同理,提交之后才开始(resume 自己开会话、起线程,不能夹在这个事务中间)。
    if resumable:
        resumes = [(job.kind, job.id) for job in resumable]
        after_commit(db, lambda: _resume(resumes))
    return len(failed) + _expire_worker_leases(db)


def _resume(resumes: list[tuple[str, str]]) -> None:
    for kind, job_id in resumes:
        if not _RESUMERS[kind].resume(job_id):
            logger.warning("job %s [%s] said it could resume but did not", job_id, kind)
    logger.info("resumed %d job(s) whose remote work outlived the restart", len(resumes))


#: 「这种任务被取消时,外面还有一张单要跟着撤」(任务种类 → 撤单的那一步)。和取消在**同一个事务**里做:任务落了取消,
#: 那张单也就撤了,没有中间态。任务这一层不认识持有那张单的领域(发布任务交给桌面发布器去点,见 publish.worker),
#: 是那一域在装配时登记进来(app/main._wire_seams)—— 和回执、落终态的收拾同一个方向。
_CANCEL_LISTENERS: dict[str, Callable[[Session, Job], None]] = {}


def register_cancel_listener(kind: str, listener: Callable[[Session, Job], None]) -> None:
    """登记 `kind` 这种任务被取消时要跟着撤的东西。不提交,跟着取消的那个事务走。同一种后登记的覆盖先登记的。"""
    _CANCEL_LISTENERS[kind] = listener


def _cancel_job_row(db: Session, job: Job, *, by: str | None, cascaded_from: str | None) -> bool:
    """把单个 job 落取消态 + 掐子进程 + 撤登记过的外部单(不 commit)。返回它是否原本还在跑。

    取消不是一个错误,没有原因可说:`error` / `error_key` 清空。谁取消的(`by`,用户 id;Mosael 自己停下的是 None)、
    是不是从别的任务级联下来的(`cascaded_from`)记在那一条 `job.cancelled` 事件里(ADR 0049 决定 3)。"""
    if job.status not in ("queued", "running") or not lock_active_job(db, job):
        return False
    job.status = CANCELLED
    job.error, job.error_key, job.error_params = None, "", {}
    say(job, "jobMsg_cancelled")
    db.add(TaskEvent(job_id=job.id, type="job.cancelled", payload={"by": by, "cascaded_from": cascaded_from}))
    # Stop the actual work, not just the row describing it.
    if kill_job_child(job.id):
        db.add(TaskEvent(job_id=job.id, type="job.child_killed", payload={}))
    withdraw = _CANCEL_LISTENERS.get(job.kind)
    if withdraw is not None:
        withdraw(db, job)
    return True


def _cancel_descendants(db: Session, job_id: str, *, by: str | None) -> set[str]:
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
            #: 级联下来的也是被停下的(ADR 0049 决定 4),不是失败。
            _cancel_job_row(db, child, by=by, cascaded_from=parent_id)
            frontier.append(child.id)
    return seen


def cancel_job_tree(db: Session, job: Job, *, by: str | None = None, cascaded_from: str | None = None) -> set[str] | None:
    """取消这个任务,并广度遍历取消它的后代(连嵌套子工作流)。不 commit。

    返回取消到的 id(含自己);它已经落了终态就返回 None、什么都不动。用户点取消(cancel_job)
    和「等它的人不再要它了」(工作流这一轮正在停,见 workflows.executors.common.wait_until)
    走的是同一条路 —— 取消只有一种做法。`by`:谁取消的(用户 id);`cascaded_from`:是哪个任务停下连带它停的。
    """
    if not _cancel_job_row(db, job, by=by, cascaded_from=cascaded_from):
        return None
    return _cancel_descendants(db, job.id, by=by)


def cancel_job(db: Session, job: Job, *, by: str | None) -> Job:
    """用户主动取消:job 落终态,发布任务同步撤单,工作流在节点边界停下。

    线程内正在执行的节点无法安全掐断;engine 每个节点边界都会重读 job 状态,看到已取消
    就不再继续——"停止中断"语义是节点粒度的。**级联**到工作流派生的子任务(发布/导出/转写/生成/
    配音):否则父流取消了,发布子任务还在桌面发布器里跑(见 parent_job_id 链)。
    """
    if job.status not in ("queued", "running"):
        raise JobError("jobErr_alreadyFinished")
    seen = cancel_job_tree(db, job, by=by)
    if seen is None:
        db.rollback()
        raise JobError("jobErr_alreadyFinished")
    # 不提交:入口(任务中心的取消、webhook 的取消)提交。子进程已经在上面掐掉了。
    db.flush()
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
    """Settle abandoned work; never automatically repeat a potentially billable side effect. Commits."""
    expired = _expire_worker_leases(db)
    db.commit()
    return expired


def _expire_worker_leases(db: Session) -> int:
    """同上,不提交(重启收尾把它和别的几张表一起提交)。"""
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
            _cancel_descendants(db, job.id, by=None)
            expired += 1
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
            if error or message:
                #: 执行器自己说的原因是它的原话(另一个进程、另一种语言),原样留着,不截半句(同 blame)。
                job.error, job.error_key, job.error_params = error or message, "", {}
            else:
                job.error_key, job.error_params = "jobErr_workerReportedFailure", {}
                job.error = t("jobErr_workerReportedFailure", DEFAULT_LOCALE)
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


#: 一批最多删这么多条任务事件。删的时候攥着写锁:一批要短,别的写入(请求、任务进度)才等得过 busy_timeout。
PRUNE_BATCH = 2000


def prunable_task_events(db: Session, *, now: datetime | None = None) -> list[str]:
    """按保留规则该删的任务事件 id。**只读** —— 不占写锁;删由 `delete_task_events` 分批做(见 workers/scheduler.prune_events)。

    规则:进行中的任务全留;已结束的留最近 TERMINAL_KEEP_EVENTS 条(工作流在窗口内全留);结束超过 EVENT_RETENTION_DAYS
    天的事件全删,任务那一行留着。

    **判据是一条集合式查询,不把任务读成 ORM 对象。** 此前逐个任务查、逐个删,而 ORM 的 DELETE 每一次都把身份映射里
    的全部对象过一遍(默认的 synchronize_session):一年的量(三万多个任务)清一次 67 秒,全程攥着写锁 ——
    期间别的写入 5 秒后报 database is locked。
    """
    reference = now or models_now()  # utcnow() is deprecated; models_now is the same naive UTC
    cutoff = reference - timedelta(days=EVENT_RETENTION_DAYS)
    finished = Job.status.in_(TERMINAL_STATUSES)
    expired = (
        select(TaskEvent.id.label("id"))
        .join(Job, Job.id == TaskEvent.job_id)
        .where(finished, Job.updated_at < cutoff)
    )
    # 工作流历史靠 started/finished/failed 事件配对还原每一个节点。通用的“只留最后 5 条”
    # 会稳定地裁掉前半程，让失败运行看起来只执行了最后一个报错节点。30 天窗口已经给存储
    # 设了明确上限；窗口内保留完整工作流事件，才能让“执行历史”名副其实。
    ranked = (
        select(
            TaskEvent.id.label("id"),
            func.row_number()
            .over(partition_by=TaskEvent.job_id, order_by=(TaskEvent.created_at.desc(), TaskEvent.id.desc()))
            .label("newest_first"),
        )
        .join(Job, Job.id == TaskEvent.job_id)
        .where(finished, Job.updated_at >= cutoff, Job.kind != "workflow")
        .subquery()
    )
    trimmed = select(ranked.c.id).where(ranked.c.newest_first > TERMINAL_KEEP_EVENTS)
    return list(db.scalars(union_all(expired, trimmed)))


def delete_task_events(db: Session, ids: list[str]) -> int:
    """按 id 删一批任务事件(不提交)。返回删了几条。"""
    if not ids:
        return 0
    db.execute(delete(TaskEvent).where(TaskEvent.id.in_(ids)).execution_options(synchronize_session=False))
    return len(ids)


def prune_task_events(db: Session, *, now: datetime | None = None) -> int:
    """一次删完(一个事务)。给测试和小库用;调度线程走分批的 `workers/scheduler.prune_events`。"""
    ids = prunable_task_events(db, now=now)
    return sum(delete_task_events(db, ids[start:start + PRUNE_BATCH]) for start in range(0, len(ids), PRUNE_BATCH))


@dataclass(frozen=True)
class FinishedJobRow:
    """建「清空已结束」那份计划时读的几列 —— 不把任务读成 ORM 对象(见 `plan_clear_finished`)。"""

    id: str
    parent_job_id: str | None
    status: str
    created_by: str | None


@dataclass(frozen=True)
class FinishedJobsPlan:
    """「清空已结束」这一下会删什么、留什么(删之前先给人看,见 `plan_clear_finished`)。"""

    #: 要删的树:每棵是一个已结束的顶层任务连同它收纳的子任务;一棵树的行挨在一起,删由 `delete_jobs` 分批做。
    trees: list[list[FinishedJobRow]]
    #: 已结束、他也动得了,却**留下**的树 —— 它们是别处的记录(见 `_kept_job_ids`)。
    kept: int

    def ids(self) -> list[str]:
        return [node.id for nodes in self.trees for node in nodes]


def _kept_job_ids(db: Session, workspace_id: str) -> set[str]:
    """已结束了也不归「清空已结束」删的任务:它们是别处的记录,不只是任务中心面板上的一行。

    - 工作流运行(`kind == "workflow"`):工作流页的「执行历史」就是这些行;
    - 留着运行产出全文的任务(`workflow_run_outputs`,别种任务跑图时也会留,见 workflows/authority):
      产出跟着任务级联,删了任务,能复制 / 下载的模型回复一起没了;
    - 记过用量的任务:「谁在花钱」顺着用量事件的 `job_id` 找到是谁花的(见 dashboard),删了任务
      这笔钱就再也归不到人头上。

    这是止血:「清空」到底该是物理删除还是「从我的面板拿掉」、用量事件要不要自己记下是谁花的,还待 ADR 定。
    """
    from app.db.models import ProviderUsageEvent, WorkflowRunOutput

    in_workspace = select(Job.id).where(Job.workspace_id == workspace_id)
    kept = set(db.scalars(in_workspace.where(Job.kind == "workflow")))
    kept |= set(db.scalars(
        select(WorkflowRunOutput.job_id).where(WorkflowRunOutput.job_id.in_(in_workspace)).distinct()
    ))
    kept |= set(db.scalars(
        select(ProviderUsageEvent.job_id)
        .where(ProviderUsageEvent.job_id.is_not(None), ProviderUsageEvent.job_id.in_(in_workspace))
        .distinct()
    ))
    return kept


def plan_clear_finished(db: Session, workspace_id: str, *, removable: Any = None) -> FinishedJobsPlan:
    """任务中心的「清空已结束」会删掉哪些:面板上列着的那些已结束任务,**连同它们收纳的子任务**。只读。

    面板只列顶层任务(子任务收在父任务的详情里,见 routes/jobs 的 `top_level`),所以清的单位是**一棵树**:
    顶层任务结束了、而且它底下每一个子任务也都结束了,整棵一起删。此前是「这个工作区里所有已结束的行」,
    于是一个**还在跑**的工作流底下已经做完的子任务也被删掉 —— 面板上根本没列它们,父任务的详情里它们却
    凭空少了几步;而配音这类父任务要回头读子任务的失败原因(voices.subtitle_dub),读到的是一个已经不存在的行。
    反过来,顶层任务结束了、它派生的子任务还在跑(渲染登记产出时顺手排的代理),整棵留着 —— 删了父任务,
    还在跑的那个就成了面板上永远看不见的孤儿。

    父任务早就不在了的行(旧版本的清空留下的孤儿)当作顶层:面板看不见它们,它们也不再属于任何还在的东西。

    `removable`:清的人能动哪些行(`jobs` 表上的 SQL 条件,见 generation/sessions.jobs_writable_filter)。
    一棵树里只要有一行他动不了(别人私有会话里的生成),整棵留着 —— 和取消任务同一道闸。

    树里只要有一行是别处的记录(工作流运行、记过用量的,见 `_kept_job_ids`),整棵也留着,数进 `kept`。
    预览(job_center.preview_clear_finished)和真删(job_center.clear_finished)读的是同一份计划。
    """
    #: 只读建树要的几列,不把任务读成 ORM 对象:一个用了几个月的工作区有上万个任务,整行(连 payload、result)读进来
    #: 再逐个 `db.delete`,ORM 每删一个都把身份映射过一遍 —— 1.2 万个任务点一次要 41 秒,全程攥着写锁。
    rows = [
        FinishedJobRow(row.id, row.parent_job_id, row.status, row.created_by)
        for row in db.execute(
            select(Job.id, Job.parent_job_id, Job.status, Job.created_by).where(Job.workspace_id == workspace_id)
        ).all()
    ]
    allowed = (
        None if removable is None
        else set(db.scalars(select(Job.id).where(Job.workspace_id == workspace_id, removable)))
    )
    kept_ids = _kept_job_ids(db, workspace_id)
    present = {row.id for row in rows}
    children: dict[str, list[FinishedJobRow]] = {}
    for row in rows:
        if row.parent_job_id:
            children.setdefault(row.parent_job_id, []).append(row)

    def tree(root: FinishedJobRow) -> list[FinishedJobRow]:
        nodes, frontier = [root], [root]
        while frontier:
            kids = children.get(frontier.pop().id, [])
            nodes.extend(kids)
            frontier.extend(kids)
        return nodes

    trees: list[list[FinishedJobRow]] = []
    kept = 0
    for root in rows:
        if root.parent_job_id in present:
            continue
        nodes = tree(root)
        if any(node.status not in TERMINAL_STATUSES for node in nodes):
            continue
        if allowed is not None and any(node.id not in allowed for node in nodes):
            continue
        if any(node.id in kept_ids for node in nodes):
            kept += 1
            continue
        trees.append(nodes)
    return FinishedJobsPlan(trees=trees, kept=kept)


#: 「清空已结束」一批删多少个任务。删的时候攥着写锁(连带它们的事件、外键上的置空),一批要短。
DELETE_JOBS_BATCH = 500


def delete_jobs(db: Session, ids: list[str]) -> int:
    """按 id 删一批任务连同它们的事件(不提交)。返回删了几个。批的大小由调用方定(见 DELETE_JOBS_BATCH)。"""
    if not ids:
        return 0
    db.execute(delete(TaskEvent).where(TaskEvent.job_id.in_(ids)).execution_options(synchronize_session=False))
    db.execute(delete(Job).where(Job.id.in_(ids)).execution_options(synchronize_session=False))
    return len(ids)
