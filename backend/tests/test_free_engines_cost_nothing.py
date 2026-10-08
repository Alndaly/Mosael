"""免费的引擎(Edge 配音)记 0、可信度「免费」—— 不是「没能定价」。

隔离环境里跑带货口播:4 段 Edge 配音在账上全是 unknown(未定价)。界面据此说「有 N 次没价,少配了价格规则」,
可 Edge 本来就不要钱,也没有价格规则可配。免费的那几条也不进「花了多少钱」的汇总:它们不是钱,混进去的话一个
人民币部署的账上会冒出一笔 $0,还按次数把美元排成了主要币种。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent, User
from app.domain.billing.usage import costs_by_currency, record_usage
from tests.util import fresh_client


class _FakeCommunicate:
    def __init__(self, text: str, voice: str = "", rate: str = "") -> None:
        pass

    async def save(self, path: str) -> None:
        Path(path).write_bytes(b"fake-mp3")


@pytest.fixture
def workspace(monkeypatch) -> tuple[str, str]:
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _FakeCommunicate)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.scalars(select(User).order_by(User.created_at)).first().id
    return ws, me


def test_Edge_配音记_0_可信度是免费(workspace, tmp_path) -> None:
    from app.domain.voices.voices import speak_to_file

    ws, me = workspace
    with SessionLocal() as db:
        speak_to_file(db, text="点下方链接", engine="builtin:edge", engine_voice="zh-CN-XiaoxiaoNeural", speed=1.0,
                      workspace_id=ws, user_id=me, out_dir=tmp_path, source_type="test", source_id="t")
        db.commit()
        event = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.capability == "tts")).one()
    assert (event.cost_micros, event.cost_confidence) == (0, "free")
    assert event.units["characters"] == 5, "用了多少照样记"


def test_免费的不进花费汇总(workspace) -> None:
    ws, _me = workspace
    with SessionLocal() as db:
        record_usage(db, user_id=None, workspace_id=ws, provider="bytedance", capability="image", operation="g", idempotency_key="a",
                     cost_micros=200_000, currency="CNY", cost_confidence="reported")
        for index in range(3):
            record_usage(db, user_id=None, workspace_id=ws, provider="edge", capability="tts", operation="s", idempotency_key=f"e{index}",
                         cost_micros=0, cost_confidence="free")
        db.commit()
        totals = costs_by_currency(db, ProviderUsageEvent.workspace_id == ws).get((), [])
    assert [(one.currency, one.micros) for one in totals] == [("CNY", 200_000)]
