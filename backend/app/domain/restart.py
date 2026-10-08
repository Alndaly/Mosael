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
    "browser_partition_moves": (
        "在等**桌面端的浏览器执行器**在磁盘上搬登录分区,不在等后端进程:它启动时领走还没搬的、搬完回报。"
        "后端重启不改变「还没搬」这件事。"
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
    from app.domain.documents.extraction import reconcile_orphaned_extractions
    from app.domain.generation.runner import reconcile_unsettled_charges
    from app.domain.jobs import reconcile_orphaned_jobs
    from app.domain.plugins.tools import reconcile_orphaned_invocations
    from app.domain.voices.remote import reconcile_orphaned_enrollments

    return {
        "jobs": reconcile_orphaned_jobs,
        # 生成那几笔没来得及记的账(调到一半没了的估一笔;停下之后正在跟的接着跟)。**排在 jobs 之后**:要看的正是
        # 上一步判了「后端重启中断」的那些,能接着取的已经被它接走。
        "generation_jobs": reconcile_unsettled_charges,
        "plugin_invocations": reconcile_orphaned_invocations,
        # 克隆音色的远端副本(ADR 0037):建到一半进程没了的,记成失败、下次用到时重建。
        "voice_enrollments": reconcile_orphaned_enrollments,
        # 浏览器那条要收的不止一张表(动作和会话都收),和别的几项一样用收尾那一个事务。
        "browser_actions": reconcile_browser_state,
        "asset_extractions": reconcile_orphaned_extractions,
    }


def reconcile_after_restart(db: Session) -> dict[str, int]:
    """把上一个进程留下的「进行中」逐个收尾。返回每张表处理了几行。"""
    return {table: settle(db) for table, settle in registered().items()}


def settle_previous_run() -> dict[str, int]:
    """启动时收上一个进程的尾。**一次用例、一个事务**:所有收尾都做完才一起提交,提交钩子在那之后才跑。

    提交钩子里有副作用:任务落终态之后的收拾、把回执送回发起它的对话(会在空闲的对话里**起一轮**)、接着干能接着干的
    远端任务。此前任务那一步自己提交,钩子当场就跑 —— 回执起的那一轮,紧接着被下一步「把卡住的会话拨回 idle」当成重启前
    的孤儿拨回去,还补了一句「上一轮对话因后端重启而中断」;而那一轮其实正在跑,用户再发一句就是同一个会话两轮并发。
    现在会话先被拨回、卡片先作废,回执再来;回执起的那一轮就是唯一在跑的那一轮。

    会话那一步不按表登记(它要收的不止 agent_sessions 一张,那一轮留下的确认卡也要作废);两个「补派生物」的扫描
    (预览代理、坏素材的时长)也在这一个事务里,它们派出去的任务同样在提交之后才起线程。磁盘上的记录(Blender 的
    transfer.json)推导不出来,事务之外单列。返回每一项处理了几行。
    """
    from app.core.unit_of_work import unit_of_work
    from app.domain.agent.host import reconcile_orphaned_agent_sessions
    from app.domain.assets import reconcile_broken_media_info
    from app.domain.assets.proxies import reconcile_missing_proxies
    from app.domain.blender.bridge import reconcile_orphaned_transfers

    with unit_of_work() as db:
        settled = reconcile_after_restart(db)
        settled["agent_sessions"] = reconcile_orphaned_agent_sessions(db)
        reconcile_missing_proxies(db)
        reconcile_broken_media_info(db)
    settled["blender_transfers"] = reconcile_orphaned_transfers()
    return settled
