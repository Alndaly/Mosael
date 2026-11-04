"""一轮图的「停」信号 —— 引擎立它,节点里的等待认它。

单独成一个模块,是因为两边都要用它而彼此不该互相 import:引擎(engine)在节点失败、工作流
被取消的那一刻立起来;执行器共用的等待(executors.common.wait_until)每一拍看一眼。
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager

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


@contextmanager
def shared_halt(halt: threading.Event) -> Iterator[None]:
    """把一个**已有的**「停」信号压进当前上下文:几路并行的工作共用它,一路失败立起来,其余各路里
    还在跑的节点都看得见(见 executors.loops 的并发遍历)。"""
    token = _HALTS.set((*_HALTS.get(), halt))
    try:
        yield
    finally:
        _HALTS.reset(token)


def halted() -> bool:
    """当前这一轮(或它外面任何一层)有没有立起停的信号。"""
    return any(halt.is_set() for halt in _HALTS.get())


#: 正在跑的是哪个节点。浏览器自动化把它带进动作参数(origin),执行器交来的下载 / 截图据此记出处
#: 「哪次运行、哪个节点」—— 执行器自己不认识工作流。
_NODE: contextvars.ContextVar[str] = contextvars.ContextVar("mosael_workflow_node", default="")


@contextmanager
def node_scope(node_id: str) -> Iterator[None]:
    """引擎在跑一个节点时压它的 id。"""
    token = _NODE.set(node_id)
    try:
        yield
    finally:
        _NODE.reset(token)


def current_node() -> str:
    """当前在跑的节点 id;不在节点里是空串。"""
    return _NODE.get()


#: 正在跑的这一层图在哪:从顶层往里经过的容器节点和第几轮(`loop1`、`#3`)。落定的节点按它分层记(见 run_steps),
#: 同一个循环体节点的每一轮是不同的一步。和「停」信号一样用上下文变量:节点在线程池里带着提交时的上下文跑。
_FRAMES: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("mosael_workflow_frames", default=())


@contextmanager
def step_frame(frame: str) -> Iterator[None]:
    """往里走一层:进一个容器节点、进循环的第几轮。"""
    token = _FRAMES.set((*_FRAMES.get(), frame))
    try:
        yield
    finally:
        _FRAMES.reset(token)


def step_scope() -> str:
    """当前这一层图的位置。顶层是空串。"""
    return "/".join(_FRAMES.get())


#: 这一轮是不是「从失败处继续」:是的话,每一层图开跑前读回已经落定的节点(见 engine.run_graph)。
_CONTINUING: contextvars.ContextVar[bool] = contextvars.ContextVar("mosael_workflow_continuing", default=False)


@contextmanager
def continuing_run(continuing: bool) -> Iterator[None]:
    """引擎在跑「从失败处继续」的那一轮时压它。"""
    token = _CONTINUING.set(continuing)
    try:
        yield
    finally:
        _CONTINUING.reset(token)


def is_continuing() -> bool:
    return _CONTINUING.get()
