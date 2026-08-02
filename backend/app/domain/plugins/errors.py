"""插件域的错误类型。

单独一个模块是为了**打断依赖环**:packages / instances / tools 三者互相要用它,而它们之间
本来就有调用关系。把它留在其中任何一个里,另外两个就得反向 import 那一个。
"""

from __future__ import annotations


class PluginDomainError(ValueError):
    """插件不可用 / 声明不合法 / 操作不被允许。调用方把它翻成 4xx,不是服务端故障。"""


__all__ = ["PluginDomainError"]
