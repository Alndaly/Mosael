"""Wan 图片 / Wan3 视频 / 旧版视频的参数与产物边界。"""

from __future__ import annotations

import json

import httpx2

from cloud.generation.adapters import JobContext
from cloud.generation.wan import ADAPTER, WanAdapter


def _context(**changes: object) -> JobContext:
    values: dict[str, object] = {
        "job_id": "job-1",
        "model_id": "model-1",
        "input": {"prompt": "a cat"},
        "capability": {},
        "base_url": "https://dashscope.example/",
        "upstream_model": "wanx2.1-t2i-turbo",
        "api_key": "sk-test",
        "config": {},
    }
    values.update(changes)
    return JobContext(**values)  # type: ignore[arg-type]


def test_wanx_image_submits_and_downloads_all_results():
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if request.url.path.endswith("/text2image/image-synthesis"):
            body = json.loads(request.read())
            assert body["model"] == "wanx2.1-t2i-turbo"
            assert body["input"]["prompt"] == "a cat"
            assert body["parameters"] == {"n": 2, "size": "1024*1024"}
            assert request.headers["X-DashScope-Async"] == "enable"
            assert request.headers["Authorization"] == "Bearer sk-test"
            return httpx2.Response(200, json={"output": {"task_id": "image-task", "task_status": "PENDING"}})
        if request.url.path.endswith("/tasks/image-task"):
            return httpx2.Response(200, json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [{"url": "https://cdn.example/a.png"}, {"url": "https://cdn.example/b.png"}],
                },
                "usage": {"image_count": 2},
            })
        return httpx2.Response(200, content=b"png", headers={"content-type": "image/png"})

    adapter = WanAdapter(transport=httpx2.MockTransport(handler))
    context = _context(input={"prompt": "a cat", "n": 2, "size": "1024x1024"})
    submitted = adapter.submit(context)
    assert submitted.status == "pending" and submitted.provider_job_id == "image-task"
    finished = adapter.poll(context, "image-task")
    assert finished.status == "succeeded", finished.error_detail
    assert [(one.filename, one.data) for one in finished.artifacts] == [("a.png", b"png"), ("b.png", b"png")]
    assert finished.usage == {"image": 2}
    assert ADAPTER.name == "wan"


def test_wan3_video_uses_media_and_reports_actual_duration():
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/video-generation/video-synthesis"):
            seen["body"] = json.loads(request.read())
            return httpx2.Response(200, json={"output": {"task_id": "video-task"}})
        if request.url.path.endswith("/tasks/video-task"):
            return httpx2.Response(200, json={
                "output": {"task_status": "SUCCEEDED", "video_url": "https://cdn.example/movie.mp4"},
                "usage": {"output_video_duration": 8},
            })
        return httpx2.Response(200, content=b"mp4", headers={"content-type": "video/mp4"})

    adapter = WanAdapter(transport=httpx2.MockTransport(handler))
    context = _context(
        upstream_model="wan3.0-video",
        input={
            "prompt": "run", "first_frame": "https://img.example/first.png",
            "last_frame": "https://img.example/last.png", "duration_seconds": 9,
            "resolution": "720p", "aspect_ratio": "9:16", "generate_audio": False,
        },
    )
    submitted = adapter.submit(context)
    assert submitted.status == "pending"
    body = seen["body"]
    assert body["input"]["media"] == [
        {"type": "first_frame", "url": "https://img.example/first.png"},
        {"type": "last_frame", "url": "https://img.example/last.png"},
    ]
    assert body["parameters"] == {"duration": 9, "resolution": "720P", "audio": False}
    finished = adapter.poll(context, "video-task")
    assert finished.status == "succeeded"
    assert finished.usage == {"second": 8}
    assert finished.artifacts[0].filename == "movie.mp4"


def test_legacy_video_maps_resolution_and_aspect_ratio_to_size():
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.read())
        return httpx2.Response(200, json={"output": {"task_id": "legacy"}})

    adapter = WanAdapter(transport=httpx2.MockTransport(handler))
    result = adapter.submit(_context(
        upstream_model="wan2.2-t2v-plus",
        input={"prompt": "sea", "resolution": "720p", "aspect_ratio": "9:16"},
    ))
    assert result.status == "pending"
    assert seen["body"]["parameters"] == {"duration": 5, "size": "720*1280"}


def test_wan_failure_and_cancel():
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/tasks/bad"):
            return httpx2.Response(200, json={"output": {"task_status": "FAILED", "message": "quota"}})
        if request.url.path.endswith("/tasks/video-task"):
            return httpx2.Response(200, json={"output": {"task_status": "RUNNING"}})
        if request.url.path.endswith("/cancel"):
            return httpx2.Response(200, json={})
        raise AssertionError(f"unexpected {request.url}")

    adapter = WanAdapter(transport=httpx2.MockTransport(handler))
    failed = adapter.poll(_context(upstream_model="wan3.0-video"), "bad")
    assert failed.status == "failed" and "quota" in failed.error_detail
    running = adapter.poll(_context(upstream_model="wan3.0-video"), "video-task")
    assert running.status == "running"
    assert adapter.cancel(_context(upstream_model="wan3.0-video"), "video-task") is True
