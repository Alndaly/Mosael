"""数字人按真实时长计量,百炼两个数字人模型有查证过的挂牌价。

数字人(说话照片、改口型)的成片长度跟着驱动音频走,模型不收 `duration_seconds`(ADR 0028 的 `duration_follows`)。
此前视频的计量一律取 `duration_seconds`、没有就按 5 秒记 —— 一段 60 秒的口播被记成 5 秒,长稿口播的花费严重低估;
而且这 8 个模型一个价都没有。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import select

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.contracts.generation import (
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationRequest,
    GenerationResult,
    metering_from_request,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent
from app.domain.billing import price_reference
from tests.util import add_provider, fresh_client, wait_status


def test_请求里没说时长就不猜_说了的照旧按请求记() -> None:
    silent = metering_from_request(GenerationRequest(kind="video", model="m", prompt="p", parameters={}))
    assert "video_seconds" not in silent, "猜一个 5 秒,那一格就再也改不回真实值"
    asked = metering_from_request(GenerationRequest(kind="video", model="m", prompt="p", parameters={"duration_seconds": 8}))
    assert asked["video_seconds"] == 8.0


class _FakeTalkingAdapter(GenerationAdapter):
    """不打网络的视频 Adapter:交回一段 2 秒的片子,不回报计费时长(和多数供应商一样)。"""

    vendor_id = "fake-talking"
    media_kind = "video"

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "talking.mp4"
        subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:d=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)], check=True, capture_output=True)
        return GenerationResult(output_paths=[target], usage=metering_from_request(request), raw_usage={})


register_generation_adapter_source(lambda vendor, kind: _FakeTalkingAdapter() if (vendor, kind) == ("fake-talking", "video") else None)


def test_时长跟着音频走的生成_按产出的真实时长计量() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "口播"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="假数字人", vendor="fake-talking", base_url="", api_key="k",
                               model="talk-1", capability_ids=["video"], make_default=False)
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": "fake-talking",
        "model": "talk-1", "kind": "video", "prompt": "开场白", "parameters": {},
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    with SessionLocal() as db:
        usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()
    assert abs(usage.units["video_seconds"] - 2.0) < 0.1, usage.units


def test_百炼两个数字人模型的挂牌价只收查证过的() -> None:
    [s2v] = price_reference.lookup("alibaba", "wan2.2-s2v", region="cn")
    assert (s2v.capability, s2v.billing_unit, s2v.currency, s2v.unit_amount_micros) == ("video", "video_second", "CNY", 500_000)
    [retalk] = price_reference.lookup("alibaba", "videoretalk", region="cn")
    assert (retalk.billing_unit, retalk.unit_amount_micros) == ("video_second", 80_000)
    # 官方价目页取不到原文的、按积分计价的不收
    for vendor, model in (("volcano-visual", "omnihuman-1.5"), ("heygen", "heygen-avatar-iv"),
                          ("hedra", "hedra-character-3"), ("kuaishou", "kling-avatar")):
        assert price_reference.lookup(vendor, model, region="cn") == price_reference.lookup(vendor, model, region="global") == []
