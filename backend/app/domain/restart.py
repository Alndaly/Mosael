"""重启之后,谁来收尾。

后端一重启,所有进程内的线程、子进程、MCP 连接、执行器视图都没了。**在调用之前就落库的那些
「进行中」的行,自己不会醒过来** —— 它们停在最后一刻的样子,在界面上看起来像还在跑。

这条规矩在本仓库里被建立过**四次**,每一次都写了很好的理由(`jobs.reconcile_orphaned_jobs`、
`agent/host.reconcile_orphaned_agent_sessions`、`browser.reconcile_browser_state`、素材那两条)。
第五、第六处照样漏了:插件调用记录永远停在 running,Blender 互通记录永远停在 sending。

结论不是"再加两个 reconciler",而是:**靠人记得给每个新的「先落 running 再去跑」补一个收尾,
是不成立的**。所以有了这份登记。

判据由 `tests/test_every_in_flight_row_has_someone_to_settle_it.py` 从 ORM **推导**:凡是状态列
默认成「进行中」那一类值的表,都必须在这里登记 —— 要么给一个收尾函数,要么写清为什么不需要。
加一张新表时,这个问题会自己找上门。

磁盘上的记录(Blender 的 `transfer.json`)推导不出来,它在 `main.py` 的启动收尾里单列,
函数是 `blender.bridge.reconcile_orphaned_transfers`。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

#: 表名 → 为什么这张表的「进行中」**不是**被重启孤立的。每条都要说得出理由。
NOT_ORPHANED_BY_RESTART: dict[str, str] = {
    "agent_questions": "在等**人**回答,不在等进程。重启不改变「还没人答」这件事。",
    "tool_confirmations": "同上:在等人点批准。(那一轮留下的卡由 reconcile_orphaned_agent_sessions 作废。)",
    "workspace_invitations": "在等**人**接受邀请;它的终结条件是对方点了,不是某个进程跑完。",
    "publish_tasks": (
        "由**执行器下一次认领**时自愈:它重启后在跑集合是空的,那些 running 的 owner 已消失,"
        "当场判 failed 可重试(见 test_orphaned_running_task_is_reclaimed_on_fresh_claim)。"
        "放在认领那一刻而不是启动那一刻,是因为执行器是另一个进程,它和后端不同生共死。"
    ),
    "scheduled_task_runs": (
        "它是**派生**的:运行记录跟着它派出去的那个 job 走。job 在启动时被收尾,"
        "`scheduler/executors.sync_run_states` 随后把终态抄过来。"
    ),
}


def registered() -> dict[str, Callable[[Session], int]]:
    """表名 → 收尾函数。

    **每次现建,不留模块级的可变字典**:它只是一份查表,而"模块级可变状态"在这个仓库里另有
    含义(见 docs/PROCESS_STATE.md 和盯着它的那条棘轮)—— 把一份纯查表混进那份清单,会稀释
    它真正要回答的问题。导入延迟到这里,是因为这些模块反过来会用到领域层的东西。
    """
    from app.domain.browser import reconcile_browser_state
    from app.domain.jobs import reconcile_orphaned_jobs
    from app.domain.plugins.tools import reconcile_orphaned_invocations

    return {
        "jobs": reconcile_orphaned_jobs,
        "plugin_invocations": reconcile_orphaned_invocations,
        # 浏览器那条要收的不止一张表(还有执行器视图),签名也不吃 Session ——
        # 包一层,让这份登记上的每一项长得一样。
        "browser_actions": lambda _db: reconcile_browser_state(),
    }


def reconcile_after_restart(db: Session) -> dict[str, int]:
    """把上一个进程留下的「进行中」逐个收尾。返回每张表处理了几行。"""
    return {table: settle(db) for table, settle in registered().items()}
