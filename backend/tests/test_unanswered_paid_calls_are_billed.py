"""付费请求送到了、没等到回答,不再记成「未扣费」;调服务商调到一半后端重启,这一笔也不再丢(GEN-6)。

此前同步生图(gpt-image-1 高质量一次四张、Seedream)读超时 —— 请求早已送到、对方在做 —— 任务判失败、账记 0「未扣费」,
提示像是「请求失败」,用户照着重来就是再付一次。重启打断同步调用 / 异步提交时没有回执,任务判「后端重启中断」,一条用量
都没有。现在:请求侧计量估一笔、注明结局不明 / 被重启打断,失败那句话说清「服务商可能照样做完、扣了费,先去后台核对」。
同步接口等回答的上限也从 120 / 180 秒放宽到 600 秒。

不调真实接口:真实的方舟 Seedream / Seedance、OpenAI、通义千问改图适配器 + httpx.MockTransport。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.http_retry import RetryingClient as RealClient, sent_but_unanswered
from app.core.unit_of_work import unit_of_work
from app.db.models import GenerationJob, Job, ProviderUsageEvent
from app.domain.billing.usage import create_pricing_rule
from app.domain.generation import runner
from tests.util import module_time

SEEDREAM = "doubao-seedream-4-0-250828"
SEEDANCE = "doubao-seedance-2-0-260128"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import app.core.http_retry as http_retry

    monkeypatch.setattr(http_retry, "time", module_time(sleep=lambda *_: None))


def _post(url: str = "https://ark.example/api/v3/images/generations") -> httpx.Request:
    return httpx.Request("POST", url)


# --------------------------------------------------------------------- 判据


@pytest.mark.parametrize(
    ("exc", "unanswered"),
    [
        (httpx.ReadTimeout("timed out", request=_post()), True),
        (httpx.RemoteProtocolError("Server disconnected without sending a response.", request=_post()), True),
        (httpx.ReadTimeout("timed out", request=httpx.Request("GET", "https://ark.example/tasks/1")), False),
        (httpx.ConnectError("refused", request=_post()), False),
        (httpx.ConnectTimeout("timed out", request=_post()), False),
    ],
    ids=["POST读超时", "POST回答中途断线", "轮询GET读超时", "连不上", "连接超时"],
)
def test_送到了没等到回答_和当场没做_分得开(exc: Exception, unanswered: bool) -> None:
    assert sent_but_unanswered(exc) is unanswered


@pytest.mark.parametrize(("status", "unanswered"), [(524, True), (502, True), (504, True), (503, False), (429, False),
                                                    (500, False), (401, False)])
def test_网关说没等到才算结局不明_源站自己说没做的不算(status: int, unanswered: bool) -> None:
    request = _post()
    exc = httpx.HTTPStatusError("x", request=request, response=httpx.Response(status, request=request))
    assert sent_but_unanswered(exc) is unanswered


def test_适配器包了一层也认得出() -> None:
    from app.ai.providers.contracts.generation import GenerationAdapterError

    try:
        try:
            raise httpx.ReadTimeout("timed out", request=_post())
        except httpx.HTTPError as exc:
            raise GenerationAdapterError("providerErr_requestFailed", vendor="ARK", detail=str(exc)) from exc
    except GenerationAdapterError as wrapped:
        assert sent_but_unanswered(wrapped)


# --------------------------------------------------------------------- 运行器


def _route(monkeypatch, module, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)

    class Routed(RealClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "RetryingClient", Routed)
    return seen


def _connection(monkeypatch) -> None:
    profile = SimpleNamespace(id=None, vendor="bytedance", api_key="sk-test", base_url="", extra={})
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: profile)
    monkeypatch.setattr(runner.provider_models, "model_id_for", lambda *a, **kw: "")


def _generation(client, *, kind: str, model: str, parameters: dict, status: str = "queued",
                payload: dict | None = None) -> tuple[str, str]:
    from tests.util import user_id

    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status=status, payload=payload or {},
                  created_by=user_id())
        db.add(job)
        db.flush()
        generation = GenerationJob(workspace_id=workspace, job_id=job.id, kind=kind, provider="bytedance", model=model,
                                   request={"prompt": "猫", "parameters": parameters})
        db.add(generation)
        create_pricing_rule(db, provider="bytedance", capability="image", model=SEEDREAM, billing_unit="image",
                            unit_amount_micros=200_000, currency="CNY")
        create_pricing_rule(db, provider="bytedance", capability="video", model=SEEDANCE, billing_unit="video_second",
                            unit_amount_micros=500_000, currency="CNY")
        db.commit()
        return job.id, generation.id


def _usage(generation_id: str) -> list[ProviderUsageEvent]:
    with SessionLocal() as db:
        rows = list(db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.source_id == generation_id)))
        db.expunge_all()
        return rows


def test_同步生图读超时_估一笔_说清可能已经扣费_只发一次(monkeypatch) -> None:
    from app.ai.providers.adapters.bytedance.ark import image as ark_image
    from tests.util import fresh_client

    client = fresh_client()
    _connection(monkeypatch)

    marked: list[bool] = []

    def slow(request: httpx.Request) -> httpx.Response:
        with SessionLocal() as db:  # 调着服务商的那一刻,任务上有「正在调」的标记 —— 这时重启,靠它估账
            marked.append(runner.PROVIDER_CALL_FIELD in (db.get(Job, job_id).payload or {}))
        raise httpx.ReadTimeout("The read operation timed out", request=request)

    sent = _route(monkeypatch, ark_image, slow)
    job_id, generation_id = _generation(client, kind="image", model=SEEDREAM, parameters={"num_images": 1})

    runner._run_generation(generation_id)

    assert [request.method for request in sent] == ["POST"], "读超时的付费 POST 不重发"
    assert marked == [True]
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert (job.status, job.error_key) == ("failed", "genErr_outcomeUnknown")
        assert runner.PROVIDER_CALL_FIELD not in (job.payload or {}), "走完了,「正在调服务商」要摘掉"
    [usage] = _usage(generation_id)
    assert usage.status == "failed"
    assert usage.cost_confidence == "estimated" and usage.cost_micros == 200_000, "不再记成「未扣费」"
    assert usage.raw_usage["outcome_unknown"] is True
    record = client.get("/api/generation/jobs", params={"workspace_id": job.workspace_id}).json()[0]
    assert "后台" in record["error"] and "扣" in record["error"]


def test_当场被拒的照旧记未扣费(monkeypatch) -> None:
    """401 是「没做」:别把每一次填错钥匙都记成一笔估算的花费。"""
    from app.ai.providers.adapters.bytedance.ark import image as ark_image
    from tests.util import fresh_client

    client = fresh_client()
    _connection(monkeypatch)
    _route(monkeypatch, ark_image, lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}))
    _, generation_id = _generation(client, kind="image", model=SEEDREAM, parameters={"num_images": 1})

    runner._run_generation(generation_id)

    [usage] = _usage(generation_id)
    assert (usage.status, usage.cost_confidence) == ("failed", "not_billed")


def test_同步接口等回答的上限放宽到十分钟_连不上照旧很快放弃(monkeypatch) -> None:
    from app.ai.providers.adapters.alibaba.dashscope import image as dashscope_image
    from app.ai.providers.adapters.bytedance.ark import image as ark_image
    from app.ai.providers.adapters.openai import image as openai_image
    from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationRequest

    timeouts: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"])
        raise httpx.ConnectError("stop here", request=request)

    for module in (openai_image, ark_image, dashscope_image):
        _route(monkeypatch, module, capture)
    context = GenerationAdapterContext(connection_id=None, vendor_id="x", api_key="k", base_url="https://api.example")
    calls = [
        (openai_image.OpenAIImageAdapter(), GenerationRequest(kind="image", model="gpt-image-1", prompt="猫")),
        (ark_image.SeedreamAdapter(), GenerationRequest(kind="image", model=SEEDREAM, prompt="猫")),
        (dashscope_image.QwenImageAdapter(), GenerationRequest(
            kind="image", model="qwen-image-edit", prompt="猫",
            parameters={"reference_image_url": "https://img.example/a.png"})),
    ]
    for adapter, request in calls:
        timeouts.clear()
        with pytest.raises(Exception):  # noqa: B017 — 这里只看发出去时带的超时
            adapter.generate(request, context, Path("/nonexistent"))
        assert timeouts, f"{type(adapter).__name__} 没发出请求"
        for timeout in timeouts:
            assert timeout["read"] >= 600 and timeout["connect"] <= 30, (type(adapter).__name__, timeout)


def test_调到一半后端重启_估一笔_写明被重启打断_只记一次(monkeypatch) -> None:
    from app.domain.restart import reconcile_after_restart
    from tests.util import fresh_client

    client = fresh_client()
    _connection(monkeypatch)
    interrupted, interrupted_generation = _generation(
        client, kind="video", model=SEEDANCE, parameters={"duration_seconds": 4, "resolution": "480p"},
        status="running", payload={runner.PROVIDER_CALL_FIELD: True},
    )
    #: 还没调到服务商就重启了的:没有「正在调」的标记,不估。
    queued, queued_generation = _generation(
        client, kind="video", model=SEEDANCE, parameters={"duration_seconds": 4}, status="running",
    )

    for _ in range(2):  # 第二次启动什么都不该多记
        with unit_of_work() as db:
            reconcile_after_restart(db)

    with SessionLocal() as db:
        job = db.get(Job, interrupted)
        assert (job.status, job.error_key) == ("failed", "jobErr_backendRestart")
        assert runner.PROVIDER_CALL_FIELD not in (job.payload or {})
    [usage] = _usage(interrupted_generation)
    assert usage.status == "failed" and usage.cost_confidence == "estimated"
    assert usage.cost_micros == 2_000_000, "4 秒 × ¥0.5"
    assert usage.raw_usage["interrupted_by_restart"] is True
    assert _usage(queued_generation) == []
    assert queued
