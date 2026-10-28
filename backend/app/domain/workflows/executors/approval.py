"""「等人确认」节点(`await_approval`):跑到这一步**落库停下**,等一个人点确认 / 拒绝再往下走。

这个执行器本身很短 —— 它做的三件事:

1. **建单**(或认出重启前那张):标题、正文、按钮文案、超时怎么算都落进 `WorkflowRunApproval`;
2. **交出去**:抛 `AwaitingApproval`,引擎据此把这一轮停在暂停点上(见 engine.run_graph 的说明),
   上层把现场写进那张单。**这里不停、不轮询、不占线程** —— 一个等 24 小时的门不该占着一条线程。
3. **恢复时交回那一格**:重新进到这一步时单上已经有决定了,就地交回 `decision` 那几样给下游。

决定的**来源**不在这里:飞书卡片和应用内那两处都走 `approvals.decide_and_wake`(见
integrations/feishu/approvals 与 routes/workflows),一处写决定、一处唤醒,没有第二套。

## 拒绝:默认是一个错误,也可以是一个决定

`rejected` 按节点上的 `on_reject` 走两种:
- `abort`(**默认**):这一次运行**失败**(抛 `wfErr_awaitApprovalRejected`),决定不交到下游 —— 和
  超时 + `abort` 同一个失败口径;
- `branch`:`rejected` 和 `approved` 一样是**交出去的那一格**,下游用条件节点按它分支 —— 想
  "拒绝了就停下",就在 `rejected` 那条分支上接你要做的事。

超时 + `abort` 那一档依旧是失败:那时没有任何人做过决定,也就没有决定可以交给下游。

## 只放在主流程里,而且一次运行只停得住一个

循环体 / 子图里的暂停要往外套好几层,而落检查点的地方只有主流程(体的执行内核没有 job)。
运行前检查在开跑之前就拦下它 —— 那些图里前面的节点可能已经花了钱,不该跑到这一步才说。

主流程里**两个互相不可达**的「等人确认」(比如挂在同一个 start 底下的两条分支上)同样跑不动:
引擎一轮只抓一个暂停点,第二个 `AwaitingApproval` 会被当成兄弟节点的失败,整轮判 failed,而两张单
都停在"还没现场"上 —— 按钮点了什么都不会发生。这一条也在开跑前拦下(见 `_parallel_gates`)。
条件节点的真 / 假两条出口上的两个门不在此列:调度那一层按出口跳过没走到的那一支,那种图跑得起来。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.unit_of_work import unit_of_work
from app.db.models import Job
from app.domain.jobs import current_parent_job_id
from app.domain.workflows.errors import AwaitingApproval, WorkflowDomainError
from app.domain.workflows.executors.registry import (
    PreflightNode,
    RunScope,
    register,
    register_preflight,
)
from app.domain.workflows.run_scope import current_node

logger = logging.getLogger(__name__)


@register("await_approval")
def await_approval(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """决定已经下来就把它交给下游;还没下来就把这一轮停在暂停点上。"""
    from app.domain.workflows import approvals

    node_id = current_node()
    job_id = current_parent_job_id()
    if not job_id or not node_id:
        #: 不在任何任务里跑(脚本、单测直接调执行器):没有任务就没有可恢复的现场,也没有可唤醒的运行。
        raise WorkflowDomainError("wfErr_awaitNotResumable")

    row = approvals.find(db, job_id, node_id)
    if row is not None:
        if row.status != approvals.PENDING:
            #: **超时 + 中止是唯一会让这一次运行停在这里失败的档**:那时没有任何人做过决定,
            #: 没有决定可以交给下游(原因说清是超时,和别的节点失败同一个出口)。
            if row.status == approvals.TIMED_OUT and row.on_timeout == approvals.TIMEOUT_ABORT:
                raise WorkflowDomainError(
                    "wfErr_awaitApprovalTimedOut",
                    params={"node": row.node_name or row.node_id, "hours": _hours(row)},
                )
            #: **拒绝 + 中止**:那个人做了决定(拒绝),节点上写了"拒绝就中止",于是这次运行失败,
            #: 决定不交到下游 —— 和超时 + 中止同一个失败口径。要"拒绝了当成一个决定交下去"就写 on_reject=branch。
            if row.status == approvals.REJECTED and row.on_reject == approvals.REJECT_ABORT:
                raise WorkflowDomainError(
                    "wfErr_awaitApprovalRejected",
                    params={"node": row.node_name or row.node_id},
                )
            #: 决定交给下游的那几格。**`decision` 是三值文字**(approved / rejected / timeout):
            #: 下游用条件节点按它分支 —— 拒绝也可以是一个决定(节点上写了 on_reject=branch 时,见文件头)。
            return {
                "decision": row.decision or row.status,
                "decided_by": row.decided_by_name or "",
                "decided_by_id": row.decided_by or "",
                "note": row.note or "",
                "decided_at": row.decided_at.isoformat() if row.decided_at else "",
            }
        #: 单还在等:重启之后又进到这一步(上一轮的线程已经结束)。**不重发卡片、不重发通知** ——
        #: 那张卡还点得动,再发一张只会让人分不清哪张算数。
        raise AwaitingApproval(row.id, node_id)

    #: **自己开一个事务建单、先提交。** 引擎只在节点成功时提交(见 run_node 的事务边界),而这一轮
    #: 接下去要抛 AwaitingApproval —— 跟着它回滚的话,任务就恢复不了了。所以建单自己提交。
    #: **说出去(站内通知 / 飞书卡片)不在这里**:那要等引擎把恢复现场也写进这张单之后
    #: (见 engine._park_at_approval)—— 先发卡、现场还没落,手快的人点了确认就唤不醒那次运行。
    with unit_of_work() as adb:
        job = adb.get(Job, job_id)
        if job is None:
            raise WorkflowDomainError("wfErr_awaitNotResumable")
        row = approvals.prepare(
            adb,
            job=job,
            workflow_id=str(scope.id),
            node_id=node_id,
            node_name=_node_name(adb, job, node_id),
            config=config,
        )
        approval_id = row.id

    raise AwaitingApproval(approval_id, node_id)


def _node_name(db: Session, job: Job, node_id: str) -> str:
    """这个节点在图里叫什么:从**这次运行钉住的那一版修订**里找(不是工作流当前那一版 —— 图可能已经改了)。

    同一份"钉住的那一版"读数(`approvals.pinned_node`)也在发卡那一步用 —— 飞书那三格
    (`channel` / `bot` / `to`)从同一个地方读,免得两处各解一遍、各有一个答案。
    """
    from app.domain.workflows import approvals

    name = str(approvals.pinned_node(db, job, node_id).get("name") or "").strip()
    return name or node_id


def _hours(row: Any) -> int:
    return int(round((row.timeout_seconds or 0) / 3600))


@register_preflight("await_approval")
def _main_flow_and_one_at_a_time(
    _db: Session, _config: dict[str, Any], _actor: str | None, place: PreflightNode
) -> None:
    """**运行前**就拦下两种跑不动的摆法:

    1. 放在循环体 / 子图里 —— 第一版不支持,而且只有主流程有地方落检查点(见下面 `_nested`);
    2. 主流程里**两个互相不在对方上下游**的「等人确认」—— 它们可以同时被调度,而一次运行只记得住
       一个暂停现场(见 `_parallel_gates`)。

    不拦的话症状是:图里前面的付费节点全跑完,轮到它才说一句"接不下去"—— 而这个仓库反复修过的
    正是这一类(见 executors/registry 的 register_preflight 说明)。
    """
    if place.scope:
        raise WorkflowDomainError("wfErr_awaitApprovalNested")
    _parallel_gates(place)


def _parallel_gates(place: PreflightNode) -> None:
    """两个 `await_approval` 互相不可达(而且没有被条件出口分到两条互斥的岔上)—— 开跑前拦下。

    引擎一轮只停得下**一个**暂停点:`run_graph` 抓到第一个 `AwaitingApproval` 就停了,兄弟节点那边
    再抛一个同样的事就被当成**失败**(`error` 一落下,整轮 failed) —— 于是这一次运行判失败,而两张
    单都是 `pending` + 空检查点,永远挂在待批列表上:点了什么都不会发生,错误文本还是内部串
    `awaiting approval <hex> at node <id>`(实测,见 tests/test_await_approval_resume_gates.py)。

    判据用的是"这两个门会不会被同时调度":**互相不可达**是必要条件,但还不够 —— 条件节点的真 / 假两条
    出口上的两个门**永远不会同时活**(调度那一层按出口跳过没走到的那一支,见 engine.incoming_active),
    那种图今天是跑得起来的,不该被这条检查误拦。所以还要排除"被同一个会分支的节点分到两条互斥出口上"。
    """
    graph = place.graph if isinstance(place.graph, dict) else {}
    here = str(place.node.get("id") or "")
    gates = [
        str(node.get("id") or "")
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and str(node.get("type") or "") == "await_approval"
    ]
    if len(gates) < 2:
        return
    edges = _edges(graph)
    for other in gates:
        if other == here or other == "":
            continue
        if _reaches(edges, here, other) or _reaches(edges, other, here):
            continue
        if _branch_apart(graph, here, other):
            continue
        raise WorkflowDomainError(
            "wfErr_awaitApprovalParallel",
            params={"node": _title(place.node), "other": _title(_node(graph, other))},
        )


def _edges(graph: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (str(edge.get("source") or ""), str(edge.get("target") or ""))
        for edge in graph.get("edges") or []
        if isinstance(edge, dict)
    ]


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(
        (
            node
            for node in graph.get("nodes") or []
            if isinstance(node, dict) and str(node.get("id") or "") == node_id
        ),
        {},
    )


def _title(node: dict[str, Any]) -> str:
    """这个节点给人看叫什么:它自己起的名字,没有就是 id(和别处的说法一致)。"""
    return str(node.get("name") or node.get("id") or "").strip()


def _reaches(edges: list[tuple[str, str]], start: str, goal: str) -> bool:
    """从 `start` 顺着边(控制边和数据边都算)**走得到** `goal` 吗。"""
    seen = {start}
    frontier = [start]
    while frontier:
        here = frontier.pop()
        for source, target in edges:
            if source != here or target in seen:
                continue
            if target == goal:
                return True
            seen.add(target)
            frontier.append(target)
    return False


def _branch_apart(graph: dict[str, Any], a: str, b: str) -> bool:
    """`a`、`b` 是不是被**同一个会分支的节点**分到两条互斥的出口上(条件的真 / 假)。

    严格分得开才算:两个门都在某一条出口下面、或者有一个两边都够得着,都还是可能同时活。
    出口的口径和调度那一层一样 —— 没写 `source_handle` 的边按「真」算(见 engine.incoming_active)。
    """
    outgoing: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        outgoing.setdefault(str(edge.get("source") or ""), []).append(
            (str(edge.get("target") or ""), str(edge.get("source_handle") or "true"))
        )

    def below(source: str, handle: str) -> set[str]:
        """从 `source` 的这一条出口往里走,够得着哪些节点(不穿过 `source` 自己)。"""
        seen: set[str] = set()
        frontier = [target for target, one in outgoing.get(source, []) if one == handle]
        while frontier:
            here = frontier.pop()
            if here in seen or here == source:
                continue
            seen.add(here)
            frontier.extend(target for target, _one in outgoing.get(here, []))
        return seen

    for source, outs in outgoing.items():
        handles = sorted({one for _target, one in outs})
        if len(handles) < 2:
            continue
        areas = {one: below(source, one) for one in handles}
        for index, one in enumerate(handles):
            for other in handles[index + 1:]:
                if (a in areas[one] and a not in areas[other]
                        and b in areas[other] and b not in areas[one]):
                    return True
                if (b in areas[one] and b not in areas[other]
                        and a in areas[other] and a not in areas[one]):
                    return True
    return False
