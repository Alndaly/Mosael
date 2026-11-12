"""通用异步任务:创建、预占、worker 提交/轮询、结果落盘与下载。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from cloud.config import CloudConfig
from cloud.domain import catalog, credits
from cloud.domain.channel_keys import new_channel_key
from cloud.generation.adapters import AdapterArtifact, AdapterResult, JobContext
from cloud.generation.service import run_one
from cloud.models import CloudGenerationJob, CloudModelPriceComponent, CloudUser, now
from conftest import RecordingSender, api, signed_in


class FakeJobAdapter:
    name = "fake"

    def __init__(self) -> None:
        self.submitted = 0
        self.polled = 0

    def submit(self, job: JobContext) -> AdapterResult:
        self.submitted += 1
        return AdapterResult(status="pending", provider_job_id="provider-1")

    def poll(self, job: JobContext, provider_job_id: str) -> AdapterResult:
        self.polled += 1
        return AdapterResult(
            status="succeeded",
            provider_job_id=provider_job_id,
            artifacts=[AdapterArtifact(filename="out.png", mime="image/png", data=b"png-bytes")],
            usage={"image": 1},
        )

    def cancel(self, job: JobContext, provider_job_id: str) -> None:
        pass


def _setup(tmp_path):
    from cloud.app import create_app

    app = create_app(
        CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False,
                    channel_key=new_channel_key()),
        code_sender=RecordingSender(),
    )
    with app.state.db.session() as db:
        model = catalog.upsert_model(
            db, model_id="image-model", label="Image Model", interaction="job",
            capability={"reservation": {"image": 1}},
        )
        price = catalog.set_price(db, model_id=model.id, input_per_1k=0, output_per_1k=0,
                                  effective_from=now() - timedelta(days=1))
        db.add(CloudModelPriceComponent(price_id=price.id, unit="image", credits_per_unit=2))
        provider = catalog.add_provider(db, app.state.config, name="fake-provider",
                                        base_url="https://fake.example/v1", api_key="sk-fake")
        provider.adapter = "fake"
        catalog.add_channel(db, model_id=model.id, provider_id=provider.id,
                            upstream_model="upstream-image", priority=0)
        db.commit()
    return app


def _desktop(app):
    client = TestClient(app)
    signed_in(client)
    secret = client.post(api("/device-tokens"), json={"name": "Mac"}).json()["secret"]
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {secret}"
    with app.state.db.session() as db:
        user = db.scalar(select(CloudUser))
        credits.gift(db, user, amount=100, days=30, note="test", at=now())
        db.commit()
    return client


def test_job_is_reserved_submitted_polled_and_downloaded(tmp_path):
    app = _setup(tmp_path)
    client = _desktop(app)
    adapter = FakeJobAdapter()

    created = client.post(api("/gateway/v1/jobs"), json={
        "model": "image-model", "input": {"prompt": "a cat"}, "idempotency_key": "job-1",
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["job"]["id"]

    with app.state.db.session() as db:
        assert run_one(db, config=app.state.config, adapters={"fake": adapter},
                       storage=app.state.artifact_storage) is True
        assert adapter.submitted == 1
        assert db.get(CloudGenerationJob, job_id).status == "submitted"
        job = db.get(CloudGenerationJob, job_id)
        job.next_poll_at = now() - timedelta(seconds=1)
        db.commit()

    with app.state.db.session() as db:
        assert run_one(db, config=app.state.config, adapters={"fake": adapter},
                       storage=app.state.artifact_storage) is True
        assert adapter.polled == 1

    finished = client.get(api(f"/gateway/v1/jobs/{job_id}"))
    assert finished.status_code == 200
    body = finished.json()["job"]
    assert body["status"] == "succeeded"
    artifact_id = body["result"]["artifact_ids"][0]
    downloaded = client.get(api(f"/gateway/v1/jobs/{job_id}/artifacts/{artifact_id}"))
    assert downloaded.status_code == 200
    assert downloaded.content == b"png-bytes"
    assert Path(tmp_path / "media").exists()


def test_openai_images_adapter_builds_artifacts_and_usage():
    import base64
    import httpx2
    from cloud.generation.openai_images import OpenAIImagesAdapter

    seen = {}
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx2.Response(200, json={"data": [{"b64_json": base64.b64encode(b"png").decode()}]})

    adapter = OpenAIImagesAdapter(transport=httpx2.MockTransport(handler))
    result = adapter.submit(JobContext(
        job_id="j1", model_id="m1", input={"prompt": "cat", "n": 1},
        capability={}, base_url="https://api.example/v1", upstream_model="gpt-image-2", api_key="sk-test", config={},
    ))
    assert result.status == "succeeded"
    assert result.usage == {"image": 1}
    assert result.artifacts[0].data == b"png"
    assert seen["url"] == "https://api.example/v1/images/generations"
    assert '"model":"gpt-image-2"' in seen["body"]


def test_kling_adapter_submits_polls_and_downloads(monkeypatch):
    import httpx2
    from cloud.generation.kling import KlingVideoAdapter

    calls = []
    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.method, str(request.url)))
        if request.method == "POST":
            return httpx2.Response(200, json={"code": 0, "data": {"task_id": "t1"}})
        if request.url.path.endswith("/t1"):
            return httpx2.Response(200, json={"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://cdn.example/v.mp4"}]}}})
        return httpx2.Response(200, content=b"mp4", headers={"content-type": "video/mp4"})

    adapter = KlingVideoAdapter(transport=httpx2.MockTransport(handler))
    ctx = JobContext(
        job_id="j", model_id="m", input={"prompt": "run", "duration_seconds": 5}, capability={},
        base_url="https://api.klingai.com", upstream_model="kling-v3", api_key="ak:sk", config={},
    )
    submitted = adapter.submit(ctx)
    assert submitted.status == "pending" and submitted.provider_job_id == "text2video:t1"
    finished = adapter.poll(ctx, submitted.provider_job_id or "")
    assert finished.status == "succeeded"
    assert finished.usage == {"second": 5}
    assert finished.artifacts[0].data == b"mp4"
    assert calls[0][1].endswith("/v1/videos/text2video")


def test_seedance_adapter_submits_polls_and_downloads():
    import httpx2
    from cloud.generation.seedance import SeedanceAdapter

    seen = []
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((request.method, str(request.url)))
        if request.method == "POST":
            return httpx2.Response(200, json={"id": "task-1"})
        if request.url.path.endswith("/task-1"):
            return httpx2.Response(200, json={"status": "succeeded", "content": {"video_url": "https://cdn.example/v.mp4"}})
        return httpx2.Response(200, content=b"mp4", headers={"content-type": "video/mp4"})

    adapter = SeedanceAdapter(transport=httpx2.MockTransport(handler))
    ctx = JobContext(
        job_id="j", model_id="m", input={"prompt": "waves", "duration_seconds": 5}, capability={},
        base_url="https://ark.example/api/v3", upstream_model="doubao-seedance-2-0", api_key="sk", config={},
    )
    submitted = adapter.submit(ctx)
    assert submitted.status == "pending" and submitted.provider_job_id == "task-1"
    finished = adapter.poll(ctx, "task-1")
    assert finished.status == "succeeded"
    assert finished.usage == {"second": 5}
    assert finished.artifacts[0].data == b"mp4"
    assert seen[0][1].endswith("/contents/generations/tasks")
