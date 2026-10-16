"""一轮图跑完的样子 —— 执行内核(engine.run_graph)交回、内嵌子图(executors.common.run_body_to_the_end)转交的那一份。

单放一个模块：内核和执行器两边都要用它，而 engine → executors 已经是一条导入边，反过来再导一次就成环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraphResume:
    """**从暂停的那一个节点接着跑**:哪些节点已经落定、它们的产物是什么。

    「等人确认」把一轮图拆成两半,`GraphResume` 就是两半之间那份现场(见
    domain/workflows/approvals)。`done` 里的节点**直接跳过、不执行** —— 这条是这份东西存在的
    全部理由:前面跑完的节点可能已经烧了钱、落了素材,恢复时重跑一遍就是又买一次。

    - `executed`:真正执行过的节点(不含被条件分支跳过的);
    - `done`:executed ∪ 被跳过的 —— 调度看的那个集合(见 engine.run_graph 的 waits_for);
    - `context`:节点 id → 产物。**整份存**,不按事件那种有界快照截断:下游插值要用的就是完整值。
    """

    context: dict[str, Any] = field(default_factory=dict)
    executed: frozenset[str] = frozenset()
    done: frozenset[str] = frozenset()

    @classmethod
    def from_checkpoint(cls, raw: Any) -> GraphResume | None:
        """从落库的那份现场(`WorkflowRunApproval.checkpoint`)读回来;认不出的当没有。"""
        if not isinstance(raw, dict):
            return None
        context = raw.get("context")
        if not isinstance(context, dict):
            return None
        return cls(
            context=context,
            executed=frozenset(str(one) for one in raw.get("executed") or ()),
            done=frozenset(str(one) for one in raw.get("done") or ()),
        )

    def checkpoint(self) -> dict[str, Any]:
        """落库的形状(JSON)。"""
        return {"context": self.context, "executed": sorted(self.executed), "done": sorted(self.done)}


@dataclass(frozen=True)
class GraphRun:
    """一轮图跑完的样子。

    **有节点失败时 `context` 里照样是已经落定的那些节点的产物**(出好的图、建好的项目……),`error` 是失败的原因,
    `failed_node` 是哪个节点。此前内核一失败就直接抛出，上下文跟着扔掉:循环选了「一项失败就记下、接着跑别的」,
    这一项里已经出了、付了钱的图也一并不见;顶层失败的任务结果里只剩一句原因。谁要据此交付，看这一份。

    **`awaiting` 是第三种收场**:这一轮没失败也没跑完,而是停在「等人确认」那个节点上等一个决定。
    它不是错误 —— `error` 是空的、`cancelled` 是 False,上层据此写下检查点并把任务留在 running
    (见 engine.run_workflow)。`approval` 是那张待批单的 id。
    """

    context: dict[str, Any]
    cancelled: bool
    error: Exception | None = None
    failed_node: str = ""
    #: 停在哪个节点上等人确认(空 = 没停在这一步)。
    awaiting: str = ""
    #: 那张待批单的 id(见 db.models.WorkflowRunApproval)。
    approval: str = ""
    #: 这一轮落定的两个集合 —— 暂停时原样进检查点(见 GraphResume)。执行过的、以及执行过或跳过的。
    executed: frozenset[str] = frozenset()
    done: frozenset[str] = frozenset()

    @property
    def paused(self) -> bool:
        return bool(self.awaiting)
