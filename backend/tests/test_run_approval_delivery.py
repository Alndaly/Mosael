"""「等人确认」到底发到飞书没有:投递结果落在单上、发不出去时站内再喊一声、取消 / 超时把那张卡收回。

改之前有两处缺口,各自都只进日志、看不见:

1. **传输失败**(卡片和降级那段文字都没发出去:断网、机器人没权限)只在日志里。单上看不出"到底
   发到飞书没有",群里也没有任何东西 —— 用户在群里等一张**永远不会来的卡**,而站内那条通知
   说的是"在飞书里点卡片,或在应用里点都可以"。所以这里要:记下投递结果(`sent` / `failed` /
   `not_attempted`)、发失败时**再写一条站内通知**(说清只能在站内批、带上那张单的 id);
2. **取消 / 超时之后**,飞书群里那张卡留在原地**还可点**(点了报错),别人不知道这件事已经结束。
   所以这里要:发出去过就把那条消息就地换成结果态;没发出去过就跳过;更新失败只记日志,
   **不许把取消本身弄失败**。

只有飞书出网那一处打桩(见 tests/test_await_approval_node 的 `_capture`),其余全走真的:
真的引擎、真的库、真的取消链路。

「仅站内」(`channel=none`)是**用户明说的选择**,记成 `not_attempted` 而不是 `failed` ——
把用户的选择说成失败,下一步就是有人给它加"重试"。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Job, Notification, WorkflowRunApproval
from app.domain.jobs import cancel_job
from tests.test_await_approval_node import (
    OPEN_ID,
    _approval,
    _capture,
    _expire,
    _feishu_ready,
    _graph,
    _job,
    _no_network,
    _paused,
    _start,
    _wait_for,
    _workspace,
)
from tests.util import fresh_client, user_id


# ---------------- 公共装置 ----------------


def _delivered(approval_id: str, want: str = "") -> WorkflowRunApproval:
    """等这张单把投递结果写下来。

    **发卡在提交之后**(见 domain/workflows/approvals.announce),所以「这张单已经在」和
    「投递结果已经写进库」之间有一小段窗口 —— 直接读会偶发读空(和 tests/test_await_approval_node
    的 `_route_settled` 同一个教训:断言的是两件先后发生的事,就得等第二件)。
    """
    def look():
        row = _approval(approval_id)
        if not row.feishu_delivery:
            return None
        return row if not want or row.feishu_delivery == want else None

    return _wait_for(look, what="这张单记下投递结果")


def _undelivered_notices(workspace_id: str, approval_id: str) -> list[Notification]:
    """「这次没能发到飞书」那一条站内通知(和「在等人确认」那条并存,靠 payload 认出来)。"""
    with SessionLocal() as db:
        rows = list(db.scalars(select(Notification).where(Notification.workspace_id == workspace_id)))
    return [
        row
        for row in rows
        if (row.payload or {}).get("approval_id") == approval_id
        and (row.payload or {}).get("delivery") == "failed"
    ]


def _card_fails_text_works(monkeypatch) -> dict[str, list]:
    """卡片发不出去(开发者后台没开交互卡片),降级那段文字发得出去 —— 这算**发到了**。"""
    from app.integrations.feishu import client

    seen: dict[str, list] = {"cards": [], "texts": []}

    def send_card(bot, receive_id, card, *, receive_id_type="chat_id"):
        seen["cards"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "card": card})
        raise client.FeishuError("feishuErr_sendCard", detail="200340")

    def send_text(bot, receive_id, text, *, receive_id_type="chat_id"):
        seen["texts"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "text": text})
        return "om_text_1"

    monkeypatch.setattr(client, "send_card", send_card)
    monkeypatch.setattr(client, "send_text", send_text)
    return seen


def _nothing_gets_out(monkeypatch) -> None:
    """断网那种:卡片和降级那段文字**都**发不出去。"""
    from app.integrations.feishu import client

    def send_card(bot, receive_id, card, *, receive_id_type="chat_id"):
        raise client.FeishuError("feishuErr_sendCard", detail="connection reset")

    def send_text(bot, receive_id, text, *, receive_id_type="chat_id"):
        raise client.FeishuError("feishuErr_sendText", detail="connection reset")

    monkeypatch.setattr(client, "send_card", send_card)
    monkeypatch.setattr(client, "send_text", send_text)


def _updates(monkeypatch, *, fail: bool = False) -> list:
    """记下「把那张卡收回成结果态」的每一次调用;`fail` 时这一步失败(要证它不影响取消)。"""
    from app.integrations.feishu import client

    seen: list = []

    def update_card(bot, message_id, card):
        seen.append({"bot": bot.id, "message_id": message_id, "card": card})
        if fail:
            raise client.FeishuError("feishuErr_sendCard", detail="200340")

    #: raising=False:这条测的是「有没有人调它」。实现还没到位时(先红后绿里那个"红"),
    #: 红在下面那条断言上,而不是 monkeypatch 自己抛 AttributeError —— 同一个道理适用于 `send_text`。
    monkeypatch.setattr(client, "update_card", update_card, raising=False)

    def send_text(bot, receive_id, text, *, receive_id_type="chat_id"):
        if fail:
            raise client.FeishuError("feishuErr_sendText", detail="connection reset")
        return "om_text_after"

    monkeypatch.setattr(client, "send_text", send_text, raising=False)
    return seen


def _cancel(job_id: str) -> None:
    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id), by=user_id())
        db.commit()


# ---------------- ① 发到了(卡片失败退成文字也算) ----------------


def test_卡片失败退成文字_记成发到了(monkeypatch) -> None:
    """两层降级里的第二层成了就算 `sent` —— 飞书里的人确实收到了东西,用户按原因看的是"没发出去"。"""
    ws = _workspace()
    _feishu_ready(ws)
    seen = _card_fails_text_works(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    row = _delivered(approval.id, "sent")
    assert seen["cards"], "卡片那一次该试过"
    assert len(seen["texts"]) == 1, "卡片失败之后该退成文字"
    #: 记的是**真正送出去的那条消息**的 id(文字那条),不是没发成的卡片。
    assert row.feishu_message_id == "om_text_1"
    assert _undelivered_notices(ws, approval.id) == [], "发到了就不该再喊一声「没发出去」"


# ---------------- ② 一个字都没发出去:记 failed + 站内再喊一声 ----------------


def test_卡片和文字都失败_单上记下原因并在站内再喊一声(monkeypatch) -> None:
    """改之前这条是红的:投递失败只进日志,单上没有痕迹,站内也没有第二条。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _feishu_ready(ws)
    _nothing_gets_out(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)

    row = _delivered(approval.id, "failed")
    assert row.feishu_message_id == "", "没发出去就不该有消息 id(取消时照它跳过)"
    assert row.feishu_delivery_reason, "失败了要说清是什么失败了"

    #: 除了「在等人确认」那条,再多一条:这次没能发到飞书,只能在站内批 —— 带上那张单的 id。
    notices = _undelivered_notices(ws, approval.id)
    assert len(notices) == 1, [one.body for one in notices]
    assert approval.id in notices[0].body

    #: 应用内那张卡读得到同一件事(接口把它交出去,界面照它显示那一句)。
    listed = client.get(f"/api/run-approvals?workspace_id={ws}")
    assert listed.status_code == 200, listed.text
    [shown] = listed.json()
    assert shown["feishu_delivery"] == "failed"
    assert shown["feishu_delivery_reason"] == row.feishu_delivery_reason

    #: 发不出去**不许**影响这次运行:照旧在等,应用内照旧批得动。
    assert _job(job_id).status == "running"


# ---------------- ③ 路由那一层就没打算发:不是失败 ----------------


def test_仅站内_记成没试过而不是失败(monkeypatch) -> None:
    """`channel=none` 是节点上明写的选择。记 `not_attempted` + 原因,绝不记成失败。"""
    ws = _workspace()
    _feishu_ready(ws)
    seen = _capture(monkeypatch)

    job_id, _ = _start(_graph(feishu={"channel": "none"}), ws, actor=user_id())
    approval = _paused(job_id)

    row = _delivered(approval.id, "not_attempted")
    assert row.feishu_delivery_reason == "none", "原因是节点上那一档(见 domain/feishu/routing)"
    assert seen["cards"] == [] and seen["texts"] == []
    assert _undelivered_notices(ws, approval.id) == [], "用户自己选的「仅站内」不是失败"


def test_没有机器人可发_也记成没试过而不是失败(monkeypatch) -> None:
    """同上:`no-bot` 是"这次没有可发的去处",不是"发出去失败了"。"""
    ws = _workspace()
    _capture(monkeypatch)

    job_id, _ = _start(_graph(feishu={"channel": "user", "to": OPEN_ID}), ws, actor=user_id())
    approval = _paused(job_id)

    row = _delivered(approval.id, "not_attempted")
    assert row.feishu_delivery_reason == "no-bot"
    assert _job(job_id).status == "running"


# ---------------- ④ 取消 / 超时:把飞书那张卡收回 ----------------


def test_取消之后_飞书那张卡被收回成已取消(monkeypatch) -> None:
    """改之前这条是红的:单被撤了,而群里那张卡还留在原地、还点得动。"""
    ws = _workspace()
    bot_id = _feishu_ready(ws)
    _no_network(monkeypatch)
    updates = _updates(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    sent = _delivered(approval.id, "sent")
    assert sent.feishu_message_id == "om_card_1", "发出去那张卡的 id 要记下来"

    _cancel(job_id)

    assert _job(job_id).status == "cancelled"
    assert len(updates) == 1, "取消时该把那张卡收回,而不是留一张死卡"
    assert updates[0]["bot"] == bot_id
    assert updates[0]["message_id"] == "om_card_1", "收回的是**发出去的那一条**"
    assert updates[0]["card"]["header"]["title"]["content"] == "已取消"
    assert _approval(approval.id).status == "cancelled"


def test_超时之后_飞书那张卡被收回成超时(monkeypatch) -> None:
    ws = _workspace()
    _feishu_ready(ws)
    _no_network(monkeypatch)
    updates = _updates(monkeypatch)

    job_id, _ = _start(_graph(on_timeout="abort"), ws, actor=user_id())
    approval = _paused(job_id)
    _delivered(approval.id, "sent")

    _expire()

    assert _approval(approval.id).status == "timeout"
    assert len(updates) == 1, "超时之后那张卡也该收回"
    assert updates[0]["card"]["header"]["title"]["content"] == "超时"
    _wait_for(lambda: _job(job_id).status == "failed", what="超时 + abort 之后这次运行停下")


# ---------------- ⑤ 收回那一步失败 **不许**影响取消 ----------------


def test_收回卡片失败_取消照样成立(monkeypatch) -> None:
    """顺序上先落库、后尽力通知:库里已经是取消,"把卡换掉"那一步炸了也只是日志。"""
    ws = _workspace()
    _feishu_ready(ws)
    _no_network(monkeypatch)
    updates = _updates(monkeypatch, fail=True)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    _delivered(approval.id, "sent")

    _cancel(job_id)  # 这一步不许抛

    assert _job(job_id).status == "cancelled"
    assert _approval(approval.id).status == "cancelled"
    assert len(updates) == 1, "「试过但失败」与「根本没试」要分得开"
    #: 卡换不掉、补的那条文字也发不出去 —— 结果不变。
    assert _approval(approval.id).decided_via == "cancel"


# ---------------- ⑥ 没发出去过就跳过 ----------------


def test_没发出去过_取消时不碰飞书也不报错(monkeypatch) -> None:
    """写了「仅站内」的单上没有消息 id:收回这一步直接跳过,不该去调飞书、更不该报错。"""
    ws = _workspace()
    _feishu_ready(ws)
    _capture(monkeypatch)
    updates = _updates(monkeypatch)

    job_id, _ = _start(_graph(feishu={"channel": "none"}), ws, actor=user_id())
    approval = _paused(job_id)
    row = _delivered(approval.id, "not_attempted")
    assert row.feishu_message_id == ""

    _cancel(job_id)

    assert updates == [], "没发出去过就没有卡可收回"
    assert _job(job_id).status == "cancelled"
    assert _approval(approval.id).status == "cancelled"


def test_没接飞书那套_取消时也不报错(monkeypatch) -> None:
    """整条飞书那一半没装上(组装根没登记实现):取消照旧,一步都不该碰飞书。"""
    #: 没有机器人、也没有绑定 —— 路由那一层就解不出来。
    ws = _workspace()
    _capture(monkeypatch)
    updates = _updates(monkeypatch)

    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    row = _delivered(approval.id, "not_attempted")
    assert row.feishu_message_id == ""

    _cancel(job_id)

    assert updates == []
    assert _job(job_id).status == "cancelled"


def test_没有待批单的取消_什么也不做() -> None:
    """这张单早就不是 pending 了(另一个入口先撤的):同一条路第二遍走也不该出事。"""
    ws = _workspace()
    job_id, _ = _start(_graph(), ws, actor=user_id())
    approval = _paused(job_id)
    _cancel(job_id)

    with SessionLocal() as db:
        row = db.get(WorkflowRunApproval, approval.id)
    assert row.status == "cancelled"
