"""服务商在回包里报了这一次扣了多少钱,就**直接记它**,可信度 `reported`。

Evolink 每个任务的终态回包里都带着扣费:`usage.cost.{credits, usd, cny}`。用户默认生视频用的就是它,而此前
这一家一条价目都没有,账上全是未定价 —— 钱明明就写在回包里。拿价目去估一个服务商已经报了实数的东西,只会
多一处可能对不上的地方。

币种照服务商报的记,不换算。Evolink 同时报 usd 和 cny(都是同一笔积分折出来的):记 usd —— Evolink 的价目页
按美元挂牌,内置参考价也是美元,同一个模型的估算和实扣落在同一个币种里,才加得起来、比得起来。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter
from app.ai.providers.contracts.generation import (
    GenerationAdapterContext,
    GenerationRequest,
    GenerationResult,
    metering_from_request,
)
from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent
from app.domain.billing.usage import billable, create_pricing_rule
from tests.billing_samples import EVOLINK_SEEDANCE_MINI
from tests.util import add_provider, fresh_client, wait_status


def test_evolink_reports_the_charge_in_its_task_payload() -> None:
    reported = EvolinkGenerationAdapter("video").reported_usage(EVOLINK_SEEDANCE_MINI["raw"])
    assert (reported.cost_micros, reported.currency) == (199_000, "USD")


def test_a_payload_without_a_charge_reports_none() -> None:
    adapter = EvolinkGenerationAdapter("video")
    assert adapter.reported_usage({"status": "completed"}).cost_micros is None
    assert adapter.reported_usage({"usage": {"credits_used": 13.5}}).cost_micros is None, "只有积分、没有钱数,不替它折算"
    wrapped = adapter.reported_usage({"data": EVOLINK_SEEDANCE_MINI["raw"]})
    assert wrapped.cost_micros == 199_000, "网关有时把任务包在 data 里"


def test_a_reported_charge_beats_the_price_list() -> None:
    """配了参考价也一样:服务商报了实扣,就记实扣,不拿价目去估。"""
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        create_pricing_rule(db, provider="evolink", capability="video", model="seedance-2.0-mini-image-to-video",
                            billing_unit="video_second", unit_amount_micros=40_000, currency="USD")
        with billable(db, capability="video", operation="generation_job", workspace_id=ws, provider="evolink",
                      model="seedance-2.0-mini-image-to-video", idempotency_key="evolink-reported") as call:
            call.meter(EVOLINK_SEEDANCE_MINI["units"], raw=EVOLINK_SEEDANCE_MINI["raw"])
            call.report_cost(199_000, "USD")
        db.commit()
        event = call.event
    assert (event.cost_micros, event.currency, event.cost_confidence) == (199_000, "USD", "reported")
    assert event.pricing_rule_id is None


class _FakeEvolink(EvolinkGenerationAdapter):
    """不打网络的 Evolink:交回一段视频和真实形状的终态回包。"""

    vendor_id = "fake-evolink"

    def __init__(self) -> None:
        super().__init__("video")

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        import subprocess

        from app.core.config import settings

        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated-1.mp4"
        subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:d=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)], check=True, capture_output=True)
        return GenerationResult(output_paths=[target], usage=metering_from_request(request), raw_usage=EVOLINK_SEEDANCE_MINI["raw"])


register_generation_adapter_source(lambda vendor, kind: _FakeEvolink() if (vendor, kind) == ("fake-evolink", "video") else None)


def test_the_runner_books_the_reported_charge() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="假 Evolink", vendor="fake-evolink", base_url="", api_key="k",
                               model="seedance-2.0-mini-image-to-video", capability_ids=["video"], make_default=False)
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": "fake-evolink",
        "model": "seedance-2.0-mini-image-to-video", "kind": "video", "prompt": "一只猫",
        "parameters": {"duration_seconds": 5, "resolution": "720p"},
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    with SessionLocal() as db:
        usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()
    assert (usage.cost_micros, usage.currency, usage.cost_confidence) == (199_000, "USD", "reported")
    assert usage.units["video_seconds"] == 5.0
