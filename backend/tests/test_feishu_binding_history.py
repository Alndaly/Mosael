"""「谁曾绑过」落在审计表(`activity_events`):解绑、删机器人各记一条 `feishu.binding.removed`。

`feishu_bindings` 是**活跃**表:机器人一删,`bot_id` 上的 `ON DELETE CASCADE` 把它名下的行一起带走
(那台应用眼里的 open_id 之后没有任何东西解释得了)。而"这个人以前绑过这台"是**历史** ——
它落在只增不改的事件表里,机器人那一行没了也照样在(`subject_id` 只是一段字符串,不是外键)。

这里钉三件事:

1. 显式解绑记一条;
2. 删机器人给它名下**每条**绑定各记一条(不是汇总成一条、也不是漏记),而且是在级联删掉它们之前记的;
3. 认人 / 面板**完全不读**它 —— 历史不参与授权(见 ADR 0070 §9)。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ActivityEvent, FeishuBinding, FeishuBot
from app.domain import collaboration
from app.domain.feishu import bindings
from tests.util import executable_source, fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _bot(client, workspace_id: str, *, name: str = "助手", app_id: str = "cli_a") -> dict:
    return client.post(
        "/api/feishu/bots",
        json={"workspace_id": workspace_id, "name": name, "app_id": app_id, "app_secret": "s3cret"},
    ).json()


def _bind(db, workspace_id: str, bot_id: str, open_id: str, member_id: str) -> None:
    """成员发一张码、再从**这台机器人**把码发过去 —— 和生产里那条路一样(见 test_feishu_binding._bind)。"""
    code, _ = bindings.issue_bind_code(db, workspace_id, member_id)
    assert bindings.redeem_bind_code(db, workspace_id, bot_id, open_id, code) is not None
    db.commit()


def _history(db, workspace_id: str, bot_id: str) -> list[dict]:
    """审计表里**这台机器人**的那些绑定历史(唯一读它的那条路:工作区动态流)。"""
    return collaboration.list_activity(db, workspace_id, subject_type="feishu_binding", subject_id=bot_id)


def test_显式解绑记一条历史() -> None:
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    bot = _bot(client, ws, name="客服助手", app_id="cli_support")
    with SessionLocal() as db:
        _bind(db, ws, bot["id"], "ou_alice", me["id"])
        assert _history(db, ws, bot["id"]) == [], "还没解绑,不该有这条历史"

    assert client.delete(f"/api/feishu/bots/{bot['id']}/bindings/ou_alice").status_code == 204

    with SessionLocal() as db:
        events = _history(db, ws, bot["id"])
        assert len(events) == 1, events
        event = events[0]
        assert event["action"] == "feishu.binding.removed"
        assert event["subject_type"] == "feishu_binding"
        #: `subject_id` 只放 bot_id —— 拼上 open_id 会顶到那一列 String(64) 的边界(见 ADR 0070 §9)。
        assert event["subject_id"] == bot["id"], "`{bot_id}:{open_id}` 约 68 字符,放不进 subject_id"
        assert event["actor_id"] == me["id"], "记的是曾经被绑的那个成员(actor 是 SET NULL:人走了痕迹还在)"
        assert event["payload"] == {
            "bot_id": bot["id"],
            "app_id": "cli_support",
            "bot_name": "客服助手",
            "open_id": "ou_alice",
        }, event["payload"]

        #: 解绑之后立刻不认、也不列 —— 认人与面板读的是**活跃**表。
        assert bindings.resolve_sender(db, ws, bot["id"], "ou_alice") is None
        assert bindings.list_bindings(db, ws, bot["id"]) == []


def test_删机器人给它名下每条绑定各记一条() -> None:
    """**在级联删掉它们之前**记:记晚了就"删了就查无此事"。

    也不把已删的状态写回绑定表 —— 那张表里照旧一条不留(历史归审计表,不归活跃表)。
    """
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    doomed = _bot(client, ws, name="要删的", app_id="cli_doomed")
    kept = _bot(client, ws, name="留着的", app_id="cli_kept")
    with SessionLocal() as db:
        _bind(db, ws, doomed["id"], "ou_a", me["id"])
        _bind(db, ws, doomed["id"], "ou_b", me["id"])
        _bind(db, ws, kept["id"], "ou_kept", me["id"])

    assert client.delete(f"/api/feishu/bots/{doomed['id']}").status_code == 204

    with SessionLocal() as db:
        assert db.get(FeishuBot, doomed["id"]) is None
        assert db.query(FeishuBinding).filter_by(bot_id=doomed["id"]).count() == 0, (
            "活跃表里一条都不留(不是标成已删)"
        )
        events = _history(db, ws, doomed["id"])
        assert len(events) == 2, f"每条绑定各记一条,不是汇总成一条:{events}"
        assert {one["payload"]["open_id"] for one in events} == {"ou_a", "ou_b"}
        assert all(one["action"] == "feishu.binding.removed" for one in events)
        assert all(one["subject_id"] == doomed["id"] for one in events)
        assert {one["payload"]["app_id"] for one in events} == {"cli_doomed"}
        assert {one["payload"]["bot_name"] for one in events} == {"要删的"}

        #: 痕迹不指着 `feishu_bots`:机器人那一行没了,这两条照样查得到。
        assert len(_history(db, ws, doomed["id"])) == 2
        #: 别的机器人的绑定一动不动 —— 历史也不该记到它名下。
        assert _history(db, ws, kept["id"]) == []
        assert db.get(FeishuBinding, {"workspace_id": ws, "bot_id": kept["id"], "open_id": "ou_kept"}) is not None


def test_历史不参与授权_认人与面板只读活跃表() -> None:
    """审计表里有那一条,不等于"这个人现在还绑着"。

    认人(`resolve_sender`)与面板(`list_bindings`)只读**活跃**表;审计表只出现在工作区动态流那条
    读路径里,没有任何"从历史推出现在谁能驱动机器人"的判断。
    """
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    bot = _bot(client, ws)
    with SessionLocal() as db:
        _bind(db, ws, bot["id"], "ou_alice", me["id"])

    assert client.delete(f"/api/feishu/bots/{bot['id']}/bindings/ou_alice").status_code == 204

    with SessionLocal() as db:
        assert _history(db, ws, bot["id"])[0]["action"] == "feishu.binding.removed", "审计表里查得到"
        assert db.query(ActivityEvent).filter_by(subject_type="feishu_binding", subject_id=bot["id"]).count() == 1
        assert bindings.resolve_sender(db, ws, bot["id"], "ou_alice") is None, "历史不是授权依据"
        assert bindings.list_bindings(db, ws, bot["id"]) == []

    #: 形状上的那一半:这两个读函数**碰都不碰**审计表(碰了就是把历史当现状)。
    for reader in (bindings.resolve_sender, bindings.list_bindings):
        assert "activity" not in executable_source(reader).lower(), (
            f"{reader.__name__} 读到了审计表 —— 历史只该出现在工作区动态流里"
        )
