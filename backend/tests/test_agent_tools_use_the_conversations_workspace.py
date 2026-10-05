"""智能体工具没带 workspace_id 时,作用在**这次对话所在的工作区**,不是用户的第一个工作区。

此前一律回退到第一个:用户在第二个工作区里跟智能体说「把这两个素材删掉」,模型没带 workspace_id,
列的是第一个工作区的素材、删的卡也开在第一个工作区 —— 而这件事没有任何迹象。对话属于哪个工作区由
**令牌**认出来的会话决定(turn 令牌铸造时带着会话),不由调用方转述。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import ToolConfirmation, User
from tests.util import fresh_client, insert_asset


def _setup():
    client = fresh_client()
    for name in ("甲", "乙"):
        client.post("/api/workspaces", json={"name": name})
    ordered = [one["id"] for one in client.post("/api/agent/tools/list_workspaces", json={"arguments": {}}).json()["result"]]
    first, other = ordered[0], ordered[1]
    session_id = client.post("/api/agent/sessions", json={"workspace_id": other, "title": "T"}).json()["id"]
    assets = {ws: insert_asset(ws, kind="video", name=f"clip-{ws[:4]}", file_key="media/x.mp4") for ws in (first, other)}
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, user.id, agent_session_id=session_id)
    return client, first, other, assets, {"Authorization": f"Bearer {token}"}


def test_在第二个工作区里对话_不带工作区的工具作用到第二个() -> None:
    client, first, other, assets, turn = _setup()

    listed = client.post("/api/agent/tools/list_assets", json={"arguments": {}}, headers=turn).json()
    assert [one["id"] for one in listed["result"]["assets"]] == [assets[other]], "列的是对话所在的工作区"

    opened = client.post(
        "/api/agent/tools/delete_assets", json={"arguments": {"asset_ids": [assets[other]]}}, headers=turn
    ).json()
    assert "result" in opened, opened
    with SessionLocal() as db:
        card = db.get(ToolConfirmation, opened["result"]["confirmation_id"])
        assert card.workspace_id == other, "卡开在对话所在的工作区"


def test_不在对话里_照旧用第一个工作区() -> None:
    """登录令牌直连没有对话可依,第一个工作区(界面上默认选中的那个)是唯一说得通的答案。"""
    client, first, _other, assets, _turn = _setup()

    listed = client.post("/api/agent/tools/list_assets", json={"arguments": {}}).json()

    assert [one["id"] for one in listed["result"]["assets"]] == [assets[first]]
