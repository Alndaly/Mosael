"""插件连接背后**有没有一个宿主管的本机服务**、它此刻在不在(ADR 0041)—— 插件域只认这道缝。

本机服务的进程管理住在 `domain/local_services`,它要调插件(问怎么起),插件域反过来要在每次调用之前问它一声
(「用到时起」),两边直接 import 就成环。所以和 `host_capabilities.use_table` 同一个手法:组装根把实现交进来
(`use`),插件域只调这里的几个函数。没接上时(只 import 了插件域的脚本、测试)一律当作没有本机服务。

- `prepare`:一次插件调用之前。这个连接有本机服务、而它停着,就先替它起进程(任务里报一句进度),交回两样:要加进
  插件环境的变量(插件据此知道「这台服务器归宿主起停」,比如装完节点要重启时请宿主重启),和「等它就绪」—— 等的
  那一段由调用方在交还数据库连接之后再做(见 plugins/tools._plugin_slot),第一次起可能要一两分钟;
- `no_autostart`:**后台刷新目录**(就绪之后那一次、启动时那一次、每分钟问指纹、改配置之后对齐)包在它里面 ——
  这几件事不是「用它」,不替它起进程,没在跑就直接说没在跑(拍板 4:用到时才起)。此前只在调用处挑:一个刚就绪
  就崩的服务,就绪后那次刷新正好撞上它崩了,于是替它又起了一次,「5 分钟内最多重启 3 次」就此失效;
- `idle`:有本机服务、而它现在没在跑。后台刷新先看这个,停着的连接干脆不问(目录留着上次的;它起来以后会自己
  通知刷新一次)。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import PluginInstance

#: 报一句进度:(0..1, 一句话)。在任务里跑时接到任务总线,不在任务里就没人听。
Progress = Callable[[float, str], None]


def _ready_now() -> None:
    return None


@dataclass(frozen=True)
class Prepared:
    """一次插件调用之前,本机服务那一侧交回的。"""

    #: 加进插件环境的变量。
    env: dict[str, str]
    #: 等它就绪:刚替它起了进程就等到它能用,本来就在跑就立刻回来;起不来在这里抛。**不碰数据库** ——
    #: 调用方先交还连接再调它。
    wait_ready: Callable[[], None] = _ready_now


#: 这个连接背后没有宿主管的本机服务。
NO_SERVICE = Prepared(env={})


@dataclass(frozen=True)
class Gate:
    #: (库, 连接, 停着要不要起, 报进度) → 见 Prepared。没在跑又不让起时抛。
    prepare: Callable[[Session, PluginInstance, bool, Progress], Prepared]
    idle: Callable[[Session, PluginInstance], bool]


def _no_service(_db: Session, _instance: PluginInstance, _start: bool, _progress: Progress) -> Prepared:
    return NO_SERVICE


def _never_idle(_db: Session, _instance: PluginInstance) -> bool:
    return False


_gate = Gate(prepare=_no_service, idle=_never_idle)

#: 这一段调用能不能替本机服务起进程。缺省能(用到时起);后台刷新目录时关掉(见 no_autostart)。
_autostart: ContextVar[bool] = ContextVar("mosael_service_autostart", default=True)


def use(gate: Gate) -> None:
    """组装根调一次:本机服务的实现(见 domain/local_services)。"""
    global _gate
    _gate = gate


@contextmanager
def no_autostart() -> Iterator[None]:
    """包在里面的插件调用不替本机服务起进程(后台刷新目录用)。线程不继承它:后台线程自己包。"""
    token = _autostart.set(False)
    try:
        yield
    finally:
        _autostart.reset(token)


def prepare(db: Session, instance: PluginInstance, *, progress: Progress) -> Prepared:
    """一次插件调用之前:有本机服务、而它停着,就先替它起进程(在 `no_autostart` 里只看、不起 —— 没在跑就抛)。
    交回要加进插件环境的变量和「等它就绪」。起不来照抛(调用就此失败,原因是本机服务说的那一句)。"""
    return _gate.prepare(db, instance, _autostart.get(), progress)


def idle(db: Session, instance: PluginInstance) -> bool:
    """这个连接有本机服务、而它现在没在跑。"""
    return _gate.idle(db, instance)


__all__ = ["NO_SERVICE", "Gate", "Prepared", "Progress", "idle", "no_autostart", "prepare", "use"]
