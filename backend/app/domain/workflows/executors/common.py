"""执行器共用的小工具:节点里的「等」、子 job 轮询、宽容的输入解析。"""

from __future__ import annotations

import contextvars
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.jobs import cancel_job_tree, current_parent_job_id
from app.domain.workflows import NODE_TYPES, WorkflowDomainError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CHILD_POLL_SECONDS = 2.0

T = TypeVar("T")

#: 这一轮图的「停」信号,外层图在前、当前这张图在最后。
#:
#: 一轮图要停有两种原因:外层工作流被取消(库里那一行落了终态),或者**同一张图里有节点失败了**
#: —— 整条工作流已经失败,还在跑的兄弟节点做完了也没人要。前者任何人都能从库里读到;后者只有
#: 引擎知道,由它在失败那一刻立起来(见 engine.execute_graph)。
#:
#: 用上下文变量传:节点在引擎的线程池里带着提交时的上下文跑(copy_context),嵌套的图(循环体、
#: 子图)在节点线程里再压一层 —— 外层停了,里面所有层都看得见。
_HALTS: contextvars.ContextVar[tuple[threading.Event, ...]] = contextvars.ContextVar(
    "mosael_workflow_halts", default=()
)


@contextmanager
def halt_scope() -> Iterator[threading.Event]:
    """为一轮图压一个「停」信号。在这里面提交的节点都认它。"""
    halt = threading.Event()
    token = _HALTS.set((*_HALTS.get(), halt))
    try:
        yield halt
    finally:
        _HALTS.reset(token)


def _stopping(db: Session) -> bool:
    """这一轮是不是正在停:哪一层图立了停的信号,或者外层工作流已经落了终态。"""
    if any(halt.is_set() for halt in _HALTS.get()):
        return True
    parent_id = current_parent_job_id()
    if parent_id is None:
        return False
    parent = db.get(Job, parent_id)
    return parent is None or parent.status not in ("queued", "running")


def wait_until(
    check: Callable[[Session], T | None],
    *,
    release: Session | None = None,
    on_stop: Callable[[Session], None] | None = None,
    deadline: float | None = None,
) -> T:
    """节点里「等」的唯一形状:每一拍用一个新会话问一次 `check`,给出非 None 就返回它。

    - **这一轮在停,等就结束**(见 _HALTS):先让 `on_stop` 收拾自己等的东西(子任务取消掉),
      再抛 wfErr_cancelled。此前等子任务只认子任务的终态,等延时干脆是一句 `time.sleep` ——
      取消一条正在延时的工作流要等满那几分钟,一个节点失败了,引擎还要陪兄弟节点把子任务跑完。
    - **等的时候不占连接**:`release` 是调用方自己的会话,连同引擎的连接预算一起交还
      (见 wait_for_job 的说明)。
    - `deadline`(time.monotonic 的基准)给了的话,最后一拍只睡到它为止。
    """
    if release is not None:
        release.commit()
        release.close()
    with _budget_released(release is not None):
        while True:
            with SessionLocal() as db:
                value = check(db)
                if value is not None:
                    return value
                if _stopping(db):
                    if on_stop is not None:
                        on_stop(db)
                        db.commit()
                    raise WorkflowDomainError("wfErr_cancelled")
            pause = CHILD_POLL_SECONDS
            if deadline is not None:
                pause = max(0.0, min(pause, deadline - time.monotonic()))
            time.sleep(pause)


def wait_for_job(job_id: str, *, release: "Session | None" = None) -> Job:
    """轮询子 job 到终态(用独立会话,避免长事务)。

    **`release` 是调用方自己的会话:等待期间把它连同引擎的连接预算一起交还。**

    一个只是在等的节点不该占着连接。不还的话,引擎那份预算(engine.NODE_CONNECTIONS)会
    被一群等着的父节点占满,而它们等的正是子图里那些**取不到预算**的节点 —— 死锁,而且表现
    是"工作流卡住不动",看不出和连接池有关。父会话在等待期间也确实没有任何用处:这里轮询
    用的是自己开的独立会话。

    `Session.close()` 之后再用它会自动重新取一条连接,所以调用方在这个函数返回之后照常使用。

    **没有"等太久就放弃"这一条。** 此前有(通用 15 分钟,字幕配音按条数放宽),而放弃等待并不会
    让子任务停下 —— 它照样在生成、照样扣费,只是做完之后没人要了。付过账:三条 Seedance 在第
    300 秒被判超时,火山那边 6 分钟后全部生成成功、全部扣费,成片无人认领。

    结束只有两种:子任务落终态,或者这一轮在停(用户取消、同一张图里别的节点失败了)——
    那时子任务连同它的后代一并取消(见 jobs.cancel_job_tree),不留一个没人要的活儿接着花钱。
    子任务各自有自己的上限(生成任务的轮询上限防的是"供应商永远不回话",见
    contracts.generation.POLL_TIMEOUT_SECONDS)。
    """

    def settled(db: Session) -> Job | None:
        job = db.get(Job, job_id)
        if job is None:
            raise WorkflowDomainError("wfErr_childMissing")
        if job.status == "failed":
            raise WorkflowDomainError("wfErr_childFailed", params={"reason": job.error or job.message})
        if job.status == "succeeded":
            db.expunge(job)
            return job
        return None

    def abandon(db: Session) -> None:
        job = db.get(Job, job_id)
        if job is not None:
            cancel_job_tree(db, job)

    return wait_until(settled, release=release, on_stop=abandon)


@contextmanager
def _budget_released(active: bool):
    """等待期间把引擎的连接预算还回去,等完再拿回来。"""
    from app.domain.workflows.engine import NODE_CONNECTIONS

    if not active:
        yield
        return
    NODE_CONNECTIONS.release()
    try:
        yield
    finally:
        NODE_CONNECTIONS.acquire()


def run_body(node_type: str, body: dict[str, Any], scope: dict[str, Any], *, workflow_id: str) -> dict[str, Any]:
    """跑一个内嵌子图(循环体的一次迭代 / subgraph),返回它的上下文。

    **与主引擎同一套内核**(execute_graph):并行调度、数据边绑定、插值、条件分支语义完全一致;
    无入边的根即入口。`scope` 播种体内看得见的作用域名,**必须恰好是节点声明的 `body_scope`**
    —— 校验和画布都按那份声明判断体内引用合不合法,这里播的少一个,那个名字下的引用就会校验
    得过、运行时安静地变成空串。

    体在运行前已经由 validate_graph 连同外层一起校验过(带着插件节点类型),这里不再校验一遍。
    """
    declared: dict[str, list[str]] = NODE_TYPES[node_type]["body_scope"]
    if set(scope) != set(declared):
        raise RuntimeError(f"{node_type} seeds its body with {sorted(scope)} but declares body_scope {sorted(declared)}")
    for root, fields in declared.items():
        # 字段固定的作用域(`loop`)逐个字段核对;`*配置字段` 的键来自这次的配置,不在这里核。
        if not any(one.startswith("*") for one in fields) and set(scope[root]) != set(fields):
            raise RuntimeError(f"{node_type} seeds {root} with {sorted(scope[root])} but declares {sorted(fields)}")
    from app.domain.workflows.engine import execute_graph  # 惰性:避开 engine↔executors 循环导入

    context, cancelled = execute_graph(body, wf_id=workflow_id, initial_context=scope, entry_is_root=True)
    if cancelled:
        raise WorkflowDomainError("wfErr_cancelled")
    return context


def provided(values: dict[str, Any]) -> dict[str, Any]:
    """只留**填了的**那几项 —— 节点把一份键值交给外面(插件工具的入参、生成供应商的参数)之前走这里。

    空串是编辑器给没填的格子种的值,上游引用落空插值出来也是它。原样交出去会让"没填"和
    "填了空串"变成同一件事:工具的必填校验失效(它收到一个存在但为空的键),布尔 / 整数参数
    收到空串报「不是布尔值」「不是整数」,校验不管的就直接发给供应商。`False`、`0` 是填了的值,留着。

    收在这一处:插件节点和生成节点曾经一个过滤一个不过滤。
    """
    return {key: value for key, value in values.items() if value is not None and value != ""}


def id_list(value: Any) -> list[str]:
    """Accept either a comma-separated string or a real list.

    Both reach here legitimately: a hand-typed config gives a string, while `{{查询.ids}}`
    resolves to the list asset_query produced. Treating the list case as a string would
    stringify it and match nothing, with no error to show for it.
    """
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").replace("，", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def text_lines(value: Any) -> list[str]:
    """一列文本 —— 「翻译整轨」「生成字幕」的 texts 共用这一份解析。

    三种写法都合法,因为它们来自三个地方:真正的列表(上游节点的输出,整串引用时插值保留
    原类型)、一段 JSON 数组文本(接 LLM 的 text 输出)、一行一条的文本(手填)。列表里的
    元素可以是带 `text` 的段落(逐字稿的 segments),取它的正文。

    **不能按逗号拆** —— 句子里全是逗号,id_list 那套在这里会把一句话拆成五句。
    **顺序即对齐**:空行照样占一个位置,下游靠第 i 条配第 i 段。
    """
    if isinstance(value, dict):
        raise WorkflowDomainError("wfErr_textsArray")
    if not isinstance(value, list):
        text = str(value or "").strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return text.splitlines()
        if not isinstance(value, list):
            raise WorkflowDomainError("wfErr_textsArray")
    return [
        str(item.get("text", "")) if isinstance(item, dict) else str(item if item is not None else "")
        for item in value
    ]


def truthy(value: Any) -> bool:
    """Loop-condition truthiness: real bools/None as-is; strings "false"/"0"/"" (any case) are False."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "no", "none")
    return bool(value)
