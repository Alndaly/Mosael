"""服务商回包里现成的用量字段读进来,和我们记的账互相印证;对不上时记日志、在这条账上留底。

不改记账的依据(按秒、按张、按回报的扣费照旧),只核对:
- 百炼万相:usage.output_video_duration(没有就 duration)是出了几秒,SR 是分辨率档;
- MiniMax:task.usage.output_seconds 是出了几秒,task.resolution 是分辨率档;
- Evolink 出图:回包带着 token 明细(文本输入 / 参考图输入 / 出图),按参考价算出来的钱和它报的扣费应当对得上。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.adapters.alibaba.dashscope.video import WanVideoAdapter
from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter
from app.ai.providers.adapters.minimax.video import MiniMaxVideoAdapter
from app.ai.providers.contracts.generation import (
    GenerationAdapterContext,
    GenerationRequest,
    GenerationResult,
    metering_from_request,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent
from app.domain.billing.usage import create_pricing_rule
from tests.billing_samples import EVOLINK_GPT_IMAGE_2_LOW
from tests.util import add_provider, fresh_client, wait_status

WAN_2S_720P = {"usage": {"duration": 2, "input_video_duration": 0, "output_video_duration": 2, "video_count": 1, "SR": 720},
               "output": {"task_status": "SUCCEEDED", "video_url": "https://example.invalid/v.mp4"}}
MINIMAX_5S_768P = {"task": {"id": "1", "model": "MiniMax-H3", "status": "succeeded", "content": {"url": "https://example.invalid/v.mp4"},
                            "resolution": "768P", "duration": 5,
                            "usage": {"total_seconds": 5, "input_seconds": 0, "output_seconds": 5, "input_image_count": 1,
                                      "total_tokens": 175765, "prompt_tokens": 13020}}}


def test_万相回包里出了几秒_什么分辨率() -> None:
    reported = WanVideoAdapter().reported_usage(WAN_2S_720P)
    assert reported.observed == {"video_seconds": 2, "resolution": "720"}
    assert reported.units == {} and reported.cost_micros is None, "只核对,不改记账的依据"


def test_百炼数字人的回包_说话照片和改口型各报各的时长字段() -> None:
    """真跑:说话照片(wan2.2-s2v)回 usage.duration + SR,改口型(videoretalk)回 usage.video_duration —— 同一个适配器读。"""
    talk = WanVideoAdapter().reported_usage({"usage": {"duration": 5.56, "size": "512*512", "fps": 16, "video_count": 1, "SR": 480}})
    assert talk.observed == {"video_seconds": 5.56, "resolution": "480"}
    retalk = WanVideoAdapter().reported_usage({"usage": {"video_duration": 6.19, "size": "640*640", "video_ratio": "standard", "fps": 16}})
    assert retalk.observed == {"video_seconds": 6.19}


def test_MiniMax_回包里出了几秒_什么分辨率() -> None:
    reported = MiniMaxVideoAdapter().reported_usage(MINIMAX_5S_768P)
    assert reported.observed == {"video_seconds": 5, "resolution": "768P"}
    assert reported.units == {} and reported.cost_micros is None


def test_Evolink_出图回包里的_token_明细() -> None:
    reported = EvolinkGenerationAdapter("image").reported_usage(EVOLINK_GPT_IMAGE_2_LOW["raw"])
    assert reported.observed == {"input_tokens": 27, "image_input_tokens": 0, "output_tokens": 196}
    assert (reported.cost_micros, reported.units) == (5_415, {"credits": 0.3682}), "记账照旧按积分"


class _FakeShortVideo(MiniMaxVideoAdapter):
    """交回一段视频,回包说只出了 4 秒(请求的是 5 秒)。"""

    vendor_id = "fake-short-video"

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated.mp4"
        subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:d=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)], check=True, capture_output=True)
        payload = {"task": {**MINIMAX_5S_768P["task"], "usage": {**MINIMAX_5S_768P["task"]["usage"], "output_seconds": 4}}}
        return GenerationResult(output_paths=[target], usage=metering_from_request(request), raw_usage=payload)


class _FakeEvolinkImage(EvolinkGenerationAdapter):
    vendor_id = "fake-evolink-image"
    charge: float = 0.3682

    def __init__(self) -> None:
        super().__init__("image")

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated-1.png"
        subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64",
                        "-frames:v", "1", str(target)], check=True, capture_output=True)
        raw = EVOLINK_GPT_IMAGE_2_LOW["raw"]
        usage = {**raw["usage"], "cost": {"credits": type(self).charge}}
        return GenerationResult(output_paths=[target], usage=metering_from_request(request), raw_usage={**raw, "usage": usage})


register_generation_adapter_source(lambda vendor, kind: {
    ("fake-short-video", "video"): _FakeShortVideo, ("fake-evolink-image", "image"): _FakeEvolinkImage,
}.get((vendor, kind), lambda: None)())


def _generate(vendor: str, model: str, kind: str, parameters: dict, *, rules: tuple = ()) -> ProviderUsageEvent:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name=vendor, vendor=vendor, base_url="", api_key="k", model=model,
                               capability_ids=[kind], make_default=False)
        for unit, micros in rules:
            create_pricing_rule(db, provider=vendor, capability=kind, model=model, billing_unit=unit,
                                unit_amount_micros=micros, currency="USD")
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": vendor, "model": model,
        "kind": kind, "prompt": "一只猫", "parameters": parameters,
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    with SessionLocal() as db:
        return db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()


def test_回包说的秒数和记账对不上_记日志_账上留底(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.domain.generation.runner"):
        usage = _generate("fake-short-video", "MiniMax-H3", "video", {"duration_seconds": 5, "resolution": "768P"})
    assert usage.units["video_seconds"] == 5.0, "记账的依据不变"
    assert usage.raw_usage["usage_check"]["mismatched"] == {"video_seconds": {"billed": 5.0, "reported": 4}}
    assert any("对不上" in record.getMessage() and "video_seconds" in record.getMessage() for record in caplog.records)


#: Evolink gpt-image-2 的参考价:文本输入 $4.5 / 参考图输入 $7.2 / 出图 $27,每百万 token。
_GPT_IMAGE_RULES = (("million_input_token", 4_500_000), ("million_image_input_token", 7_200_000),
                    ("million_output_token", 27_000_000))


@pytest.mark.parametrize(("charge", "agrees"), [(0.3682, True), (3.4, False)])
def test_Evolink_出图按_token_明细算出来的钱和它报的扣费互相印证(caplog, charge: float, agrees: bool) -> None:
    _FakeEvolinkImage.charge = charge
    with caplog.at_level(logging.WARNING, logger="app.domain.generation.runner"):
        usage = _generate("fake-evolink-image", "gpt-image-2", "image", {"size": "1:1", "quality": "low"},
                          rules=_GPT_IMAGE_RULES)
    assert usage.cost_confidence == "reported"
    check = usage.raw_usage["usage_check"]
    assert check["observed"]["output_tokens"] == 196
    assert check["priced"] == {"micros": 5_414, "currency": "USD"}, "27 × $4.5/M + 196 × $27/M"
    if agrees:
        assert "mismatched" not in check
        assert not any("对不上" in record.getMessage() for record in caplog.records)
    else:
        assert check["mismatched"]["cost"] == {"billed": usage.cost_micros, "priced": 5_414}
        assert any("对不上" in record.getMessage() for record in caplog.records)
