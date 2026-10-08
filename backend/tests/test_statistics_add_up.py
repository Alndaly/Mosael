"""统计页、管理概览上的数要对得上:点进去看到的,和加起来的合计。

- 素材数按素材库的口径(体检 UM-12):中间产物(逐句配音的一句……)不进素材库,也不进统计。此前统计写 1267、
  点进素材库只有 282。
- 「谁在花钱」各行加起来等于合计(体检 UM-11 的过渡修法):不挂任务的用量(智能体对话、画板、工作流节点里的调用)
  落进最后一行「无归属」,而不是从图上消失。写入时就记下是谁花的,等 ADR 定。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Job, ProviderUsageEvent, User
from app.domain.assets.intermediates import DUB_LINE
from tests.util import fresh_client


def _usage(workspace_id: str, key: str, micros: int, **extra) -> ProviderUsageEvent:
    return ProviderUsageEvent(
        workspace_id=workspace_id, provider="openai", model="gpt", capability="chat", operation="chat",
        idempotency_key=key, cost_micros=micros, currency="USD", cost_confidence="estimated", **extra,
    )


def test_素材数和素材库同一个口径_中间产物不算() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(Asset(workspace_id=ws, name="成片", kind="video"))
        db.add(Asset(workspace_id=ws, name="旁白", kind="audio"))
        db.add_all(Asset(workspace_id=ws, name="某音色 · 配音", kind="audio", intermediate=DUB_LINE) for _ in range(3))
        db.commit()

    summary = client.get(f"/api/workspaces/{ws}/summary").json()
    library = client.get("/api/assets/facets", params={"workspace_id": ws}).json()
    assert summary["asset_count"] == library["total"] == 2
    assert summary["asset_kinds"] == {"video": 1, "audio": 1}
    assert client.get("/api/admin/overview").json()["assets"] == 2


def test_谁在花钱_按用量自己记的人分_记不下的列在最后一行无归属_各行加起来等于合计() -> None:
    admin = fresh_client()
    ws = admin.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        tester = db.query(User).filter_by(username="tester").one().id
        someone_else = Job(workspace_id=ws, kind="generate", payload={}, created_by=None)
        db.add(someone_else)
        db.flush()
        # 智能体对话、画板里的调用不挂任务,也记得是谁花的(ADR 0050 D30);挂着的任务是谁发起的不作数 —— 记在用量上的才算。
        db.add(_usage(ws, "agent", 5_000_000, source_type="agent_message", user_id=tester))
        db.add(_usage(ws, "board", 1_000_000, source_type="board", user_id=tester, job_id=someone_else.id))
        # 升级前的老账,找不到是谁的(D31)。
        db.add(_usage(ws, "old", 7_000_000, source_type="workflow"))
        db.commit()

    overview = admin.get("/api/admin/overview").json()
    rows = [(row["user_id"] == tester, row["username"], row["costs"], row["calls"]) for row in overview["spend_by_user"]]
    assert rows == [
        (True, "tester", [{"currency": "USD", "micros": 6_000_000}], 2),
        (False, "", [{"currency": "USD", "micros": 7_000_000}], 1),
    ], "花得更多的「无归属」也排在人后面:它是余数,不是一个能去谈的人"
    assert overview["spend_by_user"][-1]["user_id"] == ""
    assert overview["costs"] == [{"currency": "USD", "micros": 13_000_000}]
