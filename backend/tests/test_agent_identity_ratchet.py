"""智能体的权限恒等式(ADR 0008 D6):

    智能体能做的  =  行动人能做的  ∩  这次对话授予的档位

两侧各有一条棘轮:

  **上界** —— 任何自动放行都必须经过与人工**同一个** `authorize_and_approve`。三档模式绕过的是
  「用户同意」,不是「他有没有这个权限」。这一条钉的是代码形状:没有第二条通往 `_claim` 的路。

  **下界** —— 三档模式只能**收紧**,不能放开行动人本来没有的东西。开着 bypass 也得先过授权。

为什么要钉:这两条今天都成立,但都是**靠人记得**成立的。上界只要有人为了"省一次查询"直接调
`approve_confirmation`,恒等式就破了,而且不会有任何测试变红 —— 卡照样被批准、活照样干完。
下界同理:autopilot 里少写一行 `authorize_*`,自动放行就变成了提权。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentSession, ToolConfirmation, User
from tests.util import fresh_client, second_client, wait_for_idle_autopilot

#: 真正落状态的那一步。任何绕过 `authorize_*` 直接调它的地方都会打破上界。
KERNEL = "approve_confirmation"

#: 允许调用内核的地方 —— 只有那两个 `authorize_*` 自己。
KERNEL_CALLERS = {("app/domain/agent/confirmations.py", "authorize_and_approve")}


def _callers_of(symbol: str) -> set[tuple[str, str]]:
    """全仓里调用 `symbol` 的 (文件, 函数)。"""
    found: set[tuple[str, str]] = set()
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == symbol:
                    found.add((str(path), fn.name))
    return found


# ---------------- 上界:只有一条通往批准的路 ----------------


def test_only_the_authorising_wrapper_may_approve() -> None:
    """内核只能由 `authorize_and_approve` 调 —— 别的调用点等于一条不过闸的批准路径。

    自动放行、飞书回调、HTTP 路由都必须汇到同一个函数上;这一条保证"必须"是结构上的,
    而不是靠每个新入口的作者记得。
    """
    strays = _callers_of(KERNEL) - KERNEL_CALLERS
    assert not strays, (
        f"这些地方绕过授权直接批准了确认卡:\n  "
        + "\n  ".join(f"{path}:{fn}" for path, fn in sorted(strays))
    )


def test_the_autopilot_settles_through_the_same_function() -> None:
    """自动放行调的必须是 `authorize_and_approve` 本尊,不是它的副本。"""
    source = pathlib.Path("app/domain/agent/autopilot.py").read_text()
    assert "authorize_and_approve" in source
    assert KERNEL not in source, "autopilot 直接碰了内核,绕开了授权"


# ---------------- 下界:模式只能收紧 ----------------


def test_bypass_cannot_grant_what_the_person_does_not_have() -> None:
    """开着 bypass 的会话,替一个**已经不在这个工作区**的人做不了决定。

    模式是"用户同意"这一侧的东西;成员关系是"他有没有权限"那一侧的。会话是长命的,成员关系不是。
    """
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    session_id = mate.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "T"}
    ).json()["id"]
    with SessionLocal() as db:
        person = db.query(User).filter(User.username == "mate").one()
        session = db.get(AgentSession, session_id)
        session.permission_mode = "bypass"
        session.mode_set_by = person.id
        db.commit()

    card = mate.post(
        "/api/confirmations",
        json={
            "workspace_id": workspace["id"],
            "tool": "run_code",
            "session_id": session_id,
            "requested_by": "pi",
            "payload": {"code": "output = 1"},
        },
    )
    assert card.status_code == 200, card.text
    wait_for_idle_autopilot()

    # 他离开了 —— 会话与它的 bypass 都还在。
    with SessionLocal() as db:
        person = db.query(User).filter(User.username == "mate").one()
        from app.domain import members as members_svc

        members_svc.remove_member(db, workspace["id"], person.id)

    denied = mate.post(
        "/api/confirmations",
        json={
            "workspace_id": workspace["id"],
            "tool": "run_code",
            "session_id": session_id,
            "requested_by": "pi",
            "payload": {"code": "output = 2"},
        },
    )
    assert denied.status_code in (403, 404), f"bypass 放开了他已经没有的权限:{denied.text}"


def test_a_card_without_a_session_is_never_automatic() -> None:
    """没有会话就没有"这次对话授予的档位" —— 恒等式右边那一项是空的,交集也是空的。

    MCP 直连、飞书外部智能体的卡走的正是这条路;让它们继承任何"默认模式"就是授权范围逃逸。
    """
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    card = owner.post(
        "/api/confirmations",
        json={
            "workspace_id": workspace["id"],
            "tool": "run_code",
            "requested_by": "mcp",
            "payload": {"code": "output = 1"},
        },
    ).json()
    wait_for_idle_autopilot()
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card["id"]).status == "pending"


def test_the_decision_is_recorded_against_a_person() -> None:
    """自动放行也有人 —— 这次执行记在他头上,而不是记在"智能体"头上。

    智能体不是主体:它花的是批准者的额度、用的是批准者的钥匙(见 Job.created_by 与
    domain/provider_credentials)。
    """
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    session_id = owner.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "T"}
    ).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        session = db.get(AgentSession, session_id)
        session.permission_mode = "bypass"
        session.mode_set_by = me.id
        db.commit()
        # 卡挂在哪次对话上**由凭据决定**,不由调用方在 body 里声明(见 autopilot.session_for_token)。
        token = mint_service_session(db, me.id, agent_session_id=session_id)
        me_id = me.id
    owner.headers["Authorization"] = f"Bearer {token}"

    card = owner.post(
        "/api/confirmations",
        json={
            "workspace_id": workspace["id"],
            "tool": "run_code",
            "session_id": session_id,
            "requested_by": "pi",
            "payload": {"code": "output = 1"},
        },
    ).json()
    wait_for_idle_autopilot()

    with SessionLocal() as db:
        row = db.get(ToolConfirmation, card["id"])
        assert row.decision_mode == "bypass"
        assert row.decided_by == me_id
