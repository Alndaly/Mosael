"""停下的生成,替记账跟远端任务时不再下成片、不占任务名额;跟到一半后端重启,接着跟、账照记(GEN-7)。

此前远端撤不掉时用「接着取」把它跟到终态,而接着取 = 轮询 + 下载:已经停下的视频照样整份下载、记完账再删掉,全程占着
一个任务名额。任务行已是「已取消」,重启的收尾不认它 —— 跟到一半重启,`cancelled_locally` 那一笔永远记不上。

不调真实接口:真实的方舟 Seedance 适配器 + httpx.MockTransport(含对象存储)。ADR 0019「停下 = 不要这一份」不变:
成片不进素材库,只是不再白下一遍。
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.http_retry import RetryingClient as RealClient
from app.core.unit_of_work import unit_of_work
from app.db.models import GeneratedAsset, Job, ProviderUsageEvent
from app.domain.generation import runner
from tests.test_interrupted_downloads_can_be_retrieved import SIGNED, _video_generation
from tests.util import module_time

USAGE = {"completion_tokens": 432000, "total_tokens": 432000}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import app.ai.providers.adapters.shared.polling as polling
    import app.core.http_retry as http_retry
    from app.ai import media_transfer

    monkeypatch.setattr(http_retry, "time", module_time(sleep=lambda *_: None))
    monkeypatch.setattr(polling, "time", module_time(sleep=lambda *_: None))
    monkeypatch.setattr(media_transfer, "time", module_time(sleep=lambda *_: None))


def _ark(monkeypatch, answer) -> dict[str, list]:
    """方舟 API + 对象存储。`answer(n)` 给第 n 次查询任务的回答。记下下载了几次、跟的时候占着几个任务名额。"""
    from types import SimpleNamespace

    from app.ai import media_transfer
    from app.ai.providers.adapters.bytedance.ark import video as ark
    from app.domain import jobs

    profile = SimpleNamespace(id=None, vendor="bytedance", api_key="sk-test", base_url="", extra={})
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: profile)
    monkeypatch.setattr(runner.provider_models, "model_id_for", lambda *a, **kw: "")
    seen: dict[str, list] = {"downloads": [], "gets": [], "slots": [], "following": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tos.example":
            seen["downloads"].append(str(request.url))
            return httpx.Response(200, content=b"mp4", headers={"content-type": "video/mp4"})
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-7"})
        seen["gets"].append(request.url.path)
        seen["slots"].append(jobs._runner._active)
        with SessionLocal() as db:
            job = db.scalars(select(Job).where(Job.kind == "ai_generation")).first()
            seen["following"].append(bool(((job.payload or {}).get("remote_task") or {}).get("following")))
        return httpx.Response(200, json=answer(len(seen["gets"])))

    transport = httpx.MockTransport(handler)
    for module in (ark, media_transfer):
        class Routed(RealClient):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(module, "RetryingClient", Routed)
    return seen


def _cancel(job_id: str) -> None:
    from app.domain.jobs import cancel_job

    with unit_of_work() as db:
        cancel_job(db, db.get(Job, job_id), by=None)


def _wait_for_usage(generation_id: str, timeout: float = 15.0) -> ProviderUsageEvent:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.source_id == generation_id)).first()
            if usage is not None:
                db.expunge(usage)
                return usage
        time.sleep(0.05)
    raise AssertionError("一直没记账")


def _payload(job_id: str) -> dict:
    with SessionLocal() as db:
        return dict(db.get(Job, job_id).payload or {})


def test_停下之后跟到远端做完_按回包记账_成片不下_也不占任务名额(monkeypatch) -> None:
    from tests.util import fresh_client

    client = fresh_client()
    _, job_id, generation_id = _video_generation(client)

    def answer(n: int) -> dict:
        if n == 1:
            _cancel(job_id)  # 第一次查询时用户点了停止
            return {"status": "running"}
        if n == 2:
            return {"status": "running"}  # 撤销之前先查一眼:在做,撤不掉
        return {"status": "succeeded", "content": {"video_url": SIGNED}, "usage": USAGE}

    seen = _ark(monkeypatch, answer)
    runner.start_generation_thread(generation_id)

    usage = _wait_for_usage(generation_id)
    assert seen["downloads"] == [], "已经停下的成片不该再整份下载一遍"
    assert (usage.status, usage.units.get("output_tokens")) == ("succeeded", 432000), "照服务商回报的用量记"
    assert usage.raw_usage.get("cancelled_locally") is True
    assert seen["slots"][0] == 1 and seen["slots"][-1] == 0, f"跟的那一段还占着任务名额:{seen['slots']}"
    assert seen["following"][-1] is True, "跟的时候要记下「正在跟」—— 这时重启,靠它接着跟"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _payload(job_id).get("remote_task", {}).get("following"):
        time.sleep(0.05)
    payload = _payload(job_id)
    assert "following" not in payload["remote_task"], "记完账要摘掉「正在跟」,否则重启还会再跟一遍"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "cancelled", "停下照旧是停下"
        assert db.scalars(select(GeneratedAsset).where(GeneratedAsset.job_id == job_id)).first() is None


def test_跟到一半后端重启_接着跟_账照记_成片不下(monkeypatch) -> None:
    from app.ai.providers.adapters.bytedance.ark.video import TASKS_PATH
    from tests.util import fresh_client

    client = fresh_client()
    _, job_id, generation_id = _video_generation(client)
    poll_path = f"{TASKS_PATH}/cgt-7"
    #: 上一个进程留下的样子:任务已停下,远端任务交出去了,正在替记账跟着。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        job.status = "cancelled"
        job.payload = {"remote_task": {"poll_path": poll_path, "following": True}}

    seen = _ark(monkeypatch, lambda _n: {"status": "succeeded", "content": {"video_url": SIGNED}, "usage": USAGE})
    with unit_of_work() as db:
        assert runner.reconcile_unsettled_charges(db) == 1

    usage = _wait_for_usage(generation_id)
    assert (usage.status, usage.units.get("output_tokens")) == ("succeeded", 432000)
    assert usage.raw_usage.get("cancelled_locally") is True
    assert seen["downloads"] == []
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _payload(job_id)["remote_task"].get("following"):
        time.sleep(0.05)
    assert "following" not in _payload(job_id)["remote_task"]

    #: 再启动一次:已经跟完的不再跟
    with unit_of_work() as db:
        assert runner.reconcile_unsettled_charges(db) == 0


def test_没被停下的照常下载成片(monkeypatch) -> None:
    """只等终态不下成片,只给停下之后的那一段 —— 正常的生成照旧要成片。"""
    from tests.util import fresh_client

    client = fresh_client()
    _, job_id, generation_id = _video_generation(client)
    seen = _ark(monkeypatch, lambda _n: {"status": "succeeded", "content": {"video_url": SIGNED}, "usage": USAGE})

    runner._run_generation(generation_id)

    assert len(seen["downloads"]) == 1
    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "succeeded"
