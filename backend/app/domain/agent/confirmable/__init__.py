"""**一个工具一处声明**:要什么权限、卡上怎么说、批准之后做什么。

此前这些摊在 confirmations.py 的四条 if 链上(TOOL_DEFS + 校验 + 摘要 + 执行),加一个工具要在
四处各补一段,而漏掉的那一段不会报错 —— 漏了校验就是一张说不清要做什么的卡,漏了摘要就是
一张只写着工具名的卡。现在一个工具就是一条 `ConfirmableTool`,按领域分文件登记。

内核(confirmations.py)只管这张卡的生命周期:开卡、认人、领卡、执行、回执。它不认识任何
具体工具。
"""

from app.domain.agent.confirmable.registry import PERMISSIONS, ConfirmableTool, confirmable_tool, tool_spec, tool_specs

#: 登记的副作用发生在 import 时,所以这些模块必须被引到(和 workflows 的执行器同一个做法)。
from app.domain.agent.confirmable import (  # noqa: F401,E402  (registration)
    automation, blender, deletion, external, generation, media,
)

__all__ = ["PERMISSIONS", "ConfirmableTool", "confirmable_tool", "tool_spec", "tool_specs"]
