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
from cloud.models import (
    CloudGatewayCall,
    CloudGenerationJob,
    CloudMediaUpload,
    CloudModelPriceComponent,
    CloudUser,
    now,
)
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

    def cancel(self, job: JobContext, provider_job_id: str) -> bool:
        return True


def _setup(tmp_path, *, worker_enabled: bool = True):
    from cloud.app import create_app

    app = create_app(
        CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False,
                    channel_key=new_channel_key(), worker_enabled=worker_enabled),
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
    assert body["usage"] == {"image": 1}
    assert body["charged_credits"] == 2
    artifact_id = body["result"]["artifact_ids"][0]
    downloaded = client.get(api(f"/gateway/v1/jobs/{job_id}/artifacts/{artifact_id}"))
    assert downloaded.status_code == 200
    assert downloaded.content == b"png-bytes"
    assert Path(tmp_path / "media").exists()


def test_a_job_with_a_price_missing_its_reserved_unit_is_rejected(tmp_path):
    app = _setup(tmp_path)
    client = _desktop(app)
    with app.state.db.session() as db:
        model = catalog.upsert_model(
            db, model_id="unpriced-image", label="Unpriced image", interaction="job",
            capability={"reservation": {"image": 1}, "kind": "image"},
        )
        catalog.set_price(db, model_id=model.id, input_per_1k=2, output_per_1k=8,
                          effective_from=now() - timedelta(days=1))
        db.commit()

    rejected = client.post(api("/gateway/v1/jobs"), json={
        "model": "unpriced-image", "input": {"prompt": "a cat"}, "idempotency_key": "job-missing-price",
    })
    assert rejected.status_code == 422
    assert rejected.json()["error"] == "gateway_model_price_incomplete"


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


def test_media_upload_is_public_for_provider_fetch(tmp_path):
    app = _setup(tmp_path)
    client = _desktop(app)
    uploaded = client.post(
        api("/gateway/v1/uploads"), content=b"image-bytes",
        headers={"Content-Type": "image/png", "X-Filename": "frame.png"},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["mime"] == "image/png"
    token = body["url"].rsplit("/", 1)[-1]
    fetched = client.get(api(f"/gateway/v1/uploads/public/{token}"), follow_redirects=False)
    assert fetched.status_code == 200
    assert fetched.content == b"image-bytes"


class FakeDirectStorage:
    direct_upload = True
    def save(self, **_kwargs):
        raise AssertionError("not used")
    def presign_put(self, *, storage_key: str, mime: str, size: int, expires_in: int = 900) -> str:
        return f"https://r2.example/{storage_key}?signature=put"
    def presign_get(self, *, storage_key: str, expires_in: int = 3600) -> str:
        return f"https://r2.example/{storage_key}?signature=get"
    def public_url(self, storage_key: str) -> str:
        return f"https://media.mosael.test/{storage_key}"


def test_upload_returns_a_direct_r2_ticket_and_public_redirect(tmp_path):
    app = _setup(tmp_path)
    app.state.artifact_storage = FakeDirectStorage()
    client = _desktop(app)
    ticket = client.post(api("/gateway/v1/uploads/presign"), json={
        "filename": "frame.png", "mime": "image/png", "size": 11,
    })
    assert ticket.status_code == 201, ticket.text
    body = ticket.json()
    assert body["method"] == "PUT"
    assert body["upload_url"].startswith("https://r2.example/")
    assert body["url"].startswith("https://media.mosael.test/uploads/")
    with app.state.db.session() as db:
        row = db.get(CloudMediaUpload, body["id"])
        assert row is not None
        token = row.public_token
    fetched = client.get(api(f"/gateway/v1/uploads/public/{token}"), follow_redirects=False)
    assert fetched.status_code in {302, 307}
    assert fetched.headers["location"].startswith("https://media.mosael.test/")


def test_r2_storage_writes_objects_and_signs_direct_puts():
    from cloud.generation.adapters import AdapterArtifact
    from cloud.generation.storage import R2ArtifactStorage

    calls = []
    class FakeClient:
        def put_object(self, **kwargs): calls.append(("put", kwargs))
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            calls.append((operation, Params, ExpiresIn))
            return f"https://r2.example/{Params['Key']}"

    storage = R2ArtifactStorage(
        account_id="a", access_key_id="k", secret_access_key="s", bucket="mosael-cloud",
        public_base_url="https://media.mosael.com", client=FakeClient(),
    )
    stored = storage.save(user_id="u", job_id="j", artifact=AdapterArtifact(
        filename="out.png", mime="image/png", data=b"png",
    ))
    assert stored.storage_key.startswith("artifacts/u/j/")
    assert calls[0][1]["Bucket"] == "mosael-cloud"
    assert calls[0][1]["ContentType"] == "image/png"
    upload = storage.presign_put(storage_key="uploads/u/x-frame.png", mime="image/png", size=3)
    assert upload == "https://r2.example/uploads/u/x-frame.png"
    assert storage.public_url("uploads/u/x frame.png") == "https://media.mosael.com/uploads/u/x%20frame.png"


def test_cancel_after_submission_waits_and_only_refunds_when_provider_confirms(tmp_path):
    from cloud.models import CloudGatewayCall, now

    class PendingAdapter(FakeJobAdapter):
        def poll(self, job, provider_job_id):
            return AdapterResult(status="running", provider_job_id=provider_job_id)

    app = _setup(tmp_path)
    client = _desktop(app)
    adapter = PendingAdapter()
    created = client.post(api("/gateway/v1/jobs"), json={
        "model": "image-model", "input": {"prompt": "cat", "n": 1}, "idempotency_key": "cancel-1",
    })
    assert created.status_code == 201, created.text
    job_id = created.json()["job"]["id"]
    with app.state.db.session() as db:
        assert run_one(db, config=app.state.config, adapters={"fake": adapter}, storage=app.state.artifact_storage)
        job = db.get(CloudGenerationJob, job_id)
        job.next_poll_at = now() - timedelta(seconds=1)
        db.commit()
    with app.state.db.session() as db:
        assert run_one(db, config=app.state.config, adapters={"fake": adapter}, storage=app.state.artifact_storage)
        job = db.get(CloudGenerationJob, job_id)
        assert job.provider_job_id == "provider-1"
        call = db.get(CloudGatewayCall, job.call_id)
        assert call.status == "reserved"

    assert client.delete(api(f"/gateway/v1/jobs/{job_id}")).status_code == 204
    with app.state.db.session() as db:
        job = db.get(CloudGenerationJob, job_id)
        assert job.status == "cancel_requested"
        assert db.get(CloudGatewayCall, job.call_id).status == "reserved"
    with app.state.db.session() as db:
        assert run_one(db, config=app.state.config, adapters={"fake": adapter}, storage=app.state.artifact_storage)
        job = db.get(CloudGenerationJob, job_id)
        assert job.status == "cancelled"
        assert db.get(CloudGatewayCall, job.call_id).status == "released"


def test_no_worker_rejects_new_jobs_without_reserving_credits(tmp_path):
    app = _setup(tmp_path, worker_enabled=False)
    client = _desktop(app)
    rejected = client.post(api("/gateway/v1/jobs"), json={
        "model": "image-model", "input": {"prompt": "a cat"}, "idempotency_key": "no-worker",
    })
    assert rejected.status_code == 503
    assert rejected.json()["error"] == "generation_worker_unavailable"
    with app.state.db.session() as db:
        assert db.scalar(select(CloudGenerationJob)) is None
        assert db.scalar(select(CloudGatewayCall)) is None, "被拒绝的请求不能留下预占"


def test_an_existing_job_is_replayable_even_when_the_worker_is_off(tmp_path):
    """重放同一个幂等键要拿回旧任务;不能因为 worker 后来关了就把一次已存在的请求变成 503。"""
    from cloud.app import create_app

    app = _setup(tmp_path, worker_enabled=True)
    client = _desktop(app)
    secret = client.headers["Authorization"].removeprefix("Bearer ")
    created = client.post(api("/gateway/v1/jobs"), json={
        "model": "image-model", "input": {"prompt": "a cat"}, "idempotency_key": "replay-me",
    })
    assert created.status_code == 201
    job_id = created.json()["job"]["id"]

    offline = create_app(
        CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False,
                    channel_key=app.state.config.channel_key, worker_enabled=False),
        code_sender=RecordingSender(),
    )
    replay = TestClient(offline)
    replay.headers["Authorization"] = f"Bearer {secret}"
    again = replay.post(api("/gateway/v1/jobs"), json={
        "model": "image-model", "input": {"prompt": "a cat"}, "idempotency_key": "replay-me",
    })
    assert again.status_code == 201, again.text
    assert again.json()["job"]["id"] == job_id


def test_uncertain_submit_is_reconciled_without_resubmitting(tmp_path):
    from cloud.generation import service as generation_service

    app = _setup(tmp_path, worker_enabled=False)
    _desktop(app)
    with app.state.db.session() as db:
        user = db.scalar(select(CloudUser))
        call = CloudGatewayCall(user_id=user.id, model_id="image-model", reserved=9, created_at=now())
        db.add(call)
        db.flush()
        credits.reserve(db, call, at=now())
        job = CloudGenerationJob(
            user_id=user.id, model_id="image-model", call_id=call.id, idempotency_key="uncertain",
            status="submitting", input={}, capability={}, price_snapshot={},
            submit_started_at=now(), created_at=now(), updated_at=now(),
        )
        db.add(job)
        db.commit()
        job_id, call_id = job.id, call.id

    with app.state.db.session() as db:
        assert generation_service.reconcile_uncertain_submits(db, at=now()) == 1
        db.commit()

    with app.state.db.session() as db:
        job = db.get(CloudGenerationJob, job_id)
        call = db.get(CloudGatewayCall, call_id)
        assert job.status == "failed"
        assert job.error_code == "submit_outcome_unknown"
        assert call.status == "settled" and call.charged == call.reserved, "结局不明不能白送一次上游生成"


def test_queued_job_expires_and_releases_its_reservation(tmp_path):
    from cloud.generation import service as generation_service

    app = _setup(tmp_path, worker_enabled=False)
    _desktop(app)
    with app.state.db.session() as db:
        user = db.scalar(select(CloudUser))
        call = CloudGatewayCall(user_id=user.id, model_id="image-model", reserved=5, created_at=now())
        db.add(call)
        db.flush()
        credits.reserve(db, call, at=now())
        old = now() - timedelta(hours=2)
        job = CloudGenerationJob(
            user_id=user.id, model_id="image-model", call_id=call.id, idempotency_key="queued-old",
            status="queued", input={}, capability={}, price_snapshot={},
            created_at=old, updated_at=old,
        )
        db.add(job)
        db.commit()
        job_id, call_id = job.id, call.id

    with app.state.db.session() as db:
        assert generation_service.expire_queued_jobs(db, at=now()) == 1
        db.commit()

    with app.state.db.session() as db:
        job = db.get(CloudGenerationJob, job_id)
        call = db.get(CloudGatewayCall, call_id)
        assert job.status == "failed" and job.error_code == "worker_unavailable"
        assert call.status == "released" and call.charged == 0


def test_future_lease_is_not_claimed_by_another_worker(tmp_path):
    from cloud.generation import service as generation_service

    app = _setup(tmp_path, worker_enabled=False)
    _desktop(app)
    with app.state.db.session() as db:
        user = db.scalar(select(CloudUser))
        call = CloudGatewayCall(user_id=user.id, model_id="image-model", reserved=1, created_at=now())
        db.add(call)
        db.flush()
        job = CloudGenerationJob(
            user_id=user.id, model_id="image-model", call_id=call.id, idempotency_key="leased",
            status="queued", input={}, capability={}, price_snapshot={},
            lease_until=now() + timedelta(minutes=5), created_at=now(), updated_at=now(),
        )
        db.add(job)
        db.commit()

    with app.state.db.session() as db:
        assert generation_service._claimed(db, now()) is None
