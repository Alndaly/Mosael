"""「等人确认」的恢复现场:一次运行里有好几道门时,从**哪一张单**接着跑。

一份只读审计(2026-10-17)在这条链路上实测出三件事,这一份测试一条一条钉住它们,顺带把几处
"说得到、做不到"的缺口也钉住:

1. **多道门时从错误的检查点恢复** —— `approvals._resumable` 此前取"最早那张有检查点的单",
   而 `wake` 只排 `job_id`,`dispatch_resume` 再自己重新找一张。图 `A→门1→B→门2→C` 上批第二道门,
   于是从**第一道门**的现场恢复:门1 与门2 之间的 B 又跑了一遍(实测 Project 落 3 行而不是 2 行、
   B 起两次),而任务照样 succeeded —— 重跑被"成功"掩盖。重启那条路读的是同一个函数,同样中招。
2. **「单已落库、现场还没落」那段窗口里下的决定,运行永远醒不过来** —— 执行器自己一个事务先提交单,
   检查点由引擎在兄弟节点都落定之后才写;这段窗口里 `dispatch_resume` 找不到现场,静默什么都不做,
   任务永远停在 running。现在两头都堵:没有现场的单不列在待批列表里,引擎写完现场会复查一次。
3. **并行分支上的两个门** —— 引擎一轮只抓第一个 `AwaitingApproval`,第二个被当成兄弟节点失败:
   整轮 failed、错误文本是内部串、两张单都 `pending` + 空检查点,永远挂在待批列表上点了没反应。
   现在开跑前就拦下(和"循环体里放不下"同一个理由:前面的节点可能已经花了钱)。

另外四条缺口:应用内批了不回改飞书那张卡、重启接回还在等的运行会**再发一张卡 + 再写一条通知**
(而且旧卡从此收不回来)、`on_timeout=remind` 只提醒站内、以及提醒那一拍没有 CAS / 降级文案让人
"在飞书里回复" / 同一个等待会被两条唤醒路各派一次。

**故意不 mock 引擎和领域那一层**:真的 `start_workflow_job`、真的线程、真的库(和
tests/test_await_approval_node 同一套装置,公共部分直接从那里 import)。只有飞书出网那一处打桩。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, Notification, WorkflowRunApproval, now
from app.domain.jobs import reconcile_orphaned_jobs, wait_for_idle_jobs
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows import approvals as run_approvals
from app.domain.workflows.engine import check_runnable
from tests.test_await_approval_node import (
    OPEN_ID,
    _approval,
    _decide,
    _events,
    _expire,
    _feishu_ready,
    _graph,
    _job,
    _paused,
    _projects,
    _route_settled,
    _settled,
    _start,
    _started,
    _wait_for,
    _workspace,
)
from tests.test_run_approval_delivery import _card_fails_text_works, _delivered
from tests.util import user_id


# ---------------- 公共装置 ----------------


def _two_gates() -> dict:
    """`start → makeA → 门1 → makeB → 门2 → after`:两道门串在一条线上。

    `makeA` / `makeB` 都会在库里留下真行(Project)—— 数行数是"中间那个节点跑了几次"的直接证据。
    """
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "makeA", "type": "project_create", "config": {"name": "A"}},
            {"id": "gate1", "type": "await_approval", "name": "第一道门",
             "config": {"title": "门一", "timeout_hours": 24, "on_timeout": "abort", "on_reject": "abort"}},
            {"id": "makeB", "type": "project_create", "config": {"name": "B"}},
            {"id": "gate2", "type": "await_approval", "name": "第二道门",
             "config": {"title": "门二", "timeout_hours": 24, "on_timeout": "abort", "on_reject": "abort"}},
            {"id": "after", "type": "template", "config": {"template": "决定:{{gate2.decision}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "makeA"},
            {"id": "e2", "source": "makeA", "target": "gate1"},
            {"id": "e3", "source": "gate1", "target": "makeB"},
            {"id": "e4", "source": "makeB", "target": "gate2"},
            {"id": "e5", "source": "gate2", "target": "after"},
        ],
    }


def _gate_window() -> dict:
    """门与一个慢节点并行:门先把单提交,慢节点还飞着 —— 这正是"单已落库、现场还没落"那段窗口。"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "gate", "type": "await_approval", "name": "门",
             "config": {"title": "等你确认", "timeout_hours": 24, "on_timeout": "abort"}},
            {"id": "slow", "type": "delay", "config": {"seconds": 3}},
            {"id": "after", "type": "template", "config": {"template": "决定:{{gate.decision}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "gate"},
            {"id": "e2", "source": "start", "target": "slow"},
            {"id": "e3", "source": "gate", "target": "after"},
        ],
    }


def _parallel_gates() -> dict:
    """两个门挂在**同一个 start 底下的两条分支**上:互相不可达,可以同时被调度。"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "gateA", "type": "await_approval", "name": "A门", "config": {"title": "A", "timeout_hours": 24}},
            {"id": "gateB", "type": "await_approval", "name": "B门", "config": {"title": "B", "timeout_hours": 24}},
            {"id": "ta", "type": "template", "config": {"template": "A:{{gateA.decision}}"}},
            {"id": "tb", "type": "template", "config": {"template": "B:{{gateB.decision}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "gateA"},
            {"id": "e2", "source": "start", "target": "gateB"},
            {"id": "e3", "source": "gateA", "target": "ta"},
            {"id": "e4", "source": "gateB", "target": "tb"},
        ],
    }


def _exclusive_gates() -> dict:
    """条件节点的真 / 假两条出口上各一个门:**永远不会同时活**,这种图今天跑得起来。

    这条是那条新检查的**反例**:拦的必须是"会同时跑到",不是"互相不可达"。
    """
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "check", "type": "condition", "config": {"left": "a", "op": "not_empty"}},
            {"id": "gateA", "type": "await_approval", "name": "A门", "config": {"title": "A", "timeout_hours": 24}},
            {"id": "gateB", "type": "await_approval", "name": "B门", "config": {"title": "B", "timeout_hours": 24}},
            {"id": "ta", "type": "template", "config": {"template": "A:{{gateA.decision}}"}},
            {"id": "tb", "type": "template", "config": {"template": "B:{{gateB.decision}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "check"},
            {"id": "e2", "source": "check", "target": "gateA", "source_handle": "true"},
            {"id": "e3", "source": "check", "target": "gateB", "source_handle": "false"},
            {"id": "e4", "source": "gateA", "target": "ta"},
            {"id": "e5", "source": "gateB", "target": "tb"},
        ],
    }


def _gate_id(job_id: str, node_id: str) -> str:
    """等**这一个节点**那张单把现场落好,交回单 id。

    只等"单存在"是不够的:单是执行器自己一个事务先提交的,现场随后才写(见 domain/workflows/approvals)。
    """

    def look():
        with SessionLocal() as db:
            row = db.query(WorkflowRunApproval).filter_by(job_id=job_id, node_id=node_id).one_or_none()
            return row.id if row is not None and row.checkpoint else None

    return _wait_for(look, what=f"{node_id} 这一张单落好现场")


def _not_ready_yet(job_id: str) -> str:
    """等**那张单已经在库里、检查点还是空的**那一段窗口(②要的正是它)。"""

    def look():
        with SessionLocal() as db:
            row = db.query(WorkflowRunApproval).filter_by(job_id=job_id).one_or_none()
            return row.id if row is not None and not row.checkpoint else None

    return _wait_for(look, what="单已落库、现场还没写的那段窗口")


def _notice_count(ws: str, approval_id: str) -> int:
    """这张单相关的站内通知有几条(靠 payload 里的 approval_id 认)。"""
    with SessionLocal() as db:
        return sum(
            1
            for row in db.query(Notification).filter_by(workspace_id=ws).all()
            if (row.payload or {}).get("approval_id") == approval_id
        )


def _notices(ws: str) -> int:
    with SessionLocal() as db:
        return db.query(Notification).filter_by(workspace_id=ws).count()


def _announced(approval_id: str) -> WorkflowRunApproval:
    """等这张单把「说出去」整笔落库(站内通知 + 飞书投递结果在**同一次提交**里写下去)。

    **不在 `_paused` 回来之后直接数通知。** `_paused` 等的是任务卡上的 `messageKey`;而「还在等你
    确认」那条站内通知与投递结果排在暂停现场提交之后(`engine._park_at_approval` 的
    `after_commit` → `announce_parked`)。这两件事之间有窗口:基线赶在它前面时,后来那条**本来就该说**
    的通知会被当成「多喊了一条」—— CI 上三次红的这一条实测就是 `1 != 0`,而 `reminded_at` 是 `None`、
    那条通知的正文正是暂停时那句「等你确认」(不是提醒那一拍写的)。等 `feishu_delivery` 非空:它和
    站内通知在同一个事务里,非空就是整笔说完了。
    """
    return _wait_for(
        lambda: next((row for row in [_approval(approval_id)] if row.feishu_delivery), None),
        what="这张单的暂停通知和投递结果都落库",
    )


def _awaiting(job_id: str) -> int:
    return _events(job_id, "workflow.awaiting_approval")


def _feishu_wire(monkeypatch) -> dict[str, list]:
    """飞书出网那一处:卡片 / 文字 / 就地改写各记一份,一条都不发出去。"""
    from app.integrations.feishu import client

    seen: dict[str, list] = {"cards": [], "texts": [], "updates": []}

    def send_card(bot, receive_id, card, *, receive_id_type="chat_id"):
        seen["cards"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "card": card})
        return f"om_card_{len(seen['cards'])}"

    def send_text(bot, receive_id, text, *, receive_id_type="chat_id"):
        seen["texts"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "text": text})
        return f"om_text_{len(seen['texts'])}"

    def update_card(bot, message_id, card):
        seen["updates"].append({"bot": bot.id, "message_id": message_id, "card": card})

    monkeypatch.setattr(client, "send_card", send_card, raising=False)
    monkeypatch.setattr(client, "send_text", send_text, raising=False)
    monkeypatch.setattr(client, "update_card", update_card, raising=False)
    return seen


# ---------------- ① 两道门:从**指定的那一张**的现场接着跑 ----------------


def test_批第二道门时从第二道门的现场恢复_中间那个节点不重跑() -> None:
    """审计的断言:Project == 2 / makeB 起 1 次 / gate1 起 2 次。

    `gate1` 起 2 次是**对的**:第一次真的执行到它,第二次是恢复之后走到它、就地领走那个决定
    (它不在第一张检查点的 `done` 里)。跑一次不该发生的是 `makeB` —— 它落在两道门之间。
    """
    ws = _workspace()
    job_id, _ = _start(_two_gates(), ws, actor=user_id())

    first = _gate_id(job_id, "gate1")
    assert _decide(first, "approved") is True

    second = _gate_id(job_id, "gate2")
    assert _started(job_id, "makeB") == 1, "停在第二道门时,中间那个节点只该跑过一次"
    assert _projects(ws) == 2

    assert _decide(second, "approved") is True
    finished = _wait_for(lambda: _settled(job_id), what="第二道门批完这次运行跑完")
    assert finished.status == "succeeded", finished.error
    assert finished.result["context"]["after"]["text"] == "决定:approved"
    #: **重跑的证据在这里**:这三条此前是 3 / 2 / 3(而任务照样 succeeded)。
    assert _projects(ws) == 2, "两道门之间那个节点被重跑了(Project 多了一行)"
    assert _started(job_id, "makeB") == 1, "两道门之间那个节点被重跑了"
    assert _started(job_id, "gate1") == 2


def test_重启接回第二道门上的运行_也从第二道门的现场接着跑() -> None:
    """重启那条路读的是同一个函数(`_resumable` 不带 id → **最新**那一张)。

    此前它取"最早那张有检查点的" —— 重启接回来会从门1 的现场重跑门1、makeB、门2。
    """
    ws = _workspace()
    job_id, _ = _start(_two_gates(), ws, actor=user_id())

    first = _gate_id(job_id, "gate1")
    assert _decide(first, "approved") is True
    second = _gate_id(job_id, "gate2")
    parked = _awaiting(job_id)

    with SessionLocal() as db:
        reconcile_orphaned_jobs(db)
        db.commit()

    _wait_for(lambda: _awaiting(job_id) > parked, what="重启之后重新停在门上")
    #: 等**那条恢复线程收尾**(不是睡一下):它的 after_commit 都做完了才停,之后数的才是全部。
    assert wait_for_idle_jobs(timeout=30), "重启接回的那条运行线程没停下来"
    assert _started(job_id, "makeB") == 1, "重启接回时从上一道门的现场重跑了中间那个节点"
    assert _projects(ws) == 2
    assert _job(job_id).status == "running", "接回来仍在等,不是被判成中断"

    #: 接回来之后决定照样落得下去、运行照样跑得完。
    assert _decide(second, "approved") is True
    finished = _wait_for(lambda: _settled(job_id), what="重启接回之后跑完")
    assert finished.status == "succeeded", finished.error
    assert _projects(ws) == 2


# ---------------- ② 「单已落库、现场还没落」那段窗口 ----------------


def test_窗口里下的决定_运行照样醒得来_而且这段窗口里不列这张单() -> None:
    """窗口里的决定赢了 CAS 却恢复不了(现场是空的)—— 运行永远停在 running 上。

    现在:这段窗口里这张单**不列在待批列表里**(没有任何人该在这时点它),而真的有人从别的路
    落了决定时,引擎写完现场会**复查**一次、自己把这次恢复排出去。
    """
    ws = _workspace()
    job_id, _ = _start(_gate_window(), ws, actor=user_id())

    early = _not_ready_yet(job_id)
    #: (a) 现场还没落:列表里不列它 —— 5 秒一轮的前端在这里根本没有可点的按钮。
    with SessionLocal() as db:
        assert run_approvals.pending_for_workspace(db, ws) == []
        assert run_approvals.pending_for_job(db, job_id) is None
    with SessionLocal() as db:
        assert db.get(WorkflowRunApproval, early).checkpoint == {}

    #: (b) 这段窗口里决定真的落了(飞书旧卡 / 直接调接口都走 `decide`):运行必须醒得来。
    assert _decide(early, "approved") is True

    finished = _wait_for(lambda: _settled(job_id), what="窗口里决定之后运行自己醒过来")
    assert finished.status == "succeeded", finished.error
    assert finished.result["context"]["after"]["text"] == "决定:approved"
    assert _approval(early).status == "approved"
    #: 已经决定过了就别再喊人来等:这张单一条"在等人确认"的站内通知都不该有。
    assert _notice_count(ws, early) == 0


# ---------------- ③ 并行分支上的两个门:开跑之前拦下 ----------------


def test_并行分支上的两个门_开跑之前就被拦下而且一分钱没花() -> None:
    ws = _workspace()
    with SessionLocal() as db:
        with pytest.raises(WorkflowDomainError) as raised:
            check_runnable(db, _parallel_gates(), None, user_id(), workspace_id=ws)
    assert raised.value.key == "wfErr_awaitApprovalParallel"
    #: 说清是哪两个节点 —— 报错里要有人看得懂的那两个名字,不是一串 id。
    said = str(raised.value)
    assert "A门" in said and "B门" in said

    #: 拦在建任务之前:没有任务、没有单、没有任何节点跑过 —— 前面的付费节点一次都没跑。
    with SessionLocal() as db:
        assert db.query(WorkflowRunApproval).count() == 0
        assert db.query(Job).filter_by(kind="workflow").count() == 0
    assert _projects(ws) == 0


def test_条件两条出口上的两个门_不算并发_照旧放行() -> None:
    """反例:那两个门永远不会同时活(调度按出口跳过没走到的那一支),不该被这条检查误拦。"""
    ws = _workspace()
    with SessionLocal() as db:
        check_runnable(db, _exclusive_gates(), None, user_id(), workspace_id=ws)


# ---------------- ④ 应用内做的决定:飞书那张卡也跟着变成结果态 ----------------


def test_应用内批了_飞书那张卡也换成结果态(monkeypatch) -> None:
    """在应用里批的那一下,群里那张卡如果还留着两个按钮,别人会以为这件事还欠着。"""
    ws = _workspace()
    _feishu_ready(ws)
    seen = _feishu_wire(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    stored = _route_settled(approval.id)
    assert len(seen["cards"]) == 1

    assert _decide(approval.id, "approved") is True

    _wait_for(lambda: seen["updates"] or None, what="飞书那张卡被换成结果态")
    update = seen["updates"][0]
    assert update["message_id"] == stored.feishu_message_id, "收的必须是原来发出去那条消息"
    assert update["card"]["header"]["title"]["content"] == "已确认"
    #: 收回是**提交之后**尽力做的一步:那次运行照常接着跑。
    finished = _wait_for(lambda: _settled(job_id), what="应用内批完这次运行接着跑")
    assert finished.status == "succeeded", finished.error


def test_飞书那条路点的不重复收一次卡(monkeypatch) -> None:
    """`via == "feishu"` 时跳过:回调响应本身就把那张卡换掉了,再收一次是多余的。"""
    from app.integrations.feishu import cards
    from app.integrations.feishu.approvals import handle_card_action

    ws = _workspace()
    _feishu_ready(ws)
    seen = _feishu_wire(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    _route_settled(approval.id)

    result = handle_card_action(OPEN_ID, {"action": cards.ACTION_RUN_APPROVE, "approval_id": approval.id})
    assert "toast" not in result, result
    _wait_for(lambda: _settled(job_id), what="飞书批完这次运行跑完")
    assert seen["updates"] == [], "飞书那条路的回应已经换过卡了,不该再收一次"


# ---------------- ⑤ 重启接回还在等的运行:卡片和通知都不重发 ----------------


def test_重启接回还在等的运行_不再发第二张卡也不覆盖最早那条消息id(monkeypatch) -> None:
    ws = _workspace()
    _feishu_ready(ws)
    seen = _feishu_wire(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    stored = _route_settled(approval.id)
    assert len(seen["cards"]) == 1
    assert stored.feishu_message_id
    first_notices = _notice_count(ws, approval.id)
    assert first_notices >= 1

    with SessionLocal() as db:
        reconcile_orphaned_jobs(db)
        db.commit()

    _wait_for(lambda: _awaiting(job_id) >= 2, what="重启之后接回来重新停在同一张单上")
    #: 等**那条恢复线程收尾**:发第二张卡这一步排在它的 after_commit 上,线程都结束了才数得准。
    assert wait_for_idle_jobs(timeout=30), "重启接回的那条运行线程没停下来"
    assert len(seen["cards"]) == 1, "重启接回来又发了一张卡:群里两张,而旧的那张从此收不回来"
    assert _notice_count(ws, approval.id) == first_notices, "重启接回来又写了一遍站内通知"
    #: 最早那条消息的 id **不被覆盖** —— 取消 / 超时照它去收群里那张卡。
    assert _approval(approval.id).feishu_message_id == stored.feishu_message_id
    assert _approval(approval.id).status == "pending", "还在等,不是被撤销了"


# ---------------- ⑥ on_timeout=remind:飞书那边也说一声 ----------------


def test_超时只提醒_飞书那边也说一声而卡上的按钮还在(monkeypatch) -> None:
    """ADR 0064 的原话是"三种都会再通知一次 —— 一个门禁悄悄过期等于没装"。

    `remind` 不是结果态:那张卡**不换掉**(门还开着,按钮还得点得动),只在同一个会话里补一句。
    """
    ws = _workspace()
    _feishu_ready(ws)
    seen = _feishu_wire(monkeypatch)

    job_id, _ = _start(_graph(on_timeout="remind"), ws, actor=user_id())
    approval = _paused(job_id)
    _route_settled(approval.id)
    assert len(seen["cards"]) == 1

    _expire()

    _wait_for(lambda: seen["texts"] or None, what="飞书那边也收到一句提醒")
    assert seen["texts"][0]["to"] == OPEN_ID
    assert "还在等你确认" in seen["texts"][0]["text"]
    assert seen["updates"] == [], "提醒不是结果态:那张卡还得点得动"
    row = _approval(approval.id)
    assert row.status == "pending", "「只提醒」不落决定"
    assert row.reminded_at is not None
    assert _notice_count(ws, approval.id) >= 2, "站内那条提醒也照旧"


def test_没发到飞书过的单_提醒时什么都不发(monkeypatch) -> None:
    """写了「仅站内」的单(`feishu_message_id` 为空)提醒时跳过,不该为此报错。"""
    ws = _workspace()
    seen = _feishu_wire(monkeypatch)

    job_id, _ = _start(_graph(on_timeout="remind", feishu={"channel": "none"}), ws, actor=user_id())
    approval = _paused(job_id)

    _expire()

    _wait_for(lambda: _approval(approval.id).reminded_at, what="站内那条提醒落库")
    #: 提醒那一步排在**提交之后的同一个线程里**(`after_commit`),`_expire` 回来时它已经做完了 ——
    #: 不用等时间:这条路上一句话都发不出去(没有消息 id 可改)。
    assert seen["texts"] == [] and seen["updates"] == []
    assert _approval(approval.id).status == "pending"


# ---------------- ⑦ 顺手那几处 ----------------


def test_提醒那一拍与人的决定撞上_不写回提醒也不多喊一条(monkeypatch) -> None:
    """人到点前一刻批了、后台这一拍在同一瞬间把"还在等"喊出去 —— 那条通知和外层那个决定自相矛盾。

    这一条把那个毫秒级窗口**做成确定的**:后台那一拍**读完到点的行之后**才让另一个会话把决定提交
    下去(pysqlite 的读是自动提交的快照,所以提交得进去),这一拍接着写时看到的就是新状态。
    提醒走 `UPDATE … WHERE status='pending'`:这时它什么都写不进去。

    **基线要等暂停那条通知说完**(见 `_announced`):这一条断言的是"这一拍**不要再多说一句**",
    前提是"该说的那一句已经说完了"。不等的话,那条「还在等你确认」会随机落在基线之后,把这条
    测试变成抽奖(CI 上三次红,红的是这里的 `1 != 0`,不是产品多写了提醒)。
    """
    from sqlalchemy.orm import Session as OrmSession

    ws = _workspace()
    job_id, _ = _start(_graph(on_timeout="remind"), ws, actor=user_id())
    approval = _paused(job_id)
    _announced(approval.id)
    before = _notices(ws)
    assert _notice_count(ws, approval.id) == before, "工作区里只有这一张单,基线里不该有别的"

    real = OrmSession.scalars
    landed: list[str] = []

    def read_then_let_a_person_decide(self, statement, *args, **kwargs):
        rows = list(real(self, statement, *args, **kwargs))
        if not landed:
            landed.append(approval.id)
            with SessionLocal() as other:
                won = run_approvals.decide(
                    other, other.get(WorkflowRunApproval, approval.id),
                    decision="approved", user_id=user_id(), user_name="T", via="app",
                )
                other.commit()
            assert won is True, "这一条里那个决定必须真的落下去"
        return rows

    monkeypatch.setattr(OrmSession, "scalars", read_then_let_a_person_decide)
    with SessionLocal() as db:
        handled = run_approvals.expire_due(db, moment=now() + timedelta(hours=48))
        db.commit()

    assert landed, "这一拍根本没读到行,这条测的就不是那个窗口"
    assert handled == 0, "已经决定了的那张单不该被这一拍算成「提醒过了」"
    row = _approval(approval.id)
    assert (row.status, row.decision) == ("approved", "approved")
    assert row.reminded_at is None, "已经决定了的那张单不该被写回提醒的时刻"
    assert _notices(ws) == before, "多了一条自相矛盾的「还在等」"


def test_降级那段文字不让用户去飞书里回复(monkeypatch) -> None:
    """全仓没有任何一条路把飞书里的**回复**变成决定(只有卡片上的按钮是),那句话把人支去空处。"""
    ws = _workspace()
    _feishu_ready(ws)
    seen = _card_fails_text_works(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    _delivered(approval.id, "sent")

    assert seen["texts"], "卡片发不出去时那段降级文字"
    text = seen["texts"][0]["text"]
    assert "请到 Mosael 里处理" in text
    assert "飞书里回复" not in text


def test_同一个等待不会被第二条唤醒路再派一遍(monkeypatch) -> None:
    """两条唤醒路(人的决定 / 重启 resumer)撞上时,第二次派发退回去。

    派出去就是同一张图在两条线程里各跑一遍 —— 检查点只记得住上次落定的节点,后面那些会重跑
    (实测:下游节点建了两行、按次计费的那一步付两次)。
    """
    ws = _workspace()
    _feishu_wire(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    assert _decide(approval.id, "approved") is True
    #: 人的决定那一条路已经派过了(唤醒排在提交之后);紧接着的第二条唤醒路不该再派一次。
    assert run_approvals.dispatch_resume(job_id) is False

    finished = _wait_for(lambda: _settled(job_id), what="这一轮收场")
    assert finished.status == "succeeded", finished.error
    assert _projects(ws) == 1, "同一个等待被派了两遍,前面的节点重跑了"
