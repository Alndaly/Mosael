"""每个批准入口批下的卡都真的落库:智能体删素材之后,**另开一个会话**查,素材确实没了。

用户反馈:智能体调 delete_assets,工具结果写着「2 个素材已删除」,素材库里两个素材却还在。
领域函数(`approve_confirmation`、`delete_asset`)按约定不提交,由入口提交(见 core/unit_of_work)——
所以「执行了却没落库」只可能出在某个入口上。这里把每个入口都从「智能体开卡」走到「新会话里查 Asset」,
不打桩任何一步:卡是经智能体工具通道开的(用户撞上的就是这条),批准走入口本身。

那一次的真因不在后端:四条路都落了库,而**自动放行**的那张卡没有任何一处让界面刷新素材缓存(见
frontend/src/features/agent/confirmationCaches 的 useRefreshWhenCardsLand)。这里钉住的是后端这一半,
免得下一个入口真的漏了提交而没人知道。

棘轮:`authorize_and_approve` 的每个调用方(= 每个批准入口)都要在 `ENTRIES` 里登记一条这样的测试。
加第五个入口(重试队列、定时任务……)而不补测试,这里就红。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import pathlib
import time

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import Asset, FeishuBinding, ToolConfirmation, User
from app.domain.agent.autopilot import wait_for_idle_autopilot
from app.integrations.feishu import cards
from app.integrations.feishu.approvals import handle_card_action
from tests.util import fresh_client, insert_asset

OPEN_ID = "ou_the_owner"


class Chat:
    """一个工作区、一次对话、两份素材,和这次对话的 turn 令牌 —— 智能体开卡用的就是它。"""

    def __init__(self) -> None:
        self.client = fresh_client()
        self.workspace_id = self.client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        self.session_id = self.client.post(
            "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": self.workspace_id, "title": "T"}
        ).json()["id"]
        self.asset_ids = [
            insert_asset(self.workspace_id, kind="video", name=f"clip-{i}", file_key=f"media/clip-{i}.mp4")
            for i in range(2)
        ]
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            self.user_id = user.id
            self.turn_token = mint_service_session(db, user.id, agent_session_id=self.session_id)

    def agent_deletes(self) -> str:
        """智能体经工具通道调 delete_assets —— 和 sidecar 发的是同一个请求。返回卡的 id。"""
        response = self.client.post(
            "/api/agent/tools/delete_assets",
            json={"arguments": {"asset_ids": self.asset_ids, "workspace_id": self.workspace_id}, "requested_by": "pi"},
            headers={"Authorization": f"Bearer {self.turn_token}"},
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]["confirmation_id"]

    def assert_deleted(self, card_id: str) -> None:
        """**另开一个会话**查:入口那个会话里的对象状态不算数,落了库才算。"""
        _settle(card_id)
        with SessionLocal() as db:
            card = db.get(ToolConfirmation, card_id)
            assert card.status == "executed", card.error
            assert [one["asset_id"] for one in card.result["deleted"]] == self.asset_ids
            left = [one for one in self.asset_ids if db.get(Asset, one) is not None]
        assert not left, f"卡上说删了,库里还在:{left}"


def _settle(card_id: str, timeout: float = 10.0) -> None:
    """自动放行在后台线程里执行,等它走到终态。`approved` 是中间态 —— 已认领、还没执行完。"""
    wait_for_idle_autopilot()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            if db.get(ToolConfirmation, card_id).status not in ("pending", "approved"):
                return
        time.sleep(0.02)


def test_在对话里点批准_素材真的删了() -> None:
    chat = Chat()
    card_id = chat.agent_deletes()

    approved = chat.client.post(f"/api/confirmations/{card_id}/approve")

    assert approved.status_code == 200, approved.text
    chat.assert_deleted(card_id)


def test_在飞书卡片上点批准_素材真的删了() -> None:
    chat = Chat()
    card_id = chat.agent_deletes()
    with SessionLocal() as db:
        db.add(FeishuBinding(workspace_id=chat.workspace_id, open_id=OPEN_ID, user_id=chat.user_id))
        db.commit()

    out = handle_card_action(OPEN_ID, {"action": cards.ACTION_APPROVE, "confirmation_id": card_id})

    assert "toast" not in out, out
    chat.assert_deleted(card_id)


def test_删除卡不给本会话始终允许_仍然每次问人() -> None:
    """删素材是撤不回的那一档(destroy):「本会话始终允许」不给这个口子(见 autopilot.SESSION_ALLOWABLE),
    自动放行的那条路由 bypass 那一条测试走到。"""
    chat = Chat()
    refused = chat.client.patch(
        f"/api/agent/sessions/{chat.session_id}",
        json={"auto_allow_tools": [{"tool": "delete_assets", "permission": "destroy"}]},
    )
    assert refused.status_code == 422, refused.text

    card_id = chat.agent_deletes()

    wait_for_idle_autopilot()
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).status == "pending"


def test_完全放行档_自动放行的删除真的删了() -> None:
    chat = Chat()
    assert chat.client.patch(
        f"/api/agent/sessions/{chat.session_id}", json={"permission_mode": "bypass"}
    ).status_code == 200

    card_id = chat.agent_deletes()

    chat.assert_deleted(card_id)
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).decision_mode == "bypass"


def test_执行体炸在第二个素材_第一个也回来_文件还在_卡记失败(monkeypatch) -> None:
    """一张卡要么全做、要么全不做。此前执行体抛错时只把卡标成失败、入口照常提交 —— 删两个素材、第二个炸了,
    第一个照样删掉(提交之后连文件都清了),卡上却写着失败:用户以为什么都没发生,而这一档撤不回来。"""
    from app.domain import entities
    from app.media.paths import resolve_key

    chat = Chat()
    with SessionLocal() as db:
        for asset_id in chat.asset_ids:
            asset = db.get(Asset, asset_id)
            asset.file_key = f"media/{asset_id}/clip.mp4"
        db.commit()
    files = [resolve_key(f"media/{asset_id}/clip.mp4") for asset_id in chat.asset_ids]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
    card_id = chat.agent_deletes()

    real_forget = entities.forget_asset

    def forget_then_fail_on_the_second(db, asset):
        if asset.id == chat.asset_ids[1]:
            raise RuntimeError("第二个素材删不掉")
        return real_forget(db, asset)

    monkeypatch.setattr(entities, "forget_asset", forget_then_fail_on_the_second)
    approved = chat.client.post(f"/api/confirmations/{card_id}/approve")

    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        card = db.get(ToolConfirmation, card_id)
        assert card.status == "failed"
        assert "第二个素材删不掉" in (card.error or "")
        assert card.resolved_at is not None
        left = [one for one in chat.asset_ids if db.get(Asset, one) is not None]
    assert left == chat.asset_ids, "执行体炸了,第一个素材的删除也要撤回来"
    assert all(path.is_file() for path in files), "行回来了,文件也得在 —— 删文件的钩子不能照样跑"


# ---------------- 棘轮:每个批准入口都有一条上面这样的测试 ----------------

#: 批准入口(`authorize_and_approve` 的调用方)→ 钉住它真的提交了的那条测试。
ENTRIES = {
    ("app/api/routes/confirmations.py", "approve"): test_在对话里点批准_素材真的删了,
    ("app/integrations/feishu/approvals.py", "handle_card_action"): test_在飞书卡片上点批准_素材真的删了,
    ("app/domain/agent/autopilot.py", "_execute_thread"): test_完全放行档_自动放行的删除真的删了,
}


def _callers_of(symbol: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == symbol:
                    found.add((str(path), fn.name))
    return found


def test_每个批准入口都有一条落库测试() -> None:
    """领域层不提交,提交的是入口 —— 那么每多一个入口,就多一处可能「执行了、回了成功、却没落库」。

    它不会报错:卡的结果照样写着「已删除」(同一个会话里读得到),关掉会话才一起没了。只有从入口一路
    走到新会话里查,才看得出来。
    """
    entries = _callers_of("authorize_and_approve")
    unregistered = entries - set(ENTRIES)
    assert not unregistered, (
        "这些地方批准确认卡,却没有一条从开卡走到新会话里查结果的测试(照上面几条补一条,登记进 ENTRIES):\n  "
        + "\n  ".join(f"{path}:{fn}" for path, fn in sorted(unregistered))
    )
    stale = set(ENTRIES) - entries
    assert not stale, f"ENTRIES 里登记的入口已经不批卡了,删掉那一行:{sorted(stale)}"
