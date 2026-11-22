"""Cloud 生成必须留下远端回执、能接着取、能撤销、且重试不重复提交。

Cloud 的 `POST /gateway/v1/jobs` 是付费提交:HTTP 200 时 Cloud 已经预占积分。回执
(`/jobs/{id}`) 不从适配器局部变量里消失,而是交给运行器落进 `Job.payload.remote_task`;
后端重启或用户取消之后只轮询这一条。幂等键取自 `GenerationRequest.idempotency_key`,
同一份生成记录在“已提交、还没落回执”之间崩溃后重试时不会多建一个 Cloud 任务。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.ai.providers import get_generation_adapter
from app.ai.providers.adapters.mosael_cloud import jobs as cloud_jobs
from app.ai.providers.adapters.shared import polling
from app.ai.providers.contracts.generation import (
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    RemoteTaskWatch,
    watching_remote_tasks,
)


class _Response:
    def __init__(self, payload: Any = None, status: int = 200, content: bytes = b"") -> None:
        self._payload = payload
        self.status_code = status
        self.text = str(payload)
        self.content = content
        self.headers = {"content-type": "image/png"}

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, reads: list[dict[str, Any]], *, created: dict[str, Any] | None = None,
                 cancel: dict[str, Any] | None = None) -> None:
        self.reads = list(reads)
        self.created = created or {"job": {"id": "cloud-1", "status": "queued"}}
        self.cancel = cancel or {"job": {"status": "cancelled"}}
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[str] = []
        self.deletes: list[str] = []

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def post(self, path: str, json: dict[str, Any] | None = None, **_kwargs: Any) -> _Response:
        self.posts.append((path, json or {}))
        return _Response(self.created, status=201)

    def get(self, path: str) -> _Response:
        self.gets.append(path)
        return _Response(self.reads.pop(0) if self.reads else self.cancel)

    def delete(self, path: str) -> _Response:
        self.deletes.append(path)
        return _Response({}, status=204)


def _request(**overrides: Any) -> GenerationRequest:
    values = dict(kind="image", model="image-model", prompt="a cat", idempotency_key="generation-42")
    values.update(overrides)
    return GenerationRequest(**values)


def _context() -> GenerationAdapterContext:
    return GenerationAdapterContext(
        connection_id="c", vendor_id="mosael-cloud", api_key="mct_token",
        base_url="https://mosael.test/api/cloud/v1/gateway/v1",
    )


@pytest.fixture
def adapter(monkeypatch):
    instance = get_generation_adapter("mosael-cloud", "image")
    assert instance is not None

    class _AdapterClient(_Client):
        pass

    clients: list[_Client] = []

    def factory(_context):
        client = _AdapterClient(
            [
                {"job": {"status": "running"}},
                {
                    "job": {
                        "status": "succeeded",
                        "result": {"artifact_ids": ["artifact-1"]},
                        "usage": {"image": 2},
                        "charged_credits": 4,
                    }
                },
            ],
            cancel={"job": {"status": "cancelled"}},
        )
        clients.append(client)
        return client

    monkeypatch.setattr(instance, "_client", factory)

    def download(url: str, target: Path, **_kwargs: Any) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"png")
        return "image/png"

    monkeypatch.setattr(cloud_jobs, "download_to_path", download)
    real_poll = polling.poll_until_ready
    monkeypatch.setattr(
        cloud_jobs, "poll_until_ready",
        lambda client, path, extract, **kw: real_poll(client, path, extract, interval=0, **kw),
    )
    instance.clients = clients  # type: ignore[attr-defined]
    return instance


def test_generate_records_the_cloud_job_and_uses_a_stable_idempotency_key(adapter, tmp_path) -> None:
    remembered: list[str] = []
    watch = RemoteTaskWatch(remember=remembered.append, is_cancelled=lambda: False, settled=lambda _: None)
    with watching_remote_tasks(watch):
        result = adapter.generate(_request(), _context(), tmp_path)

    assert remembered == ["/jobs/cloud-1"], "提交后必须在开始轮询前交出远端回执"
    assert adapter.clients[0].posts == [
        ("/jobs", {
            "model": "image-model",
            "input": {"prompt": "a cat", "n": 1},
            "idempotency_key": "generation-42",
        })
    ], "同一份生成记录重试必须带同一个幂等键"
    assert [path for path in result.output_paths][0].suffix == ".png"
    assert result.raw_usage["usage"] == {"image": 2}


def test_resume_never_submits_again(adapter, tmp_path) -> None:
    client = _Client(
        [{"job": {"status": "succeeded", "result": {"artifact_ids": ["artifact-1"]}, "usage": {"image": 1}}}],
        cancel={"job": {"status": "cancelled"}},
    )
    adapter._client = lambda _context: client  # type: ignore[method-assign]
    result = adapter.resume("/jobs/cloud-1", _request(), _context(), tmp_path)
    assert client.posts == [], "resume 是接着取,绝不能重新提交"
    assert len(result.output_paths) == 1


def test_cancel_only_reports_true_when_cloud_already_cancelled(adapter, monkeypatch) -> None:
    adapter._client = lambda _context: _Client([], cancel={"job": {"status": "cancelled"}})  # type: ignore[method-assign]
    assert adapter.cancel_remote("/jobs/cloud-1", _request(), _context()) is True

    adapter._client = lambda _context: _Client([], cancel={"job": {"status": "cancel_requested"}})  # type: ignore[method-assign]
    assert adapter.cancel_remote("/jobs/cloud-1", _request(), _context()) is False, (
        "Cloud 只是接受了撤销请求,还没向上游确认;不能当成没扣费"
    )


def test_reported_usage_maps_cloud_units_and_keeps_charged_credits() -> None:
    adapter = get_generation_adapter("mosael-cloud", "video")
    assert adapter is not None
    usage = adapter.reported_usage({"usage": {"second": 3, "image": 1}, "charged_credits": 7})
    assert usage.units == {"video_second": 3, "image": 1}
    assert usage.observed == {"cloud_charged_credits": 7}


def test_cloud_job_failure_is_a_generation_error(adapter, tmp_path) -> None:
    adapter._client = lambda _context: _Client([  # type: ignore[method-assign]
        {"job": {"status": "failed", "error": {"detail": "upstream exploded"}}},
    ])
    with pytest.raises(GenerationAdapterError) as err:
        adapter.resume("/jobs/cloud-1", _request(), _context(), tmp_path)
    assert err.value.key == "providerErr_cloudFailed"
    assert err.value.params["detail"] == "upstream exploded"
