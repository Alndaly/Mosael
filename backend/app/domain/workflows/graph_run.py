"""一轮图跑完的样子 —— 执行内核(engine.run_graph)交回、内嵌子图(executors.common.run_body_to_the_end)转交的那一份。

单放一个模块：内核和执行器两边都要用它，而 engine → executors 已经是一条导入边，反过来再导一次就成环。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphRun:
    """一轮图跑完的样子。

    **有节点失败时 `context` 里照样是已经落定的那些节点的产物**(出好的图、建好的项目……),`error` 是失败的原因,
    `failed_node` 是哪个节点。此前内核一失败就直接抛出，上下文跟着扔掉:循环选了「一项失败就记下、接着跑别的」,
    这一项里已经出了、付了钱的图也一并不见;顶层失败的任务结果里只剩一句原因。谁要据此交付，看这一份。
    """

    context: dict[str, Any]
    cancelled: bool
    error: Exception | None = None
    failed_node: str = ""
