"""按 token 计价的生成(Seedance 视频、GPT Image 生图):计量要记**回包里实际计费的 token 数**。

官方价目表给这两种模型预填的是按 token 的价(见 domain/billing/price_reference)。适配器只报请求侧那份
(按提示词估的几十个 token)的话,规则要么对不上、要么对上一个差好几个数量级的数:用户库里 147ai 的
gpt-image-2 有输入 $5 / 输出 $30 两条规则,而每次只按估的十几个输入 token 记了几十 micros ——
回包里明明写着 196 个图像输出 token。

服务商回报的计量由适配器的 `reported_usage(回包)` 读出来:运行器记账时叠在请求侧计量上,补算老账的迁移
对着库里存的回包读同一个函数。请求侧按提示词估的 token(`token_estimate`)在服务商报了 token 数之后让位;
**估出来的 token 数本身不计价** —— 它是画图表用的,不是账单(见 core/token_estimate)。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.adapters.bytedance.ark.video import SeedanceAdapter
from app.ai.providers.adapters.openai.image import OpenAIImageAdapter
from app.ai.providers.contracts.generation import (
    GenerationAdapterContext,
    GenerationRequest,
    GenerationResult,
    ReportedUsage,
    metering_from_request,
    with_reported,
)
from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent
from app.domain.billing import price_reference
from app.domain.billing.usage import create_pricing_rule, record_usage
from tests.billing_samples import GPT_IMAGE_CLIENT_WITH_REFERENCES, GPT_IMAGE_TEXT_ONLY, SEEDANCE_480P_WITH_AUDIO
from tests.util import add_provider, fresh_client, wait_status

GPT_IMAGE = OpenAIImageAdapter("openai-compatible")


def test_seedance_records_the_billed_completion_tokens() -> None:
    reported = SeedanceAdapter().reported_usage(SEEDANCE_480P_WITH_AUDIO["raw"])
    assert reported.units == {"output_tokens": 110_902, "total_tokens": 110_902}
    units = with_reported(SEEDANCE_480P_WITH_AUDIO["units"], reported.units)
    assert units["output_tokens"] == 110_902
    assert units["video_seconds"] == 5.0 and units["resolution"] == "480p", "请求侧的计量照旧保留"
    assert "token_estimate" not in units and "input_tokens" not in units, "按提示词估的 token 让位给服务商报的"
    assert units["input_characters"] == 145, "提示词有多长这件事照旧留着"


def test_seedance_without_usage_stays_unpriceable() -> None:
    """回包没带 usage 就不编一个 —— 按 token 的规则对不上,账上照实显示未定价。"""
    assert SeedanceAdapter().reported_usage({"status": "succeeded"}).units == {}


def test_gpt_image_reads_text_input_reference_image_input_and_output_tokens() -> None:
    reported = GPT_IMAGE.reported_usage(GPT_IMAGE_CLIENT_WITH_REFERENCES["raw"])
    assert reported.units == {
        "input_tokens": 215,
        "image_input_tokens": 1120,
        "output_tokens": 1756,
        "total_tokens": 3091,
    }
    units = with_reported(GPT_IMAGE_CLIENT_WITH_REFERENCES["units"], reported.units)
    assert (units["input_tokens"], units["images"], units["source_images"]) == (215, 1, 2)
    assert "token_estimate" not in units
    assert GPT_IMAGE.reported_usage({"data": []}).units == {}


def test_gpt_image_without_input_details_counts_the_whole_input_as_text() -> None:
    """有的兼容端点只回总数、不拆文字 / 图像:整段按文字输入记(拆不出来就不猜)。"""
    reported = GPT_IMAGE.reported_usage({"usage": {"input_tokens": 50, "output_tokens": 4160, "total_tokens": 4210}})
    assert reported.units == {"input_tokens": 50, "output_tokens": 4160, "total_tokens": 4210}


def _gpt_image_rules(db, model: str) -> None:
    for unit, micros in (("million_input_token", 5_000_000), ("million_image_input_token", 8_000_000), ("million_output_token", 30_000_000)):
        create_pricing_rule(db, provider="openai-compatible", capability="image", model=model,
                            billing_unit=unit, unit_amount_micros=micros, currency="USD")


def _record(db, ws: str, model: str, units: dict, key: str) -> ProviderUsageEvent:
    return record_usage(db, workspace_id=ws, provider="openai-compatible", model=model, capability="image",
                        operation="generation_job", idempotency_key=key, units=units)


def test_gpt_image_prices_text_input_image_input_and_output() -> None:
    """215 × $5 + 1120 × $8 + 1756 × $30(每百万)= $0.062715;纯文生图那次 19 × $5 + 196 × $30 = $0.005975。"""
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        _gpt_image_rules(db, "gpt-image-2")
        with_refs = _record(db, ws, "gpt-image-2", with_reported(
            GPT_IMAGE_CLIENT_WITH_REFERENCES["units"], GPT_IMAGE.reported_usage(GPT_IMAGE_CLIENT_WITH_REFERENCES["raw"]).units
        ), "with-refs")
        text_only = _record(db, ws, "gpt-image-2", with_reported(
            GPT_IMAGE_TEXT_ONLY["units"], GPT_IMAGE.reported_usage(GPT_IMAGE_TEXT_ONLY["raw"]).units
        ), "text-only")
        db.commit()
    assert (with_refs.cost_micros, with_refs.currency, with_refs.cost_confidence) == (62_715, "USD", "estimated")
    assert text_only.cost_micros == 5_975


def test_estimated_prompt_tokens_alone_are_not_priced() -> None:
    """回包没报用量的兼容端点:只剩按提示词估的十几个 token。按它记几十 micros 看起来「有价」,
    实际差两个数量级 —— 那正是此前 gpt-image-2 账上的样子。记成未定价,一眼看得出缺什么。"""
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        _gpt_image_rules(db, "gpt-image-2")
        event = _record(db, ws, "gpt-image-2", GPT_IMAGE_TEXT_ONLY["units"], "estimate-only")
        db.commit()
    assert event.cost_micros is None
    assert event.cost_confidence == "unknown"


def test_the_price_list_charges_gpt_image_for_text_input_image_input_and_output() -> None:
    prices = {entry.billing_unit: entry.unit_amount_micros for entry in price_reference.lookup("openai", "gpt-image-2")}
    assert prices == {
        "million_input_token": 5_000_000,
        "million_image_input_token": 8_000_000,
        "million_output_token": 30_000_000,
    }


class _FakeGptImage(OpenAIImageAdapter):
    """不打网络的 GPT Image:交回一张图和 147ai 真实回包形状的 usage。"""

    def __init__(self) -> None:
        super().__init__("fake-gpt-image")

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated-1.png"
        Image.new("RGB", (8, 8), "gray").save(target)
        return GenerationResult(output_paths=[target], usage=metering_from_request(request),
                                raw_usage=GPT_IMAGE_CLIENT_WITH_REFERENCES["raw"])


register_generation_adapter_source(lambda vendor, kind: _FakeGptImage() if (vendor, kind) == ("fake-gpt-image", "image") else None)


def test_the_runner_books_what_the_provider_reported() -> None:
    """端到端:生成任务跑完,账上是回包里的 token 数和按它算的钱,不是请求侧估的那几个。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="假 147ai", vendor="fake-gpt-image", base_url="", api_key="k",
                               model="gpt-image-2-client", capability_ids=["image"], make_default=False)
        for unit, micros in (("million_input_token", 5_000_000), ("million_image_input_token", 8_000_000), ("million_output_token", 30_000_000)):
            create_pricing_rule(db, provider="fake-gpt-image", capability="image", model="gpt-image-2-client",
                                billing_unit=unit, unit_amount_micros=micros, currency="USD")
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": "fake-gpt-image",
        "model": "gpt-image-2-client", "kind": "image", "prompt": "一只猫", "parameters": {},
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    with SessionLocal() as db:
        usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()
    assert (usage.units["input_tokens"], usage.units["image_input_tokens"], usage.units["output_tokens"]) == (215, 1120, 1756)
    assert "token_estimate" not in usage.units
    assert (usage.cost_micros, usage.currency, usage.cost_confidence) == (62_715, "USD", "estimated")


class _UnreadableUsage(_FakeGptImage):
    def __init__(self) -> None:
        super().__init__()
        self.vendor_id = "fake-unreadable"

    def reported_usage(self, raw_usage: dict) -> ReportedUsage:
        raise ValueError("回包换了形状")


register_generation_adapter_source(lambda vendor, kind: _UnreadableUsage() if (vendor, kind) == ("fake-unreadable", "image") else None)


def test_an_unreadable_payload_does_not_fail_a_finished_generation() -> None:
    """记账是旁路:回包读不懂(服务商改了形状),按请求侧计量照记,不把一次已经成功、已经付了钱的生成判成失败。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="假的", vendor="fake-unreadable", base_url="", api_key="k",
                               model="gpt-image-2", capability_ids=["image"], make_default=False)
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": "fake-unreadable",
        "model": "gpt-image-2", "kind": "image", "prompt": "一只猫", "parameters": {},
    })
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    with SessionLocal() as db:
        usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()
    assert usage.status == "succeeded" and usage.units["images"] == 1
