"""服务商在回包里报了这一次扣了多少钱,就**直接记它**,可信度 `reported`。

Evolink 每个任务的终态回包里都带着扣费:`usage.cost.{credits, usd, cny}`。用户默认生视频用的就是它,而此前
这一家一条价目都没有,账上全是未定价 —— 钱明明就写在回包里。拿价目去估一个服务商已经报了实数的东西,只会
多一处可能对不上的地方。

币种照服务商报的记,不换算。Evolink 同时报 usd 和 cny(都是同一笔积分折出来的):记 usd —— Evolink 的价目页
按美元挂牌,内置参考价也是美元,同一个模型的估算和实扣落在同一个币种里,才加得起来、比得起来。

**按积分(credits)记,不按回包里的 usd 记。**回包里的 usd 四舍五入到了 4 位:用户在 Evolink 后台核对过三笔,积分
分毫不差(0.3682 / 1.02 / 0.3682),而后台的美元是 $0.005415 / $0.015000 / $0.005415,回包写的是 0.0055 / 0.015 /
0.0055 —— 小图每张差一百多 micros。后台的美元正是「积分 ÷ 68」(0.3682 / 68 = 0.0054147…,1.02 / 68 = 0.015,
13.5 / 68 = 0.19853,回包四舍五入成 0.199)。所以有积分时按积分折美元,积分本身也记进计量,对账按积分对。
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
from tests.billing_samples import EVOLINK_GPT_IMAGE_2_LOW, EVOLINK_SEEDANCE_MINI
from tests.util import add_provider, fresh_client, wait_status


def test_evolink_reports_the_charge_in_its_task_payload() -> None:
    reported = EvolinkGenerationAdapter("video").reported_usage(EVOLINK_SEEDANCE_MINI["raw"])
    assert (reported.cost_micros, reported.currency) == (198_529, "USD"), "13.5 积分 ÷ 68"
    assert reported.units == {"credits": 13.5}


def test_the_charge_matches_the_evolink_back_office_to_the_micro() -> None:
    """后台核对过的两笔:gpt-image-2 低画质 1K 一张 0.3682 积分 = $0.005415;gpt-image-2-beta 一张 1.02 积分 = $0.015。"""
    adapter = EvolinkGenerationAdapter("image")
    low = adapter.reported_usage(EVOLINK_GPT_IMAGE_2_LOW["raw"])
    assert (low.cost_micros, low.currency, low.units) == (5_415, "USD", {"credits": 0.3682})
    beta = adapter.reported_usage({"status": "completed", "usage": {"cost": {"credits": 1.02, "usd": 0.015, "cny": 0.102}, "credits_used": 1.02}})
    assert beta.cost_micros == 15_000


def test_without_credits_the_reported_dollars_are_taken_as_is() -> None:
    reported = EvolinkGenerationAdapter("video").reported_usage({"usage": {"cost": {"usd": 0.2}}})
    assert (reported.cost_micros, reported.currency, reported.units) == (200_000, "USD", {})


def test_a_payload_without_a_charge_reports_none() -> None:
    adapter = EvolinkGenerationAdapter("video")
    assert adapter.reported_usage({"status": "completed"}).cost_micros is None
    assert adapter.reported_usage({"usage": {"credits_used": 13.5}}).cost_micros is None, "只有积分、没有钱数,不替它折算"
    wrapped = adapter.reported_usage({"data": EVOLINK_SEEDANCE_MINI["raw"]})
    assert wrapped.cost_micros == 198_529, "网关有时把任务包在 data 里"


def test_a_reported_charge_beats_the_price_list() -> None:
    """配了参考价也一样:服务商报了实扣,就记实扣,不拿价目去估。"""
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        create_pricing_rule(db, provider="evolink", capability="video", model="seedance-2.0-mini-image-to-video",
                            billing_unit="video_second", unit_amount_micros=40_000, currency="USD")
        with billable(db, user_id=None, capability="video", operation="generation_job", workspace_id=ws, provider="evolink",
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
    assert (usage.cost_micros, usage.currency, usage.cost_confidence) == (198_529, "USD", "reported")
    assert usage.units["video_seconds"] == 5.0 and usage.units["credits"] == 13.5
