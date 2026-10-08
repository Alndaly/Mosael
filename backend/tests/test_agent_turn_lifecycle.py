"""一轮结束,它留下的东西也跟着结束、说得对(ADR 0007 修订 2026-10-08,智能体那一路 AGENT-1/2/3/4、UC-05)。

## 现场(全部在隔离环境里用脚本化的假模型复现过)

- **孤儿确认卡**:让它建一个工作流,卡出来后按「停止」—— 会话 idle、那一轮记成失败,卡仍是 pending;这时批准,工作流真的
  建出来了,而模型被告知「那一轮失败了」,结果送不回对话。卡等满 590 秒、整轮超时(600 秒里包括等人的时间)是同一个结局。
  卡还会落进右上角全局中心,一直挂着、盖住页面工具条。
- **等人的时间算进整轮时限**:先干两分钟活再开卡,人八分钟后回来批,整轮已经被杀。
- **停止记成失败**:停在工具执行中(最常见的是正等着批卡),气泡是「智能体执行失败,请稍后重试」。
- **没配对话模型就发消息**:气泡写「请稍后重试」,真正的原因「还没有选好对话模型」藏在「错误详情」里。

这里钉宿主这一侧:收尾时作废这一轮的待决卡(按由头)、批作废的卡回 409、作废接口只认那一轮的凭据、后端重启和老数据
同一种状态、等人时整轮时限停表、停止 / 失败 / 没配模型时落库的那一条对。sidecar 那一侧(停止不算失败、停掉的部分回答
进记忆、等到点先作废卡)在 agent-sidecar/test/stop-keeps-what-was-said.test.mjs 和 card-wait-expires.test.mjs。
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.ai.sidecar import pi_client
from app.ai.sidecar.pi_client import SidecarError, TurnResult
from app.core.child_process import ChildProcess, popen_text
from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentMessage, AgentSession, ToolConfirmation
from app.domain.agent import host
from tests.test_agent_queue import _session, _wait_idle
from tests.util import fresh_client, user_id


# ---------------------------------------------------------------------------
# 等人时停表
# ---------------------------------------------------------------------------


def _sleeper(seconds: float) -> subprocess.Popen:
    return popen_text(
        [sys.executable, "-c", f"import time; time.sleep({seconds}); print('done', flush=True)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def test_停着表的那段不算进时限() -> None:
    child = ChildProcess(_sleeper(1.6), timeout=0.8)
    child.pause_deadline(cap=10)
    lines = list(child.lines())
    child.finish()
    assert lines == ["done"]
    assert not child.timed_out, "等人的时间算进了时限 —— 一轮会在人还在看卡时被杀"


def test_停表也有上限_对面卡死在等人中时看门狗照样会响() -> None:
    child = ChildProcess(_sleeper(5), timeout=0.5)
    child.pause_deadline(cap=0.3)
    list(child.lines())
    child.finish()
    assert child.timed_out, "停表没有上限的话,sidecar 一旦卡死在「等人中」,这一轮永远挂着"


def test_几张卡同时等_最后一张等完才接着走表() -> None:
    child = ChildProcess(_sleeper(1.6), timeout=0.8)
    child.pause_deadline(cap=10)
    child.pause_deadline(cap=10)
    child.resume_deadline()  # 还有一张在等
    lines = list(child.lines())
    child.finish()
    assert lines == ["done"] and not child.timed_out


def test_sidecar_报等人中_这一轮的总时限停表(monkeypatch) -> None:
    """协议这一跳:`awaiting_user` 成对来,`_run_pi` 据此停表 / 接着走。整轮时限压成 0.8 秒,假 sidecar 在「等人」里待 1.6 秒。"""
    script = (
        "import json, sys, time\n"
        "sys.stdin.readline()\n"
        "def send(event): print(json.dumps(event), flush=True)\n"
        "send({'type': 'awaiting_user', 'turnId': 'turn', 'waiting': True})\n"
        "time.sleep(1.6)\n"
        "send({'type': 'awaiting_user', 'turnId': 'turn', 'waiting': False})\n"
        "send({'type': 'turn_done', 'turnId': 'turn', 'text': '批完了,建好了', 'sessionState': []})\n"
        "sys.stdin.read()\n"
    )
    monkeypatch.setattr(
        pi_client, "spawn_pi",
        lambda **_: popen_text([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE),
    )
    monkeypatch.setattr(pi_client, "TURN_TIMEOUT_SECONDS", 0.8)
    result = pi_client.run_turn(
        "pi", prompt="建一个工作流", system_prompt="", api_base="http://127.0.0.1:1", token="t",
        provider={"base_url": "http://x/v1", "api_key": "k"}, model="m",
    )
    assert result.text == "批完了,建好了"


# ---------------------------------------------------------------------------
# 一轮收尾时作废它还在等的卡
# ---------------------------------------------------------------------------


def _open_card(session_id: str) -> str:
    """一张挂在这段对话上、还在等人的卡(就是那一轮开的那种)。"""
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        card = ToolConfirmation(
            workspace_id=session.workspace_id, tool="create_workflow", permission="edit",
            summary="新建工作流「孤儿卡测试」", payload={"name": "孤儿卡测试"}, session_id=session_id,
            requested_by="pi-agent",
        )
        db.add(card)
        db.commit()
        return card.id


def _card(card_id: str) -> ToolConfirmation:
    with SessionLocal() as db:
        return db.get(ToolConfirmation, card_id)


def _last_assistant(session_id: str) -> AgentMessage:
    with SessionLocal() as db:
        return db.query(AgentMessage).filter(
            AgentMessage.session_id == session_id, AgentMessage.role == "assistant"
        ).order_by(AgentMessage.created_at.desc()).first()


@pytest.mark.parametrize(
    ("ending", "reason"),
    [
        ("stopped", "turn_stopped"),
        ("failed", "turn_failed"),
        ("ended", "turn_ended"),  # 卡等到点之后模型接着说完了:卡也没人等了
    ],
)
def test_一轮收尾时它还在等的卡作废_批了回409(monkeypatch, ending: str, reason: str) -> None:
    opened: dict[str, str] = {}

    def turn(*_args, session_key: str = "", **_kwargs):
        opened["card"] = _open_card(session_key)
        if ending == "failed":
            raise SidecarError("上游断线")
        return TurnResult(text="第1秒…", aborted=ending == "stopped")

    monkeypatch.setattr(host, "run_turn", turn)
    client = fresh_client()
    sid = _session(client)
    assert client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "建一个工作流"}).status_code == 200
    _wait_idle(sid)

    card = _card(opened["card"])
    assert card.status == "expired", "这一轮已经结束,卡还亮着 —— 批了照样执行,结果却送不回对话"
    assert card.error == reason
    assert card.resolved_at is not None
    approved = client.post(f"/api/confirmations/{card.id}/approve")
    assert approved.status_code == 409, "作废的卡还能批"
    pending = client.get(f"/api/confirmations?workspace_id={card.workspace_id}&status=pending&decidable=true").json()
    assert pending == [], "作废的卡还在全局确认中心里"


def test_别的对话的卡和没挂对话的卡不受这一轮收尾影响(monkeypatch) -> None:
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: TurnResult(text="好"))
    client = fresh_client()
    sid = _session(client)
    other = client.post(
        "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": client.get("/api/workspaces").json()[0]["id"]}
    ).json()["id"]
    elsewhere = _open_card(other)
    with SessionLocal() as db:
        session = db.get(AgentSession, sid)
        mcp = ToolConfirmation(workspace_id=session.workspace_id, tool="create_workflow", permission="edit",
                               summary="MCP 直连开的", payload={}, session_id=None, requested_by="mcp-agent")
        db.add(mcp)
        db.commit()
        mcp_id = mcp.id
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "你好"})
    _wait_idle(sid)
    assert _card(elsewhere).status == "pending"
    assert _card(mcp_id).status == "pending"


def test_卡等到点由那一轮的凭据作废_别人作废不了() -> None:
    client = fresh_client()
    sid = _session(client)
    card_id = _open_card(sid)
    other = client.post(
        "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": client.get("/api/workspaces").json()[0]["id"]}
    ).json()["id"]
    with SessionLocal() as db:
        mine = mint_service_session(db, user_id(), agent_session_id=sid)
        theirs = mint_service_session(db, user_id(), agent_session_id=other)

    # 登录令牌(看得见这张卡的人)作废不了 —— 作废是「那一轮不再等它了」,只有那一轮说了算。
    assert client.post(f"/api/confirmations/{card_id}/expire").status_code == 404
    assert client.post(f"/api/confirmations/{card_id}/expire", headers={"Authorization": f"Bearer {theirs}"}).status_code == 404
    assert _card(card_id).status == "pending"

    done = client.post(f"/api/confirmations/{card_id}/expire", headers={"Authorization": f"Bearer {mine}"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "expired"
    assert _card(card_id).error == "wait_timeout"
    assert client.post(f"/api/confirmations/{card_id}/approve").status_code == 409

    # 已经有结论的不动。
    approved = _open_card(sid)
    with SessionLocal() as db:
        db.get(ToolConfirmation, approved).status = "rejected"
        db.commit()
    again = client.post(f"/api/confirmations/{approved}/expire", headers={"Authorization": f"Bearer {mine}"})
    assert again.status_code == 200 and again.json()["status"] == "rejected"


def test_后端重启作废的卡和别的作废同一种状态() -> None:
    client = fresh_client()
    sid = _session(client)
    card_id = _open_card(sid)
    with SessionLocal() as db:
        db.get(AgentSession, sid).status = "running"
        db.commit()
        assert host.reconcile_orphaned_agent_sessions(db) == 1
        db.commit()  # 启动收尾的几步不各自提交,由 restart.settle_previous_run 收完一起提交(ADR 0018 修订)
    card = _card(card_id)
    assert (card.status, card.error) == ("expired", "backend_restarted")


def test_老库里的孤儿卡和老的已取消卡_迁移成作废() -> None:
    from app.db.migrations import _expire_orphaned_session_confirmations

    client = fresh_client()
    sid = _session(client)
    orphan = _open_card(sid)
    restarted = _open_card(sid)
    with SessionLocal() as db:
        db.get(ToolConfirmation, restarted).status = "cancelled"
        db.get(ToolConfirmation, restarted).error = "backend restarted mid-turn"
        workspace_id = db.get(AgentSession, sid).workspace_id
        mcp = ToolConfirmation(workspace_id=workspace_id, tool="create_workflow", permission="edit",
                               summary="MCP 直连开的", payload={}, session_id=None, requested_by="mcp-agent")
        done = ToolConfirmation(workspace_id=workspace_id, tool="create_workflow", permission="edit",
                                summary="批过的", payload={}, session_id=sid, status="executed")
        db.add_all([mcp, done])
        db.commit()
        mcp_id, done_id = mcp.id, done.id

    _expire_orphaned_session_confirmations()
    _expire_orphaned_session_confirmations()  # 幂等

    assert (_card(orphan).status, _card(orphan).error) == ("expired", "orphaned")
    assert _card(orphan).resolved_at is not None
    assert (_card(restarted).status, _card(restarted).error) == ("expired", "backend_restarted")
    assert _card(mcp_id).status == "pending", "没挂对话的卡不属于哪一轮,不碰"
    assert _card(done_id).status == "executed"


def test_迁移在迁移计划里() -> None:
    from app.db.migrations import migration_plan

    assert "expire-orphaned-session-confirmations" in {step.name for step in migration_plan().steps}


# ---------------------------------------------------------------------------
# 停止 / 失败 / 没配模型时落库的那一条
# ---------------------------------------------------------------------------


def test_还没出字就被停下_记成停止不是模型什么都没回(monkeypatch) -> None:
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: TurnResult(text="", aborted=True))
    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "写一篇长文"})
    _wait_idle(sid)
    last = _last_assistant(sid)
    assert last.error is None, "按了停止被记成失败(此前是「模型没有返回任何内容,请检查供应商配置」)"
    assert last.content == "(还没开始回答就停下了。)"


def test_失败带回了记忆_落库记下记忆已回存(monkeypatch) -> None:
    def turn(*_args, **_kwargs):
        raise SidecarError("上游断线", [{"role": "user", "content": [{"type": "text", "text": "建工作流"}]}])

    monkeypatch.setattr(host, "run_turn", turn)
    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "建工作流"})
    _wait_idle(sid)
    last = _last_assistant(sid)
    assert last.error and (last.payload or {}).get("memory_saved") is True

    # 下一轮的补记不再把「建工作流」当成没见过的话重述,只补一句中断原因。
    with SessionLocal() as db:
        note = host.unseen_since_last_success(db, db.get(AgentSession, sid))
    assert "上游断线" in note and "用户说:建工作流" not in note


def test_没配对话模型_气泡直接说原因_并带上去设置的线索() -> None:
    """UC-05:新用户没配对话模型就发消息,此前气泡是「智能体执行失败,请稍后重试」—— 而重试永远不会好。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    sid = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws["id"]}).json()["id"]
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "整理我的素材"})
    _wait_idle(sid)
    last = _last_assistant(sid)
    assert last.error
    assert "还没有选好对话模型" in last.content, f"气泡上没说原因:{last.content}"
    assert (last.payload or {}).get("error_code") == "no_chat_model", "界面要据此给一个去设置的按钮"


def _fake_sidecar(monkeypatch, *events: dict) -> None:
    import json as _json

    lines = "".join(f"print({_json.dumps(_json.dumps(event, ensure_ascii=False))}, flush=True)\n" for event in events)
    script = "import sys\nsys.stdin.readline()\n" + lines + "sys.stdin.read()\n"
    monkeypatch.setattr(
        pi_client, "spawn_pi",
        lambda **_: popen_text([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE),
    )


def test_供应商配置问题_气泡上说原因而不是请稍后重试(monkeypatch) -> None:
    """还没调过工具就失败,多半是端点 / 模型名不对:气泡(`human`)带上供应商的原话和检查清单,不是一句「请稍后重试」。"""
    _fake_sidecar(monkeypatch, {"type": "error", "turnId": "turn", "message": "404 model not found"})
    with pytest.raises(SidecarError) as caught:
        pi_client.run_turn(
            "pi", prompt="你好", system_prompt="", api_base="http://127.0.0.1:1", token="t",
            provider={"base_url": "http://x/v1", "api_key": "k"}, model="m",
        )
    assert "404 model not found" in caught.value.human
    assert "base_url" in caught.value.human


def test_没有供应商时_sidecar_那一层也说清原因并给出去设置的线索() -> None:
    with pytest.raises(SidecarError) as caught:
        pi_client.run_turn("pi", prompt="你好", system_prompt="", api_base="", token="t", provider=None, model=None)
    assert caught.value.human and caught.value.code == "no_chat_model"
