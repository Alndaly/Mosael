"""等远端任务时网络抖一下,不再放弃付费任务(ADR 0019 修订)。

此前 `poll_until_ready` 里任何一步抛异常都直接跳出循环:Seedance 提交拿到任务号之后,合盖 / 换 Wi-Fi 十几秒
(GET 自己重试 3 次也用完了)→ 任务判失败、账记「未扣费」、重启也不接 —— 而远端下一次轮询其实就成功了,照样扣费。
用户照「未扣费」的提示重来,就是再付一次。

现在:连接层错误、429 / 5xx、回包不是 JSON 对象(代理回了一页 HTML)都退避再问,任务上写「正在第 n 次重新连接」;
只有确定性的错(401 / 404、服务商判了失败)才结束 —— 结束时远端任务没了结,按请求侧计量估一笔,不记「未扣费」。
不调真实接口:真实的方舟 Seedance 适配器 + httpx.MockTransport。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import GeneratedAsset, GenerationJob, Job, ProviderUsageEvent

SEEDANCE = "doubao-seedance-2-0-260128"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import app.ai.providers.adapters.shared.polling as polling
    import app.core.http_retry as http_retry

    monkeypatch.setattr(http_retry.time, "sleep", lambda *_: None)
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)


def _video_generation() -> tuple[str, str]:
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
        db.add(job)
        db.flush()
        generation = GenerationJob(
            workspace_id=workspace, job_id=job.id, kind="video", provider="bytedance", model=SEEDANCE,
            request={"prompt": "一只猫在跑", "parameters": {"duration_seconds": 5, "resolution": "720p"}},
        )
        db.add(generation)
        db.commit()
        return job.id, generation.id


def _route_seedance(monkeypatch, handler) -> None:
    from app.ai.providers.adapters.bytedance.ark import video as ark
    from app.domain.generation import runner

    profile = SimpleNamespace(id=None, vendor="bytedance", api_key="sk-test", base_url="", extra={})
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: profile)
    monkeypatch.setattr(runner.provider_models, "model_id_for", lambda *a, **kw: "")
    transport = httpx.MockTransport(handler)

    class Routed(ark.RetryingClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ark, "RetryingClient", Routed)
    monkeypatch.setattr(ark, "download_to_path", lambda url, target, **kw: target.write_bytes(b"mp4"))


def _message_key(job_id: str) -> str:
    with SessionLocal() as db:
        return db.get(Job, job_id).message_key


def _usage(job_id: str) -> list[ProviderUsageEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)))


@pytest.mark.parametrize(
    "outage",
    [
        pytest.param(lambda request: (_ for _ in ()).throw(httpx.ConnectError("unreachable", request=request)),
                     id="合盖断网"),
        pytest.param(lambda request: httpx.Response(502, text="Bad Gateway"), id="查询接口502"),
        pytest.param(lambda request: httpx.Response(429, json={"error": {"code": "RateLimit"}}), id="查询接口限流"),
        pytest.param(lambda request: httpx.Response(200, text="<html>proxy login</html>"), id="代理回了一页HTML"),
    ],
)
def test_等远端时一阵子问不到_接着问_拿到成片(monkeypatch, outage) -> None:
    from app.domain.generation import runner

    job_id, generation_id = _video_generation()
    seen: dict[str, Any] = {"polls": 0, "posts": 0, "message_during_outage": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["posts"] += 1
            return httpx.Response(200, json={"id": "cgt-123"})
        seen["polls"] += 1
        if seen["polls"] == 1:
            return httpx.Response(200, json={"status": "running"})
        # 十几次问不到:远超 GET 自己那 3 次重试,此前在第 2 次轮询就整条放弃了。
        if seen["polls"] <= 16:
            if seen["polls"] == 16:
                seen["message_during_outage"] = _message_key(job_id)
            return outage(request)
        return httpx.Response(200, json={"status": "succeeded", "content": {"video_url": "https://tos/x.mp4"}})

    _route_seedance(monkeypatch, handler)
    runner._run_generation(generation_id)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "succeeded", job.error
        assert db.scalars(select(GeneratedAsset).where(GeneratedAsset.job_id == job_id)).first() is not None
    assert seen["posts"] == 1, "等远端时问不到,不该重新提交"
    assert seen["message_during_outage"] == "jobMsg_generationReconnecting", "断着的时候任务上要说「正在重新连接」"
    assert [event.status for event in _usage(job_id)] == ["succeeded"]


@pytest.mark.parametrize("status", [401, 404])
def test_回执之后出了确定性的错_不记未扣费(monkeypatch, status: int) -> None:
    """钥匙被换掉(401)、远端说没这个任务(404):再问也一样,结束等待。但任务交出去了、没了结 —— 那一次多半在扣钱,
    按请求侧计量估一笔并写明为什么,不是「未扣费」;之后可以「重新取回」(见 test_interrupted_downloads_can_be_retrieved)。"""
    from app.domain.generation import runner

    job_id, generation_id = _video_generation()
    polls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-401"})
        polls.append(status)
        return httpx.Response(status, json={"error": {"code": "AuthenticationError", "message": "bad key"}})

    _route_seedance(monkeypatch, handler)
    runner._run_generation(generation_id)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed"
        assert runner.remote_poll_path(job).endswith("cgt-401")
    assert len(polls) <= 4, "确定性的错不该一直问下去(GET 自己的 3 次重试之外不再退避)"
    events = _usage(job_id)
    assert len(events) == 1
    assert events[0].cost_confidence != "not_billed", "远端任务交出去了、没了结,不能记成「未扣费」"
    assert events[0].raw_usage.get("unsettled_remote_task", "").endswith("cgt-401")


def test_断网时点了停止_不再干等退避(monkeypatch) -> None:
    """退避最长一分钟,每一秒都看一眼取消:用户点了停止,不该再等完这一分钟才停。"""
    from app.ai.providers.adapters.shared import polling
    from app.ai.providers.contracts.generation import GenerationAdapterError, RemoteTaskWatch, watching_remote_tasks

    slept: list[float] = []
    monkeypatch.setattr(polling.time, "sleep", lambda seconds: slept.append(seconds))
    state = {"cancelled": False, "asks": 0}

    class Offline:
        def get(self, path: str):
            state["asks"] += 1
            if state["asks"] == 6:
                state["cancelled"] = True  # 第 6 次没问到时用户点了停止
            raise httpx.ConnectError("unreachable", request=httpx.Request("GET", "https://ark.test" + path))

    watch = RemoteTaskWatch(remember=lambda _p: None, is_cancelled=lambda: state["cancelled"], settled=lambda _p: None)
    with watching_remote_tasks(watch), pytest.raises(GenerationAdapterError) as caught:
        polling.poll_until_ready(Offline(), "/tasks/cgt-1", lambda payload: None)
    assert caught.value.key == "providerErr_cancelled"
    assert state["asks"] == 6
    assert max(slept) <= 1.0, "退避要一秒一秒地等、每秒看一眼取消"
