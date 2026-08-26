"""插件与素材库之间**唯一的**接触面。

插件要搬字节,两个方向都要:

    宿主 → 插件   把一份素材交给它(上传到网盘、发给外部服务处理)
    插件 → 宿主   把它产出的文件收进素材库(从网盘拉、AI 服务生成)

这两件事看起来在两头,其实是同一道缝:**"素材库"这个概念在插件这一侧不该存在**。
插件声明的是「我要一个文件」和「这是我产出的文件」,至于文件从哪来、到哪去,是宿主的事。

所以这里只定义**契约**,不认识素材库 —— 和 jobs 不认识智能体是同一个道理(见
domain/jobs 的回执登记处)。真正会 import assets 的是 domain/assets/plugin_bridge,
它在启动时把自己登记进来。

这样换一种来源不用动插件这一层:哪天要支持「从一个 URL 取文件交给插件」,登记另一个
解析器即可,`tools.invoke` 一行都不用改。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session


class Sink(Protocol):
    """文件 → 宿主。返回一个**引用**(素材 id),插件拿到的就是它。"""

    def __call__(
        self, db: Session, path: Path, *, workspace_id: str, project_id: str | None, name: str
    ) -> tuple[str, str]: ...


class Source(Protocol):
    """引用 → 文件。把它落到 `into` 那个目录里,返回落好的路径。"""

    def __call__(self, db: Session, ref: str, *, into: Path, workspace_id: str) -> Path: ...


_sink: Sink | None = None
_source: Source | None = None


def use_sink(sink: Sink) -> None:
    global _sink
    _sink = sink


def use_source(source: Source) -> None:
    global _source
    _source = source


def sink() -> Sink:
    if _sink is None:
        raise RuntimeError("插件产出的落点没有装配(见 app/main 的启动装配)")
    return _sink


def source() -> Source:
    if _source is None:
        raise RuntimeError("插件输入的来源没有装配(见 app/main 的启动装配)")
    return _source


__all__ = ["Sink", "Source", "sink", "source", "use_sink", "use_source"]
