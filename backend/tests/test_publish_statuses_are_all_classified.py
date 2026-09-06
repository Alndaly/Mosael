"""棘轮:**每个发布状态都要被归到首页那三档里的一档**,不多不少。

`_publish_summary_bucket` 把状态分成 succeeded / failed / blocked / active,而它最后有一句
兜底 `return "active"` —— 那句让「漏掉一个状态」不报错,只是首页永远显示还有几条在跑。
一个看起来永远没干完的发布队列,而实际上那几条早就结束了。

`queued` 就是漂出来的证据:它躺在 ACTIVE 里,而发布任务根本没有这个状态(建出来是 pending,
之后只走 report_task,后者按 TASK_STATUSES 校验)。没有任何东西会因此报错。

所以把三个手写的集合和权威集合绑起来:合起来正好覆盖,且不含权威集合以外的东西。
"""

from __future__ import annotations

RATCHET = True


def _sets():
    from app.api.routes.workspaces import PUBLISH_ACTIVE_STATUSES, PUBLISH_BLOCKED_STATUSES
    from app.domain.publish import TERMINAL_TASK_STATUSES

    return {
        "TERMINAL_TASK_STATUSES": set(TERMINAL_TASK_STATUSES),
        "PUBLISH_ACTIVE_STATUSES": set(PUBLISH_ACTIVE_STATUSES),
        "PUBLISH_BLOCKED_STATUSES": set(PUBLISH_BLOCKED_STATUSES),
    }


def test_每个状态都归了档() -> None:
    from app.domain.publish.worker import TASK_STATUSES

    covered = set().union(*_sets().values())
    missing = sorted(set(TASK_STATUSES) - covered)
    assert not missing, (
        "这些发布状态没被归档,会被 _publish_summary_bucket 的兜底算成「进行中」——"
        f"首页于是永远显示有几条在跑:{missing}"
    )


def test_没有归了档却不存在的状态() -> None:
    from app.domain.publish.worker import TASK_STATUSES

    for name, group in _sets().items():
        stale = sorted(group - set(TASK_STATUSES))
        assert not stale, f"{name} 里这些状态发布任务根本不会有,删掉:{stale}"


def test_三档互不重叠() -> None:
    """一个状态同时算「进行中」和「已结束」的话,首页两个数会对不上,而两边看起来都对。"""
    groups = list(_sets().items())
    for index, (name, group) in enumerate(groups):
        for other_name, other in groups[index + 1 :]:
            overlap = sorted(group & other)
            assert not overlap, f"{name} 和 {other_name} 都包含 {overlap}"


def test_归档函数和集合说的是一回事() -> None:
    """集合对了,分档函数也可能自己另写一套判断 —— 那才是首页真正读的东西。"""
    from app.api.routes.workspaces import _publish_summary_bucket
    from app.domain.publish import TERMINAL_TASK_STATUSES
    from app.api.routes.workspaces import PUBLISH_ACTIVE_STATUSES, PUBLISH_BLOCKED_STATUSES

    for status in TERMINAL_TASK_STATUSES:
        expected = "succeeded" if status == "success" else "failed"
        assert _publish_summary_bucket(status) == expected, status
    for status in PUBLISH_BLOCKED_STATUSES:
        assert _publish_summary_bucket(status) == "blocked", status
    for status in PUBLISH_ACTIVE_STATUSES:
        assert _publish_summary_bucket(status) == "active", status
