"""没能定价时,要说清**缺哪个模型的价**。

用户报的原话:「我明明设置了价格规则」。他配了九条,首页却写着「暂无价格规则」—— 因为那九条
挂在别的档案、别的模型上,没有一条对得上他实际在用的 `deepseek-v4-flash`。

笼统的否定在这里是错的:它把「这个模型没配价」说成了「一条规则都没有」,于是用户先怀疑的是
功能坏了,而不是去补那一条。摘要因此要带上**是哪几个**没定上价。
"""
from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Workspace
from app.domain.usage import record_usage, summarize_usage
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_unpriced_names_the_models_that_have_no_rule() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        for index in range(3):
            record_usage(
                db, workspace_id=workspace_id, provider="deepseek", capability="chat",
                model="deepseek-v4-flash", operation="chat", units={"input_tokens": 100},
                idempotency_key=f"ds-{index}",
            )
        record_usage(
            db, workspace_id=workspace_id, provider="kimi-coding", capability="chat",
            model="k3", operation="chat", units={"input_tokens": 50}, idempotency_key="k3-1",
        )
        db.commit()
        summary = summarize_usage(db, workspace_id=workspace_id, days=14)

    assert summary.unknown_cost_events == 4
    # 次数多的排前面 —— 要补价的话先补这个最划算。
    assert [row["model"] for row in summary.unpriced] == ["deepseek-v4-flash", "k3"]
    assert summary.unpriced[0]["events"] == 3
    assert summary.unpriced[0]["provider"] == "deepseek"


def test_a_priced_event_does_not_show_up_as_missing() -> None:
    """定上价的不该出现在缺价清单里 —— 否则那份清单会一直劝用户去配已经配好的东西。"""
    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        record_usage(
            db, workspace_id=workspace_id, provider="deepseek", capability="chat",
            model="deepseek-v4-flash", operation="chat", units={"input_tokens": 100},
            cost_micros=1234, currency="USD", idempotency_key="priced-1",
        )
        db.commit()
        summary = summarize_usage(db, workspace_id=workspace_id, days=14)

    assert summary.unknown_cost_events == 0
    assert summary.unpriced == []


def test_a_model_without_a_name_still_gets_reported() -> None:
    """Edge TTS 这类引擎不带模型名。用 provider 顶上,而不是让它从清单里消失 ——
    消失了的话「18 次没定价」和列出来的几条就对不上,用户会以为清单不全。"""
    client = fresh_client()
    workspace_id = _workspace(client)
    with SessionLocal() as db:
        record_usage(
            db, workspace_id=workspace_id, provider="edge", capability="tts",
            model="", operation="tts", units={"characters": 92}, idempotency_key="edge-1",
        )
        db.commit()
        summary = summarize_usage(db, workspace_id=workspace_id, days=14)

    assert summary.unpriced == [{"provider": "edge", "model": "", "capability": "tts", "events": 1}]
