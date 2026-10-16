"""工作流「等人确认」节点(`await_approval`):暂停**落库**、从暂停那一节点恢复、两条路汇到一处。

这一份测试要证的是需求里那六条,每条都留**可复查的证据**,不只看最终结果:

1. 能暂停,而且**落在库里** —— 暂停态经 `reconcile_orphaned_jobs`(重启收尾)之后仍在等,而不是被判成
   "被中断";
2. 决定下来之后**从暂停的那个节点接着跑**,而且**前面的节点没有再执行一遍**
   —— 数 `workflow.node.started` 事件 + 数它落下的真实行(这里是 Project);
3. 超时按节点配置走,而且**再通知一次**;
4. 没有飞书绑定就走站内,不报错、也不放行;
5. 飞书回调(直接调 `handle_card_action` 那一层)能落到决定上;
6. 取消仍然有效,并且把待批的那张单一起撤掉。

**故意不 mock 引擎和领域那一层**:走的是真的 `start_workflow_job`、真的线程、真的库。
只有飞书出网那一处打桩(见 `_no_network`),因为测试不该连飞书。
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from app.core.db import SessionLocal
from app.db.models import (
    FeishuBinding,
    FeishuBot,
    Job,
    Notification,
    Project,
    TaskEvent,
    Workflow,
    WorkflowRunApproval,
    now,
)
from app.domain.jobs import cancel_job, reconcile_orphaned_jobs
from app.domain.workflows import WorkflowDomainError, create_workflow
from app.domain.workflows import approvals as run_approvals
from app.domain.workflows.engine import check_runnable, start_workflow_job
from app.integrations.feishu import cards
from app.integrations.feishu.approvals import handle_card_action
from tests.util import fresh_client, user_id

OPEN_ID = "ou_the_owner"


# ---------------- 公共装置 ----------------


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _graph(
    *, on_timeout: str = "abort", on_reject: str = "abort", timeout_hours: float = 24, feishu: dict | None = None
) -> dict:
    """start → 新建项目(会留下真行,用来数它跑了几次) → 等人确认 → 文本模板。

    `feishu`:`channel` / `bot` / `to` 那三格(节点上怎么写通知方式),不填就是没写 —— 和此前存的图一样。
    """
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "make", "type": "project_create", "config": {"name": "前半程"}},
            {
                "id": "gate",
                "type": "await_approval",
                "name": "上线前确认",
                "config": {
                    "title": "要发布「前半程」吗",
                    "body": "**确认**之后接着往下走。",
                    "approve_label": "确认发布",
                    "reject_label": "先别发",
                    "allow_note": "yes",
                    "timeout_hours": timeout_hours,
                    "on_timeout": on_timeout,
                    "on_reject": on_reject,
                    **(feishu or {}),
                },
            },
            {"id": "after", "type": "template", "config": {"template": "决定:{{gate.decision}} 由 {{gate.decided_by}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "make"},
            {"id": "e2", "source": "make", "target": "gate"},
            {"id": "e3", "source": "gate", "target": "after"},
        ],
    }


def _start(graph: dict, ws: str, *, actor: str | None = None) -> tuple[str, str]:
    """建图、开跑。返回 (job_id, workflow_id)。任务在提交之后才派发。"""
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="确认", graph=graph, created_by=user_id())
        db.commit()
        job = start_workflow_job(db, db.get(Workflow, workflow.id), created_by=actor)
        db.commit()
        return job.id, workflow.id


def _wait_for(fn, *, timeout: float = 20.0, what: str = "条件"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = fn()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"等不到:{what}")


def _settled(job_id: str) -> Job | None:
    job = _job(job_id)
    return job if job.status in ("succeeded", "failed") else None


def _paused(job_id: str) -> WorkflowRunApproval:
    """等到这次运行**停在**「等人确认」上(库里那张单是 pending,而且恢复现场已经落库)。

    **要等现场**:单是节点自己一个事务先提交的(它必须比卡片先落库),检查点由引擎随后写进同一个
    事务。只等单出现的话,读到的是一份还没有现场的暂停态 —— 重启收尾那时接不回来。
    """
    settled = _wait_for(
        lambda: (lambda j: j if j.message_key == "jobMsg_awaitingApproval" else None)(_job(job_id)),
        what="这次运行停在等人确认上(任务卡说出来了)",
    )
    assert settled.status == "running", settled.error
    with SessionLocal() as db:
        row = db.query(WorkflowRunApproval).filter_by(job_id=job_id).one()
    assert row.status == "pending", row.status
    assert row.checkpoint.get("done"), "恢复现场还没落库"
    return row


def _approval(approval_id: str) -> WorkflowRunApproval:
    with SessionLocal() as db:
        return db.get(WorkflowRunApproval, approval_id)


def _route_settled(approval_id: str) -> WorkflowRunApproval:
    """等这张单把「发到哪」那三列记下来。

    **卡是在提交之后才发的**(见 domain/workflows/approvals.announce:先把暂停现场落库,再在
    after_commit 里说出去),所以「任务卡已经说出在等人确认」和「这三列已经写进库」之间有一小段
    窗口 —— 直接读会偶发地读到空串,机器负载一高就变成抽奖(整仓并行跑时实测撞上过一次)。
    和「等满两件事再断言」那几条同一个教训:断言的是**两件先后发生的事**,就得等第二件。
    """
    return _wait_for(
        lambda: (lambda row: row if row.feishu_receive_id else None)(_approval(approval_id)),
        what="这张单记下要发到哪",
    )


def _job(job_id: str) -> Job:
    with SessionLocal() as db:
        return db.get(Job, job_id)


def _projects(ws: str) -> int:
    with SessionLocal() as db:
        return db.query(Project).filter(Project.workspace_id == ws).count()


def _started(job_id: str, node_id: str) -> int:
    """这个节点被**开始执行**过几次 —— 「没有重跑前面节点」的直接证据。"""
    return _events(job_id, "workflow.node.started", node_id)


def _events(job_id: str, kind: str, node_id: str = "") -> int:
    with SessionLocal() as db:
        rows = db.query(TaskEvent).filter_by(job_id=job_id, type=kind).all()
    if not node_id:
        return len(rows)
    return sum(1 for row in rows if str((row.payload or {}).get("node_id") or "") == node_id)


def _decide(approval_id: str, decision: str, *, note: str = "") -> bool:
    """像应用内那条路一样落一个决定(提交之后才唤醒)。"""
    with SessionLocal() as db:
        won = run_approvals.decide_and_wake(
            db, db.get(WorkflowRunApproval, approval_id),
            decision=decision, user_id=user_id(), user_name="Tester", note=note, via="app",
        )
        db.commit()
        return won


def _no_network(monkeypatch) -> list:
    """飞书出网那一处打桩:记录发了什么,不发出去。其余一切都走真的。"""
    from app.integrations.feishu import client

    sent: list = []

    def send_card(bot, receive_id, card, *, receive_id_type="chat_id"):
        sent.append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "card": card})
        return f"om_card_{len(sent)}"

    monkeypatch.setattr(client, "send_card", send_card)
    return sent


def _capture(monkeypatch) -> dict[str, list]:
    """卡片和文字都记下来(降级那条路也要看得见),一条都不出网。

    `_no_network` 只挡卡片 —— 它服务的是"卡片发得出去"那几条。要证「一个字都没发」的用例
    必须把**两条**路都记下来,否则降级发出去的那段文字会真的出网,而断言还绿着。
    """
    from app.integrations.feishu import client

    seen: dict[str, list] = {"cards": [], "texts": []}

    def send_card(bot, receive_id, card, *, receive_id_type="chat_id"):
        seen["cards"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "card": card})
        return f"om_card_{len(seen['cards'])}"

    def send_text(bot, receive_id, text, *, receive_id_type="chat_id"):
        seen["texts"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "text": text})
        return f"om_text_{len(seen['texts'])}"

    monkeypatch.setattr(client, "send_card", send_card)
    monkeypatch.setattr(client, "send_text", send_text)
    return seen


# ---------------- ① 能暂停,而且落在库里(重启之后仍在等) ----------------


def test_暂停落在库里_重启收尾之后仍在等() -> None:
    ws = _workspace()
    job_id, _workflow_id = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    #: 暂停是**写进库**的,不是内存里等一个线程:标题正文、超时怎么算、现场都在那一行上。
    assert approval.status == "pending"
    assert approval.title == "要发布「前半程」吗"
    assert approval.node_name == "上线前确认"
    assert approval.on_timeout == "abort"
    assert approval.on_reject == "abort"
    assert approval.timeout_seconds == 24 * 3600
    assert approval.expires_at is not None
    #: 现场里**已经落定的**是 start 和 make —— 恢复时要跳过它们。
    assert set(approval.checkpoint["done"]) == {"start", "make"}
    assert set(approval.checkpoint["executed"]) == {"start", "make"}
    assert "make" in approval.checkpoint["context"]
    #: 任务仍是 running:它是活的,只是在等(取消它走的还是普通任务那条路)。
    assert _job(job_id).status == "running"
    assert _projects(ws) == 1

    #: **重启**:收尾会把没登记的 running 任务判成"被中断",而手里有一张待批单的必须接得回来。
    with SessionLocal() as db:
        failed = reconcile_orphaned_jobs(db)
        db.commit()
    assert failed == 0, "停在等人确认上的运行不该被判成被中断"
    reopened = _job(job_id)
    assert reopened.status == "running", reopened.error

    #: 接回来之后**重新停在同一个节点上等**,而且前面那一步没有被再跑一遍。
    #:
    #: 等的是**「门又走了一遍」这件事本身**(门自己 started 第二次、第二条 awaiting 事件),
    #: 不是那句从第一次暂停起就没变过的任务消息 —— 等那句话的话,这一条在"其实根本没接回来"
    #: 时也会绿(而它正是要证"接回来了")。
    #: 两件事**都要等**:门第二次 started 写在派发那一刻,而第二条 awaiting 事件要等门跑完、
    #: 重新停回那张单上才落库(engine 线 905 → 922 → _park_at_approval 的 emit_job_event)。
    #: 只等 started 的话,机器一忙就会在两者之间读到 1,红的是这一条而不是真没接回来。
    _wait_for(
        lambda: _started(job_id, "gate") >= 2 and _events(job_id, "workflow.awaiting_approval") >= 2,
        what="重启收尾把这次运行接回来",
    )
    assert _events(job_id, "workflow.awaiting_approval") == 2, "接回来之后要重新停在同一张单上"
    assert _projects(ws) == 1, "恢复不该重跑暂停点前面的节点"
    assert _started(job_id, "make") == 1
    same = _paused(job_id)
    assert same.id == approval.id, "重启之后认的是同一张单,不是新发一张"


# ---------------- ② 决定下来从暂停节点继续,前面不重跑 ----------------


def test_批准之后从暂停节点接着跑_前面的节点不重跑() -> None:
    ws = _workspace()
    job_id, _workflow_id = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    assert _projects(ws) == 1

    assert _decide(approval.id, "approved", note="可以") is True

    finished = _wait_for(lambda: _settled(job_id), what="批准之后这次运行接着跑完")
    assert finished.status == "succeeded", finished.error
    #: 下游拿到了决定 —— 从暂停的那个节点接着跑的产物。
    assert finished.result["context"]["after"]["text"] == "决定:approved 由 Tester"
    #: **前面的节点没有被再执行一次。** 两样证据:库里那行还是 1 个,事件里 started 只有一次。
    assert _projects(ws) == 1, "「新建项目」被重跑了一遍 —— 那是又要花一次钱的那种 bug"
    assert _started(job_id, "make") == 1
    assert _started(job_id, "gate") == 2, "门自己要走两遍:一遍停下、一遍读到决定"
    #: 单上是这次决定的全套:谁批的、什么时候、备注、从哪条路来的。
    settled = _approval(approval.id)
    assert (settled.status, settled.decision, settled.decided_by, settled.note, settled.decided_via) == (
        "approved", "approved", user_id(), "可以", "app",
    )
    assert settled.decided_at is not None


def test_拒绝也是一个决定_下游按它分支() -> None:
    """`on_reject=branch` 时 `rejected` 是**交给下游的那一格**,不是一个错误:想"拒绝了就停下",
    就在那条分支上接(默认已是 abort,所以这里显式写 branch)。"""
    ws = _workspace()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "gate", "type": "await_approval",
             "config": {"title": "发不发", "timeout_hours": 24, "on_reject": "branch"}},
            {"id": "check", "type": "condition",
             "config": {"left": "{{gate.decision}}", "op": "equals", "right": "rejected"}},
            {"id": "no", "type": "template", "config": {"template": "不发了({{gate.note}})"}},
            {"id": "yes", "type": "template", "config": {"template": "发"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "gate"},
            {"id": "e2", "source": "gate", "target": "check"},
            {"id": "e3", "source": "check", "target": "no", "source_handle": "true"},
            {"id": "e4", "source": "check", "target": "yes", "source_handle": "false"},
        ],
    }
    job_id, _ = _start(graph, ws, actor=user_id())
    approval = _paused(job_id)
    assert _decide(approval.id, "rejected", note="再改一版") is True
    finished = _wait_for(lambda: _settled(job_id), what="拒绝之后这次运行走完")
    assert finished.status == "succeeded", finished.error
    assert finished.result["context"]["no"]["text"] == "不发了(再改一版)"
    assert "yes" not in finished.result["context"], "假分支不该跑"


def test_拒绝_中止_这一次运行失败() -> None:
    """`on_reject=abort`(默认)时拒绝是一个**失败**,和超时 + abort 同一个口径:决定不交到下游。"""
    ws = _workspace()
    job_id, _ = _start(_graph(on_reject="abort"), ws, actor=user_id())
    approval = _paused(job_id)

    assert _decide(approval.id, "rejected", note="再改一版") is True

    finished = _wait_for(lambda: _settled(job_id), what="拒绝 + 中止之后这次运行停下")
    assert finished.status == "failed"
    assert finished.error_key == "wfErr_awaitApprovalRejected", finished.error
    #: 决定确实落下了(是「拒绝」),只是不交到下游 —— 下游那个节点根本没被派发。
    assert _approval(approval.id).decision == "rejected"
    assert _started(job_id, "after") == 0, "中止时决定不该交到下游"
    assert _projects(ws) == 1, "停下也不该回头重跑前面那些节点"


def test_拒绝_分支_把决定交给下游() -> None:
    """`on_reject=branch` 时拒绝是一个**决定**:下游拿到 `decision="rejected"`,这次运行照常走完。"""
    ws = _workspace()
    job_id, _ = _start(_graph(on_reject="branch"), ws, actor=user_id())
    approval = _paused(job_id)

    assert _decide(approval.id, "rejected", note="再改一版") is True

    finished = _wait_for(lambda: _settled(job_id), what="拒绝 + 分支之后这次运行走完")
    assert finished.status == "succeeded", finished.error
    assert finished.result["context"]["after"]["text"].startswith("决定:rejected")
    assert _projects(ws) == 1, "分支也不该回头重跑前面那些节点"


# ---------------- ③ 超时按配置走,而且再通知一次 ----------------


def _expire() -> None:
    """把后台那一拍要做的超时处理直接跑一遍(不真等 24 小时)。"""
    with SessionLocal() as db:
        run_approvals.expire_due(db, moment=now() + timedelta(hours=48))
        db.commit()


def _timeout_notices(ws: str) -> list[Notification]:
    with SessionLocal() as db:
        return [
            row for row in db.query(Notification).filter_by(workspace_id=ws).all()
            if row.body and "超时" in row.body
        ]


def test_超时_继续_按_timeout_往下走并再通知一次() -> None:
    ws = _workspace()
    job_id, _ = _start(_graph(on_timeout="continue"), ws, actor=user_id())
    _paused(job_id)

    _expire()

    finished = _wait_for(lambda: _settled(job_id), what="超时之后按 continue 走完")
    assert finished.status == "succeeded", finished.error
    assert finished.result["context"]["after"]["text"].startswith("决定:timeout")
    assert _projects(ws) == 1
    assert _timeout_notices(ws), "超时之后必须再通知一次,不能静默"
    with SessionLocal() as db:
        row = db.query(WorkflowRunApproval).filter_by(job_id=job_id).one()
    assert (row.status, row.decision, row.decided_via) == ("timeout", "timeout", "timeout")


def test_超时_中止_这一次运行停下来说清是超时() -> None:
    ws = _workspace()
    job_id, _ = _start(_graph(on_timeout="abort"), ws, actor=user_id())
    _paused(job_id)

    _expire()

    finished = _wait_for(lambda: _settled(job_id), what="超时之后按 abort 停下")
    assert finished.status == "failed"
    assert finished.error_key == "wfErr_awaitApprovalTimedOut", finished.error
    assert _timeout_notices(ws), "超时之后必须再通知一次,不能静默"
    assert _projects(ws) == 1, "停下也不该回头重跑前面那些节点"


def test_超时_只提醒_继续等并把下一次提醒往后推() -> None:
    ws = _workspace()
    job_id, _ = _start(_graph(on_timeout="remind"), ws, actor=user_id())
    approval = _paused(job_id)

    _expire()

    row = _approval(approval.id)
    assert row.status == "pending", "「只提醒」不落决定,还在等"
    assert row.reminded_at is not None
    assert row.expires_at > now(), "提醒过之后下一次提醒的时刻要往后推,否则每一拍都提醒一次"
    assert _timeout_notices(ws)
    assert _job(job_id).status == "running"
    assert _projects(ws) == 1


# ---------------- ④ 没有飞书就走站内(不报错、也不放行) ----------------


def test_没有飞书绑定_走站内待批且应用内能批() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    job_id, workflow_id = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    #: 没有飞书机器人时**不报错、也不放行**:通知照样有,运行照样在等。
    with SessionLocal() as db:
        notices = db.query(Notification).filter_by(workspace_id=ws, type="workflow").all()
    assert any((row.payload or {}).get("approval_id") == approval.id for row in notices)
    assert _job(job_id).status == "running"
    assert approval.feishu_bot_id == ""

    #: 应用内那两处:列表(工作区 / 这张图各一条)和决定。
    listed = client.get(f"/api/run-approvals?workspace_id={ws}")
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [approval.id]
    assert [row["id"] for row in client.get(f"/api/workflows/{workflow_id}/run-approvals").json()] == [approval.id]

    decided = client.post(f"/api/run-approvals/{approval.id}/decide", json={"decision": "approved", "note": "行"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    finished = _wait_for(lambda: _settled(job_id), what="应用内批完这次运行接着跑")
    assert finished.status == "succeeded", finished.error
    assert _projects(ws) == 1
    #: 列表里不再挂着它。
    assert client.get(f"/api/run-approvals?workspace_id={ws}").json() == []


def test_应用内批一条已经批过的单_409而不是又跑一遍() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    assert client.post(f"/api/run-approvals/{approval.id}/decide", json={"decision": "approved"}).status_code == 200
    again = client.post(f"/api/run-approvals/{approval.id}/decide", json={"decision": "rejected"})
    assert again.status_code == 409, again.text
    _wait_for(lambda: _settled(job_id), what="这次运行跑完")
    assert _projects(ws) == 1
    #: 第二次那一下**没有**把已经落下的决定改掉。
    assert _approval(approval.id).decision == "approved"


# ---------------- ⑤ 飞书那条路 ----------------


def _feishu_ready(ws: str) -> str:
    """这个工作区接一个飞书机器人,并把 tester 绑定成一个 open_id。"""
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=ws, name="助手", app_id="cli_x", app_secret="s", enabled=True)
        db.add(bot)
        db.flush()
        db.add(FeishuBinding(workspace_id=ws, open_id=OPEN_ID, user_id=user_id()))
        db.commit()
        return bot.id


def test_飞书卡片那条路_发得出去_点得回来(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _feishu_ready(ws)
    sent = _no_network(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    #: 卡片发到了这个人的私聊(这次运行不是从飞书会话来的,所以走"负责人绑过飞书"那条)。
    assert [one["to"] for one in sent] == [OPEN_ID]
    assert sent[0]["bot"] == bot_id
    assert sent[0]["type"] == "open_id"
    assert sent[0]["card"]["header"]["title"]["content"] == "要发布「前半程」吗"
    stored = _route_settled(approval.id)
    assert (stored.feishu_bot_id, stored.feishu_receive_id, stored.feishu_receive_type) == (bot_id, OPEN_ID, "open_id")

    #: 点按钮:直接调回调那一层(和 connections.dispatch 调的是同一个函数)。
    result = handle_card_action(
        OPEN_ID, {"action": cards.ACTION_RUN_APPROVE, "approval_id": approval.id, "note": "飞书批的"}
    )
    assert "toast" not in result, result
    assert result["card"]["data"]["header"]["title"]["content"] == "已确认"

    settled = _approval(approval.id)
    assert (settled.status, settled.decision, settled.decided_via, settled.note) == (
        "approved", "approved", "feishu", "飞书批的",
    )
    finished = _wait_for(lambda: _settled(job_id), what="飞书批完这次运行接着跑")
    assert finished.status == "succeeded", finished.error
    assert finished.result["context"]["after"]["text"].startswith("决定:approved")
    assert _projects(ws) == 1, "飞书那条路也不许重跑前面的节点"


def test_飞书回调_没绑定的人点不动(monkeypatch) -> None:
    ws = _workspace()
    _feishu_ready(ws)
    _no_network(monkeypatch)
    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    result = handle_card_action("ou_a_stranger", {"action": cards.ACTION_RUN_APPROVE, "approval_id": approval.id})
    assert result.get("toast", {}).get("type") == "error", result
    assert _approval(approval.id).status == "pending"
    assert _job(job_id).status == "running"


def test_飞书回调_动作名认不出就什么都不做() -> None:
    result = handle_card_action(OPEN_ID, {"action": "something.else", "approval_id": "x"})
    assert result.get("toast", {}).get("type") == "error"


# ---------------- ⑥ 取消仍然有效 ----------------


def test_取消暂停中的运行_待批单一起撤掉() -> None:
    ws = _workspace()
    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id), by=user_id())
        db.commit()

    assert _job(job_id).status == "cancelled"
    assert _approval(approval.id).status == "cancelled"
    #: 撤掉之后卡片上那一下不该还能把一次已经停下的运行叫醒。
    assert _decide(approval.id, "approved") is False
    assert _job(job_id).status == "cancelled"
    assert _projects(ws) == 1


# ---------------- ⑦ 放错地方:开跑之前就拦 ----------------


def test_循环体里的等人确认_开跑之前就被拦下() -> None:
    """体里的暂停没有地方落检查点。不拦的话症状是:前面的付费节点全跑完,轮到它才说一句接不下去。"""
    ws = _workspace()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "loop", "type": "loop_foreach",
                "config": {
                    "items": "a,b",
                    "body": {
                        "nodes": [{"id": "gate", "type": "await_approval", "config": {"title": "确认"}}],
                        "edges": [],
                    },
                },
            },
        ],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    }
    with SessionLocal() as db:
        with pytest.raises(WorkflowDomainError) as raised:
            check_runnable(db, graph, None, user_id(), workspace_id=ws)
    assert raised.value.key == "wfErr_awaitApprovalNested"
    #: 主流程里放同一个节点则照常通过 —— 拦的是位置,不是这个节点。
    with SessionLocal() as db:
        check_runnable(db, _graph(), None, user_id(), workspace_id=ws)


# ---------------- ⑧ 节点上那几个格的解析 ----------------


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 24 * 3600),
        ({"timeout_hours": 0}, None),
        ({"timeout_hours": ""}, 24 * 3600),
        ({"timeout_hours": "2"}, 2 * 3600),
        ({"timeout_hours": "不是数"}, 24 * 3600),
        ({"timeout_hours": 0.0003}, 1),
    ],
)
def test_超时小时数的解析(config: dict, expected: int | None) -> None:
    assert run_approvals.timeout_of(config) == expected


@pytest.mark.parametrize(
    ("config", "expected"),
    [({}, "abort"), ({"on_timeout": "continue"}, "continue"), ({"on_timeout": "remind"}, "remind"),
     ({"on_timeout": "乱写"}, "abort")],
)
def test_超时之后怎么办的解析(config: dict, expected: str) -> None:
    assert run_approvals.on_timeout_of(config) == expected


@pytest.mark.parametrize(
    ("config", "expected"),
    [({}, True), ({"allow_note": "no"}, False), ({"allow_note": "false"}, False), ({"allow_note": "yes"}, True)],
)
def test_备注那一格的解析(config: dict, expected: bool) -> None:
    assert run_approvals.wants_note(config) == expected


# ---------------- ⑨ 飞书那一面**显式写在节点上**(channel / bot / to) ----------------
#
# 此前"发到哪"是**自动猜**的:这次运行来自飞书会话就发回那个会话,否则看发起人绑没绑 ——
# 节点上既看不见、也改不了,更没有"就是不发飞书"这一档。现在这三格写在节点上,运行时照它走。


def _sent_to(seen: dict[str, list]) -> list[tuple[str, str, str]]:
    """发出去的那些是「(机器人, 收件 id, 收件 id 的类型)」—— 卡片和降级用的文字一起看。"""
    return [(one["bot"], one["to"], one["type"]) for one in [*seen["cards"], *seen["texts"]]]


def test_通知方式写了仅站内_一个字都不发飞书(monkeypatch) -> None:
    """`channel=none` 是**节点上明写的选择**,不是"发不出去就算了"。

    改之前这里会照旧发卡(节点上那一格根本没人读)—— 所以这条用例改之前是红的。
    """
    ws = _workspace()
    bot_id = _feishu_ready(ws)
    seen = _capture(monkeypatch)

    job_id, _ = _start(_graph(feishu={"channel": "none"}), ws, actor=user_id())
    approval = _paused(job_id)

    assert seen["cards"] == [] and seen["texts"] == [], "写了「仅站内」还发了飞书"
    #: **站内那条照旧**(仅站内 = 换一条通知的路,不是不通知):通知有、运行在等、应用内批得动。
    with SessionLocal() as db:
        notices = db.query(Notification).filter_by(workspace_id=ws, type="workflow").all()
    assert any((row.payload or {}).get("approval_id") == approval.id for row in notices)
    assert _job(job_id).status == "running"
    #: 单上那三格是空的 —— "没发飞书"这件事在记录里也是显式的。
    stored = _approval(approval.id)
    assert (stored.feishu_bot_id, stored.feishu_receive_id, stored.feishu_receive_type) == ("", "", "")
    assert bot_id, "这个用例里机器人是接着的 —— 不发飞书只能是节点上写了「仅站内」"

    assert _decide(approval.id, "approved") is True
    assert _wait_for(lambda: _settled(job_id), what="仅站内批完接着跑").status == "succeeded"


def test_通知方式写了私聊某个人_发到那个人的_open_id(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _feishu_ready(ws)
    #: 另一个人也绑了 —— 节点点名了谁,就该发给谁,不是"发给发起人"。
    someone_else = "ou_someone_else"
    with SessionLocal() as db:
        db.add(FeishuBinding(workspace_id=ws, open_id=someone_else, user_id=user_id()))
        db.commit()
    seen = _capture(monkeypatch)

    job_id, _ = _start(
        _graph(feishu={"channel": "user", "to": someone_else, "bot": bot_id}), ws, actor=user_id()
    )
    approval = _paused(job_id)

    assert _sent_to(seen) == [(bot_id, someone_else, "open_id")]
    assert _route_settled(approval.id).feishu_receive_id == someone_else


def test_通知方式写了发到某个群_发到那个群(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _feishu_ready(ws)
    seen = _capture(monkeypatch)

    job_id, _ = _start(_graph(feishu={"channel": "chat", "to": "oc_team_room"}), ws, actor=user_id())
    approval = _paused(job_id)

    assert _sent_to(seen) == [(bot_id, "oc_team_room", "chat_id")]
    stored = _route_settled(approval.id)
    assert (stored.feishu_receive_id, stored.feishu_receive_type) == ("oc_team_room", "chat_id")


def test_没绑机器人时_只站内_既不报错也不放行(monkeypatch) -> None:
    """节点点名了私聊某个人,而工作区一个机器人都没接:退回站内那条路(单照建、运行照等),
    **不是**让这次运行失败 —— 一个门禁的用处是拦住"没人看着就往下走",不是拦住自己。"""
    ws = _workspace()
    seen = _capture(monkeypatch)

    job_id, _ = _start(_graph(feishu={"channel": "user", "to": OPEN_ID}), ws, actor=user_id())
    approval = _paused(job_id)

    assert seen["cards"] == [] and seen["texts"] == []
    assert _job(job_id).status == "running"
    assert _approval(approval.id).feishu_bot_id == ""


def test_没写那三格时_行为与此前一致(monkeypatch) -> None:
    """`channel` 缺省是 `origin`:旧的图(节点上没有那三格)照旧走"哪来发回哪、否则私聊发起人"。"""
    ws = _workspace()
    _feishu_ready(ws)
    seen = _capture(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    _paused(job_id)

    assert [one["to"] for one in seen["cards"]] == [OPEN_ID]
    assert seen["cards"][0]["type"] == "open_id"


def test_节点上写了哪个机器人就用哪个(monkeypatch) -> None:
    """工作区接了不止一个机器人时,节点上那一格说得上话(改之前一律挑最早启用的那个)。"""
    ws = _workspace()
    first = _feishu_ready(ws)
    with SessionLocal() as db:
        second = FeishuBot(workspace_id=ws, name="另一个", app_id="cli_y", app_secret="s", enabled=True)
        db.add(second)
        db.commit()
        second_id = second.id
    seen = _capture(monkeypatch)

    job_id, _ = _start(_graph(feishu={"channel": "user", "to": OPEN_ID, "bot": second_id}), ws, actor=user_id())
    _paused(job_id)

    assert [one["bot"] for one in seen["cards"]] == [second_id]
    assert first != second_id
