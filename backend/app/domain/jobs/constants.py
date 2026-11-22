"""任务状态的公共词汇。"""

from __future__ import annotations

#: 被停下的任务落的状态(ADR 0049):人点了停止 / 取消,或者 Mosael 替人做的决定 —— 父任务被取消了、等它的那一轮停了。
#: 它是终态,而且**进去就出不来**(见 _terminal_is_terminal)。租约过期、重启打断、父任务失败照旧是 failed:那不是谁的决定。
CANCELLED = "cancelled"
TERMINAL_STATUSES = ("succeeded", "failed", CANCELLED)
#: 任务系统只有这两种非终态。轮询必须用正向集合命中 `(workspace_id, status, …)` 索引;
#: `NOT IN TERMINAL_STATUSES` 会为了找零条活动任务扫描整个工作区的历史。
IN_FLIGHT_STATUSES = ("queued", "running")
#: 「被停下了」的那句话(「已取消」)。任务本身不再用它记取消(见 CANCELLED);还用它的:执行体发现自己没人要了时抛的
#: JobCancelled、工作流节点事件里那一步「被停下」、生成记录上抄下的「已停止」(generation.runner.record_failure)。
CANCELLED_ERROR_KEY = "jobErr_cancelled"
#: 「后端重启时它还在跑、接不回来」的记法:failed + 这个 key(见 reconcile_orphaned_jobs)。
RESTART_ERROR_KEY = "jobErr_backendRestart"


def was_cancelled(job: object) -> bool:
    """这个任务是不是被停下的(状态是 `cancelled`,ADR 0049)。"""
    return getattr(job, "status", None) == CANCELLED
