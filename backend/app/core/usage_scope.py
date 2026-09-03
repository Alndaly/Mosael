"""这次请求 / 这次任务是在**替哪个工作区**花钱。

叶子模块,只依赖 contextvars。

## 为什么是环境变量而不是穿参

`ProviderUsageEvent.workspace_id` 是 NOT NULL,而发起供应商调用的地方普遍很深:翻译在
字幕面板底下、素材分析在一个只拿得到 ORM 对象的叶子函数里。
把 workspace_id 一路穿下去,代价是**每个调用点收一次,并且对未来每个新调用点重复收费** ——
而事实是:八个对话调用点里,曾经零个上报。税太高的接口没人交税。

这个仓库对同类问题已经三次选了同一条路,都写了理由:
  - `core/permissions._request_method` —— 就在隔壁,把 HTTP 方法绑进上下文供写闸门读;
  - `domain/network` 的出站代理 —— 改进程环境变量,"而不是给十几处 httpx.Client 逐个传";
  - `domain/ai_retry` 的重试次数 —— "调用点散在十几个适配器里,其中不少拿不到 db 会话"。

代价是隐式:出问题时"这笔钱为什么记在这个工作区"要看调用栈而不是签名。所以
`billable()` 允许显式传 workspace_id 覆盖,显式永远优先。

## 线程

contextvars **不会**自动跨到 ThreadPoolExecutor 的工作线程。字幕整批翻译使用线程池,
所以它得用 `run_in_scope` 提交任务,否则工作线程里读到的是空。
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

#: 当前上下文归属的工作区;空串 = 不知道(登录、实例级配置、后台巡检等)。
_workspace: contextvars.ContextVar[str] = contextvars.ContextVar("mosael_usage_workspace", default="")

T = TypeVar("T")


def bind_workspace(workspace_id: str) -> None:
    """把工作区绑进当前上下文。由权限闸门调用 —— 那里是"这次请求关于哪个工作区"的唯一真源。"""
    if workspace_id:
        _workspace.set(workspace_id)


def current_workspace() -> str:
    return _workspace.get()


@contextmanager
def workspace_scope(workspace_id: str) -> Iterator[None]:
    """在一段代码里临时指定工作区。给没有 HTTP 请求的入口用:后台任务、worker、定时触发。"""
    token = _workspace.set(workspace_id or "")
    try:
        yield
    finally:
        _workspace.reset(token)


def run_in_scope(fn: Callable[..., T]) -> Callable[..., T]:
    """把当前的工作区归属带进包装后的函数,供 ThreadPoolExecutor 使用。

    `pool.map(run_in_scope(one), items)` —— 不这样做的话,工作线程里 current_workspace()
    永远是空串,而那正是最需要它的两处(整批翻译、图谱抽取)。

    传的是**值**而不是 `contextvars.copy_context()` 的那个 Context 对象:一个 Context 不能
    被同时进入两次,而线程池天生就是并发调用同一个包装函数 —— 拿 Context 去 run,八个 worker
    里有七个会撞上 "cannot enter context: ... is already entered"。这个模块只拥有工作区
    归属这一个值,那就只带这一个,顺带也说清了它的边界。
    """
    workspace = _workspace.get()

    def wrapped(*args: Any, **kwargs: Any) -> T:
        token = _workspace.set(workspace)
        try:
            return fn(*args, **kwargs)
        finally:
            _workspace.reset(token)

    return wrapped
