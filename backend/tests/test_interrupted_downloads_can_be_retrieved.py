"""成片下载断了,付过钱的成片不再丢:先接着下,接不上就说人话,并且能「重新取回」(ADR 0019 修订)。

此前服务商做完、扣了费,下载成片时连接断一下:整条任务失败,报「ARK 请求失败:peer closed connection…」(像是供应商
出了错),回执还在但任务已是 failed,重启不接、界面上也没有入口 —— 用户唯一的路是重新生成,也就是再付一次。

现在:
- 下到一半断了从断的地方接着下(Range),对面不认 Range 就从头再来,链接过期这类直接说清;
- 接不上时任务说「服务商已经生成好了……点『重新取回』」,不说「供应商请求失败」;
- 「重新取回」不重新提交,建一个新任务接着取,成片照常入库;成功那一条账接替失败那一条,花费不被加两遍。
不调真实接口:真实的方舟 Seedance 适配器 + httpx.MockTransport(含对象存储下载)。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.ai import media_transfer
from app.core.http_retry import RetryingClient as RealClient
from app.core.db import SessionLocal
from app.db.models import GeneratedAsset, GenerationJob, Job, ProviderUsageEvent
from tests.util import module_time

SEEDANCE = "doubao-seedance-2-0-260128"
VIDEO = bytes(range(256)) * 4096  # 1 MiB 的「成片」
SIGNED = "https://tos.example/out/x.mp4?X-Tos-Signature=SECRET-SIGNATURE"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import app.ai.providers.adapters.shared.polling as polling
    import app.core.http_retry as http_retry

    monkeypatch.setattr(http_retry, "time", module_time(sleep=lambda *_: None))
    monkeypatch.setattr(polling, "time", module_time(sleep=lambda *_: None))
    monkeypatch.setattr(media_transfer, "time", module_time(sleep=lambda *_: None))


class _Breaks(httpx.SyncByteStream):
    """先发一截,然后像对面掉线那样断掉。"""

    def __init__(self, chunk: bytes) -> None:
        self.chunk = chunk

    def __iter__(self):
        yield self.chunk
        raise httpx.ReadError("peer closed connection without sending complete message body")


def _storage(*, breaks: int, ranges: bool = True):
    """假对象存储:前 `breaks` 次连接各发 64 KiB 就断;认 Range 的话从断点续,不认就每次给整份。"""
    state = {"connections": 0, "ranges": []}

    def serve(request: httpx.Request) -> httpx.Response:
        state["connections"] += 1
        wanted = request.headers.get("range", "")
        state["ranges"].append(wanted)
        start = int(re.match(r"bytes=(\d+)-", wanted).group(1)) if (wanted and ranges) else 0
        body = VIDEO[start:]
        headers = {"content-type": "video/mp4", "content-length": str(len(body))}
        status = 200
        if wanted and ranges:
            status = 206
            headers["content-range"] = f"bytes {start}-{len(VIDEO) - 1}/{len(VIDEO)}"
        if state["connections"] <= breaks:
            return httpx.Response(status, headers=headers, stream=_Breaks(body[: 64 * 1024]))
        return httpx.Response(status, headers=headers, content=body)

    return serve, state


def _route(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class Routed(RealClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(media_transfer, "RetryingClient", Routed)


# --------------------------------------------------------------------- 下载本身


def test_下到一半断了_从断点接着下(monkeypatch, tmp_path: Path) -> None:
    serve, state = _storage(breaks=3)
    _route(monkeypatch, serve)
    target = tmp_path / "out.mp4"
    assert media_transfer.download_to_path(SIGNED, target) == "video/mp4"
    assert target.read_bytes() == VIDEO
    assert state["ranges"] == ["", "bytes=65536-", "bytes=131072-", "bytes=196608-"], "要从断的地方接着要,不是从头"
    assert not target.with_name("out.mp4.part").exists()


def test_对面不认_Range_就从头再下(monkeypatch, tmp_path: Path) -> None:
    serve, state = _storage(breaks=2, ranges=False)
    _route(monkeypatch, serve)
    target = tmp_path / "out.mp4"
    media_transfer.download_to_path(SIGNED, target)
    assert target.read_bytes() == VIDEO, "对面回了整份(200)时,拼在半截后面就成了坏文件"


def test_接不上就说下载失败_不带签名链接_也不是_httpx_的异常(monkeypatch, tmp_path: Path) -> None:
    serve, _ = _storage(breaks=99)
    _route(monkeypatch, serve)
    target = tmp_path / "out.mp4"
    with pytest.raises(media_transfer.MediaDownloadError) as caught:
        media_transfer.download_to_path(SIGNED, target)
    assert not isinstance(caught.value, httpx.HTTPError), "适配器会把 httpx 异常说成「供应商请求失败」"
    assert not target.exists() and not target.with_name("out.mp4.part").exists()

    _route(monkeypatch, lambda request: httpx.Response(403, text="SignatureExpired"))
    with pytest.raises(media_transfer.MediaDownloadError) as expired:
        media_transfer.download_to_path(SIGNED, target)
    assert "SECRET-SIGNATURE" not in str(expired.value) and "403" in str(expired.value)


# --------------------------------------------------------------------- 运行器 + 重新取回


def _seedance(monkeypatch, *, storage) -> dict[str, int]:
    """方舟 API(提交 / 轮询)和对象存储(下载)。返回提交次数的计数。"""
    from app.ai.providers.adapters.bytedance.ark import video as ark
    from app.domain.generation import runner

    profile = SimpleNamespace(id=None, vendor="bytedance", api_key="sk-test", base_url="", extra={})
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: profile)
    monkeypatch.setattr(runner.provider_models, "model_id_for", lambda *a, **kw: "")
    seen = {"posts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tos.example":
            return storage(request)
        if request.method == "POST":
            seen["posts"] += 1
            return httpx.Response(200, json={"id": "cgt-9"})
        return httpx.Response(200, json={"status": "succeeded", "content": {"video_url": SIGNED},
                                          "usage": {"completion_tokens": 432000, "total_tokens": 432000}})

    transport = httpx.MockTransport(handler)
    for module in (ark, media_transfer):
        class Routed(RealClient):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(module, "RetryingClient", Routed)
    return seen


def _video_generation(client) -> tuple[str, str, str]:
    from tests.util import user_id

    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={}, created_by=user_id())
        db.add(job)
        db.flush()
        generation = GenerationJob(
            workspace_id=workspace, job_id=job.id, kind="video", provider="bytedance", model=SEEDANCE,
            request={"prompt": "猫", "parameters": {"duration_seconds": 10, "resolution": "1080p"}},
        )
        db.add(generation)
        db.commit()
        return workspace, job.id, generation.id


def _history(client, workspace: str) -> dict:
    rows = client.get("/api/generation/jobs", params={"workspace_id": workspace}).json()
    assert len(rows) == 1
    return rows[0]


def _wait(job_id: str, timeout: float = 15.0) -> Job:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status not in ("queued", "running"):
                return job
        time.sleep(0.05)
    raise AssertionError("取回的任务没有落终态")


def _usage(generation_id: str) -> list[ProviderUsageEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.source_id == generation_id)))


def test_下载接不上_说人话_点重新取回_不重新提交_账只记一笔(monkeypatch) -> None:
    from tests.util import fresh_client
    from app.domain.generation import runner

    client = fresh_client()
    workspace, first_job, generation_id = _video_generation(client)

    #: 第一次:对象存储一直断(接 5 次都接不上)
    serve, _ = _storage(breaks=99)
    seen = _seedance(monkeypatch, storage=serve)
    runner._run_generation(generation_id)

    with SessionLocal() as db:
        job = db.get(Job, first_job)
        assert job.status == "failed"
        assert job.error_key == "genErr_resultNotCollected", "下载断了不该说成「供应商请求失败」"
    record = _history(client, workspace)
    assert "重新取回" in record["error"] and "SECRET-SIGNATURE" not in record["error"]
    assert record["retrievable"] is True
    failed = _usage(generation_id)
    assert [event.status for event in failed] == ["failed"]
    assert failed[0].units.get("output_tokens") == 432000, "服务商回报扣了多少,失败那一条照它记"

    #: 重新取回:对象存储恢复了。下载那一刻看一眼任务上那句话 —— 要说「正在重新取回」,不是被换成笼统的「生成中」。
    serve, _ = _storage(breaks=0)
    said_while_retrieving: list[str] = []

    def storage(request: httpx.Request) -> httpx.Response:
        with SessionLocal() as db:
            current = db.get(Job, db.get(GenerationJob, generation_id).job_id)
            said_while_retrieving.append(current.message_key)
        return serve(request)

    seen = _seedance(monkeypatch, storage=storage)
    response = client.post(f"/api/generation/jobs/{generation_id}/retrieve")
    assert response.status_code == 200, response.text
    second_job = response.json()["job"]["id"]
    assert second_job != first_job, "失败的任务是终态,取回建一个新任务,不复活旧的"
    job = _wait(second_job)
    assert job.status == "succeeded", job.error
    assert seen["posts"] == 0, "重新取回不该重新提交"
    assert said_while_retrieving[:1] == ["jobMsg_generationRetrieving"]

    with SessionLocal() as db:
        assert db.get(Job, first_job).status == "failed", "旧任务留在历史里"
        assets = list(db.scalars(select(GeneratedAsset).where(GeneratedAsset.job_id == second_job)))
        assert len(assets) == 1
    record = _history(client, workspace)
    assert record["result_asset_id"] == assets[0].asset_id and record["error"] is None
    assert record["retrievable"] is False
    events = _usage(generation_id)
    assert [event.status for event in events] == ["succeeded"], "同一次服务商调用记了两笔,花费会被加两遍"
    assert events[0].raw_usage["replaces_failed_attempt"]["status"] == "failed"
    assert events[0].units.get("output_tokens") == 432000

    #: 已经取回过了:再点是 409
    assert client.post(f"/api/generation/jobs/{generation_id}/retrieve").status_code == 409


def test_停下的和别人的都取不回(monkeypatch) -> None:
    from tests.util import fresh_client, second_client
    from app.domain.jobs import CANCELLED_ERROR_KEY

    client = fresh_client()
    workspace, job_id, generation_id = _video_generation(client)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.status = "failed"
        job.payload = {"remote_task": {"poll_path": "/contents/generations/tasks/cgt-1"}}
        db.commit()
    other = second_client()
    assert other.post(f"/api/generation/jobs/{generation_id}/retrieve").status_code == 404, "别的工作区的人看不见它"

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.error_key = CANCELLED_ERROR_KEY  # 用户点了停止:这一份他不要了
        db.commit()
    assert _history(client, workspace)["retrievable"] is False
    assert client.post(f"/api/generation/jobs/{generation_id}/retrieve").status_code == 409


def test_同步接口下载断了_说只能重来_不摆重新取回(monkeypatch, tmp_path) -> None:
    """同步接口没有远端任务可以再问(ADR 0019/0022):话要说对 —— 服务商做完了、多半扣了钱,只能重新生成。"""
    from tests.util import fresh_client
    from app.ai.providers.adapters.openai import image as openai_image
    from app.domain.generation import runner

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
        db.add(job)
        db.flush()
        generation = GenerationJob(workspace_id=workspace, job_id=job.id, kind="image", provider="openai-compatible",
                                   model="gpt-image-1", request={"prompt": "猫", "parameters": {"num_images": 1}})
        db.add(generation)
        db.commit()
        job_id, generation_id = job.id, generation.id
    profile = SimpleNamespace(id=None, vendor="openai-compatible", api_key="k", base_url="https://relay.example/v1",
                              extra={})
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: profile)
    monkeypatch.setattr(runner.provider_models, "model_id_for", lambda *a, **kw: "")
    serve, _ = _storage(breaks=99)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tos.example":
            return serve(request)
        return httpx.Response(200, json={"data": [{"url": SIGNED}]})

    transport = httpx.MockTransport(handler)
    for module in (openai_image, media_transfer):
        class Routed(RealClient):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(module, "RetryingClient", Routed)

    runner._run_generation(generation_id)
    with SessionLocal() as db:
        assert db.get(Job, job_id).error_key == "genErr_resultNotCollectedNoReceipt"
    assert _history(client, workspace)["retrievable"] is False
    [event] = _usage(generation_id)
    assert event.cost_confidence != "not_billed", "服务商做完了的,不会是免费的"
