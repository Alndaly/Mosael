"""远端已经生成、已经扣费,但我们这边失败了(下载失败、结果地址没给全):**按服务商回报的用量或扣费照记**,不记 0。

失败的调用此前只有一种记法:服务商什么都没回 → 不计费(见 test_failed_calls_are_not_billed)。可「什么都没回」
是适配器丢掉了回包造成的:轮询拿到终态回包、成片已经生成扣了费,接着下载一失败,异常往外抛,回包留在适配器的
局部变量里,运行器拿到的只有一句错误 —— 账上记 0,而钱已经花了。付费测试照这张账控费,会一直以为没花钱。

回包怎么交出来:和远端回执同一条路(RemoteTaskWatch,见 contracts.generation)。轮询循环是异步任务那几家
唯一共同经过的地方,终态回包(成功或失败)一到手就报给运行器;同步接口的适配器在回包到手、开始下载之前报。
失败时运行器拿最后一份回包,交给那一家的 `reported_usage` 读:报了用量就按价目算,报了扣费就记扣费;
没报的(包括服务商自己判了失败、什么都没扣的)照旧不计费。失败的这一条**只按服务商报的计** —— 请求侧的数量
(请求了几秒、几张)不算,只留分辨率这类给价目分档用的属性。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.adapters.bytedance.ark.image import SeedreamAdapter
from app.ai.providers.adapters.alibaba.dashscope.image import QwenImageAdapter
from app.ai.providers.adapters.bytedance.ark.video import SeedanceAdapter, extract_video_url
from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter, extract_result_urls
from app.ai.providers.adapters.openai.image import OpenAIImageAdapter
from app.ai.providers.adapters.shared.polling import poll_until_ready
from app.ai.providers.contracts.generation import (
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    RemoteTaskWatch,
    watching_remote_tasks,
)
from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent
from app.domain.billing.usage import create_pricing_rule
from tests.billing_samples import EVOLINK_SEEDANCE_MINI, GPT_IMAGE_TEXT_ONLY, SEEDANCE_480P_WITH_AUDIO
from tests.util import add_provider, fresh_client, wait_status


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Client:
    """轮询客户端替身:依次交回几份回包。"""

    def __init__(self, *payloads: dict) -> None:
        self._payloads = list(payloads)

    def get(self, _path: str) -> _Response:
        return _Response(self._payloads.pop(0))


def _watch(settled: list) -> RemoteTaskWatch:
    return RemoteTaskWatch(remember=lambda _: None, is_cancelled=lambda: False, settled=settled.append)


def test_the_poll_loop_hands_over_the_terminal_payload() -> None:
    settled: list[dict] = []
    running = {"status": "running"}
    with watching_remote_tasks(_watch(settled)):
        poll_until_ready(_Client(running, SEEDANCE_480P_WITH_AUDIO["raw"]), "/tasks/1", extract_video_url, interval=0)
    assert settled == [SEEDANCE_480P_WITH_AUDIO["raw"]], "只交终态那一份,中间的进度回包不算"


def test_the_poll_loop_hands_over_a_failed_terminal_payload_too() -> None:
    """服务商判了失败的回包也交:有的平台失败也扣,扣了多少写在那一份里。"""
    settled: list[dict] = []
    failed = {"status": "failed", "error": {"code": "service_error", "message": "boom"}}
    with watching_remote_tasks(_watch(settled)), pytest.raises(GenerationAdapterError):
        poll_until_ready(_Client(failed), "/tasks/1", extract_result_urls, interval=0)
    assert settled == [failed]


def test_a_sync_adapter_hands_over_its_payload_before_downloading(tmp_path, monkeypatch) -> None:
    """同步接口:回包一到手(钱已经扣了)就交,下载失败也丢不掉。"""
    payload = {**GPT_IMAGE_TEXT_ONLY["raw"], "data": [{"url": "https://example.invalid/a.png"}]}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, _path: str, **_kwargs) -> _Response:
            return _Response(payload)

    def broken_download(url: str, **_kwargs):
        raise GenerationAdapterError("providerErr_noImageData", vendor="OpenAI")

    monkeypatch.setattr("app.ai.providers.adapters.openai.image.RetryingClient", FakeClient)
    monkeypatch.setattr("app.ai.providers.adapters.openai.image.fetch_bytes", broken_download)
    settled: list[dict] = []
    request = GenerationRequest(kind="image", model="gpt-image-2", prompt="a cat")
    with watching_remote_tasks(_watch(settled)), pytest.raises(GenerationAdapterError):
        OpenAIImageAdapter().generate(request, GenerationAdapterContext("p", "openai", "k"), tmp_path)
    assert settled == [payload]


def test_per_image_providers_report_how_many_images_they_billed() -> None:
    """按张计价的两家,回包里写着这一次实际生成(计费)了几张 —— 样本取自用户库。"""
    assert QwenImageAdapter().reported_usage({"output": {"task_status": "SUCCEEDED"}, "usage": {"image_count": 2}}).units == {"images": 2}
    seedream = {"model": "doubao-seedream-4-0-250828", "data": [{}], "usage": {"generated_images": 1, "output_tokens": 16384, "total_tokens": 16384}}
    assert SeedreamAdapter().reported_usage(seedream).units == {"images": 1}
    assert QwenImageAdapter().reported_usage({"output": {}}).units == {}


# ---------- 端到端:轮询拿到终态、下载失败 ----------


class _DownloadFails:
    """轮询走真的 poll_until_ready,拿到终态之后「下载」失败。"""

    terminal: dict = {}

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        poll_until_ready(_Client(self.terminal), "/tasks/remote-1", self.extract, interval=0)
        raise GenerationAdapterError("providerErr_noResultUrl", vendor="fake")  # 成片已生成、扣了费,下载那一步失败


class _FakeSeedance(_DownloadFails, SeedanceAdapter):
    vendor_id = "fake-seedance-dl"
    terminal = SEEDANCE_480P_WITH_AUDIO["raw"]
    extract = staticmethod(extract_video_url)


class _FakeEvolink(_DownloadFails, EvolinkGenerationAdapter):
    vendor_id = "fake-evolink-dl"
    terminal = EVOLINK_SEEDANCE_MINI["raw"]
    extract = staticmethod(extract_result_urls)

    def __init__(self) -> None:
        EvolinkGenerationAdapter.__init__(self, "video")


class _FakeRejected(_DownloadFails, EvolinkGenerationAdapter):
    """服务商自己判了失败、回包里什么都没扣。"""

    vendor_id = "fake-rejected-dl"
    terminal = {"status": "failed", "error": {"code": "content_policy_violation", "message": "blocked"}}
    extract = staticmethod(extract_result_urls)

    def __init__(self) -> None:
        EvolinkGenerationAdapter.__init__(self, "video")


_FAKES = {"fake-seedance-dl": _FakeSeedance, "fake-evolink-dl": _FakeEvolink, "fake-rejected-dl": _FakeRejected}
register_generation_adapter_source(lambda vendor, kind: _FAKES[vendor]() if kind == "video" and vendor in _FAKES else None)


def _run(vendor: str, model: str, *, rule: tuple[str, int, str] | None = None) -> ProviderUsageEvent:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name=vendor, vendor=vendor, base_url="", api_key="k", model=model,
                               capability_ids=["video"], make_default=False)
        if rule is not None:
            unit, micros, currency = rule
            create_pricing_rule(db, provider=vendor, capability="video", model=model, billing_unit=unit,
                                unit_amount_micros=micros, currency=currency)
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": vendor, "model": model,
        "kind": "video", "prompt": "一只猫", "parameters": {"duration_seconds": 5, "resolution": "480p"},
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "failed"
    with SessionLocal() as db:
        return db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()


def test_a_finished_seedance_task_whose_download_failed_is_billed_by_the_reported_tokens() -> None:
    usage = _run("fake-seedance-dl", "doubao-seedance-2-0-260128", rule=("million_output_token", 46_000_000, "CNY"))
    assert usage.status == "failed"
    assert (usage.cost_micros, usage.currency, usage.cost_confidence) == (5_101_492, "CNY", "estimated")
    assert usage.units["output_tokens"] == 110_902
    assert usage.units["resolution"] == "480p", "给价目分档用的属性留着"
    assert "video_seconds" not in usage.units, "请求侧的数量不算 —— 失败的这一条只按服务商报的计"
    assert usage.raw_usage["usage"]["completion_tokens"] == 110_902


def test_a_finished_evolink_task_whose_download_failed_keeps_the_reported_charge() -> None:
    usage = _run("fake-evolink-dl", "seedance-2.0-mini-image-to-video", rule=("video_second", 40_000, "USD"))
    assert (usage.status, usage.cost_micros, usage.currency, usage.cost_confidence) == ("failed", 198_529, "USD", "reported")


def test_a_task_the_provider_failed_without_charging_still_costs_nothing() -> None:
    usage = _run("fake-rejected-dl", "seedance-2.5-image-to-video", rule=("video_second", 296_000, "USD"))
    assert (usage.status, usage.cost_micros, usage.cost_confidence) == ("failed", 0, "not_billed")
    assert usage.units["video_seconds"] == 5.0, "什么都没报的失败,请求侧计量照旧留在账上"


def test_a_failure_after_the_adapter_returned_is_billed_from_its_result(monkeypatch) -> None:
    """适配器已经交回了成片和回包,失败在我们这边(登记素材出错):照回包记。"""
    from app.domain.generation import runner

    class _Done(SeedanceAdapter):
        vendor_id = "fake-seedance-done"

        def requires_credentials(self) -> bool:
            return False

        def generate(self, request, context, output_dir: Path) -> GenerationResult:
            output_dir.mkdir(parents=True, exist_ok=True)
            target = output_dir / "generated.png"
            Image.new("RGB", (4, 4)).save(target)
            return GenerationResult(output_paths=[target], usage={"videos": 1, "video_seconds": 5.0, "resolution": "480p"},
                                    raw_usage=SEEDANCE_480P_WITH_AUDIO["raw"])

    register_generation_adapter_source(lambda vendor, kind: _Done() if (vendor, kind) == ("fake-seedance-done", "video") else None)

    def broken_register(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(runner, "register_file_asset", broken_register)
    usage = _run("fake-seedance-done", "doubao-seedance-2-0-260128", rule=("million_output_token", 46_000_000, "CNY"))
    assert (usage.status, usage.cost_micros, usage.cost_confidence) == ("failed", 5_101_492, "estimated")
