"""ComfyUI 适配器的真实 HTTP 形状、产物收集与失败边界。"""

from __future__ import annotations

import base64
import json

import httpx2
import pytest

from cloud.generation.adapters import JobContext
from cloud.generation.comfyui import ADAPTER, ComfyUIAdapter


def _config(*, prompt_binding: str | None = "6.inputs.text") -> dict:
    bindings: dict[str, object] = {
        "n": "5.inputs.batch_size",
        "aspect_ratio": "3.inputs.options.ratio",
        "first_frame": "10.inputs.image",
        "reference_images": ["11.inputs.image", "12.inputs.image"],
    }
    if prompt_binding is not None:
        bindings["prompt"] = prompt_binding
    return {
        "workflows": {
            "portrait": {
                "prompt": {
                    "3": {"inputs": {"options": {"ratio": "1:1"}}},
                    "5": {"inputs": {"batch_size": 1}},
                    "6": {"inputs": {"text": "original"}},
                    "10": {"inputs": {"image": "first.png"}},
                    "11": {"inputs": {"image": "ref-a.png"}},
                    "12": {"inputs": {"image": "ref-b.png"}},
                },
                "bindings": bindings,
            }
        }
    }


def _context(**changes: object) -> JobContext:
    values: dict[str, object] = {
        "job_id": "job-1",
        "model_id": "model-1",
        "input": {"prompt": "a cat", "n": 2, "aspect_ratio": "16:9"},
        "capability": {},
        "base_url": "https://comfy.example/",
        "upstream_model": "portrait",
        "api_key": "secret",
        "config": _config(),
    }
    values.update(changes)
    return JobContext(**values)  # type: ignore[arg-type]


def test_submit_binds_graph_without_mutating_config_and_authenticates():
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx2.Response(200, json={"prompt_id": "prompt-1"})

    context = _context()
    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    result = adapter.submit(context)

    assert result.status == "pending"
    assert result.provider_job_id == "prompt-1"
    assert seen["url"] == "https://comfy.example/prompt"
    assert seen["authorization"] == "Bearer secret"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["client_id"] == "job-1"
    graph = body["prompt"]
    assert graph["6"]["inputs"]["text"] == "a cat"
    assert graph["5"]["inputs"]["batch_size"] == 2
    assert graph["3"]["inputs"]["options"]["ratio"] == "16:9"
    assert context.config["workflows"]["portrait"]["prompt"]["6"]["inputs"]["text"] == "original"
    assert ADAPTER.name == "comfyui"


def test_submit_omits_empty_authorization_and_requires_prompt_binding():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"prompt_id": "p"})

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    submitted = adapter.submit(_context(api_key=""))
    assert submitted.status == "pending"
    assert "authorization" not in requests[0].headers

    missing = adapter.submit(_context(config=_config(prompt_binding=None)))
    assert missing.status == "failed"
    assert missing.error_code == "comfyui_prompt_binding"
    assert len(requests) == 1


def test_submit_downloads_and_uploads_all_bound_images():
    uploads: list[bytes] = []
    graph: dict = {}
    source_authorization: list[str | None] = []
    encoded = base64.b64encode(b"data-image").decode()

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url.startswith("https://assets.example/"):
            source_authorization.append(request.headers.get("authorization"))
            if url.endswith("first.png"):
                return httpx2.Response(200, content=b"first-image", headers={"content-type": "image/png"})
            return httpx2.Response(200, content=b"remote-reference", headers={"content-type": "image/jpeg"})
        if url == "https://comfy.example/upload/image":
            assert request.headers["authorization"] == "Bearer secret"
            assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
            uploads.append(request.read())
            return httpx2.Response(200, json={"name": f"uploaded-{len(uploads)}.png", "type": "input"})
        if url == "https://comfy.example/prompt":
            graph.update(json.loads(request.read())["prompt"])
            return httpx2.Response(200, json={"prompt_id": "images-job"})
        raise AssertionError(f"unexpected request: {request.method} {url}")

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    result = adapter.submit(_context(input={
        "prompt": "portrait",
        "first_frame": "https://assets.example/first.png",
        "reference_images": [
            f"data:image/png;base64,{encoded}",
            "https://assets.example/reference.jpg",
        ],
    }))

    assert result.status == "pending", result.error_detail
    assert result.provider_job_id == "images-job"
    assert len(uploads) == 3
    assert b'filename="first.png"' in uploads[0] and b"first-image" in uploads[0]
    assert b"data-image" in uploads[1]
    assert b'filename="reference.jpg"' in uploads[2] and b"remote-reference" in uploads[2]
    assert graph["10"]["inputs"]["image"] == "uploaded-1.png"
    assert graph["11"]["inputs"]["image"] == "uploaded-2.png"
    assert graph["12"]["inputs"]["image"] == "uploaded-3.png"
    assert source_authorization == [None, None]


def test_submit_rejects_excess_reference_images_without_dropping_them():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no HTTP request should be made")

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    result = adapter.submit(_context(input={
        "prompt": "three refs",
        "reference_images": ["data:image/png;base64,QQ=="] * 3,
    }))
    assert result.status == "failed"
    assert result.error_code == "comfyui_reference_images"


def test_poll_returns_running_then_downloads_every_output_with_usage():
    history_calls = 0
    views: list[httpx2.Request] = []
    media = {
        "one.png": (b"png", "image/png"),
        "two.gif": (b"gif", "image/gif"),
        "movie.mp4": (b"mp4", "application/octet-stream"),
        "sound.wav": (b"wav", "audio/wav"),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal history_calls
        if request.url.path == "/history/prompt-1":
            history_calls += 1
            assert request.headers["authorization"] == "Bearer secret"
            if history_calls == 1:
                return httpx2.Response(200, json={"prompt-1": {"status": {"completed": False}}})
            return httpx2.Response(200, json={
                "prompt-1": {
                    "status": {"status_str": "success", "completed": True},
                    "outputs": {
                        "9": {
                            "images": [{"filename": "one.png", "subfolder": "out", "type": "output"}],
                            "gifs": [{"filename": "two.gif", "subfolder": "", "type": "output"}],
                        },
                        "10": {"videos": [{"filename": "movie.mp4", "type": "output"}]},
                        "11": {"audio": [{"filename": "sound.wav", "type": "output"}]},
                    },
                }
            })
        if request.url.path == "/view":
            views.append(request)
            content, mime = media[request.url.params["filename"]]
            return httpx2.Response(200, content=content, headers={"content-type": mime})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    context = _context(input={"prompt": "cat", "duration_seconds": 7})
    running = adapter.poll(context, "prompt-1")
    assert running.status == "running"
    assert running.provider_job_id == "prompt-1"

    finished = adapter.poll(context, "prompt-1")
    assert finished.status == "succeeded", finished.error_detail
    assert [(one.filename, one.mime, one.data) for one in finished.artifacts] == [
        ("one.png", "image/png", b"png"),
        ("two.gif", "image/gif", b"gif"),
        ("movie.mp4", "video/mp4", b"mp4"),
        ("sound.wav", "audio/wav", b"wav"),
    ]
    assert finished.usage == {"image": 2, "second": 7}
    assert len(views) == 4
    assert dict(views[0].url.params) == {"filename": "one.png", "subfolder": "out", "type": "output"}
    assert all(request.headers["authorization"] == "Bearer secret" for request in views)


def test_poll_uses_default_duration_and_fails_when_success_has_no_artifacts():
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/history/video":
            return httpx2.Response(200, json={
                "video": {
                    "status": {"status_str": "success", "completed": True},
                    "outputs": {"9": {"videos": [{"filename": "movie.mp4"}]}},
                }
            })
        return httpx2.Response(200, content=b"mp4", headers={"content-type": "video/mp4"})

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    result = adapter.poll(_context(), "video")
    assert result.status == "succeeded"
    assert result.usage == {"second": 5}

    def empty_handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={
            "empty": {"status": {"status_str": "success", "completed": True}, "outputs": {}}
        })

    empty = ComfyUIAdapter(transport=httpx2.MockTransport(empty_handler)).poll(_context(), "empty")
    assert empty.status == "failed"
    assert empty.error_code == "comfyui_no_artifacts"


def test_cancel_deletes_only_pending_job():
    posts: list[tuple[str, dict]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path == "/queue":
            return httpx2.Response(200, json={
                "queue_running": [],
                "queue_pending": [[0, "prompt-1", {}, {}, []]],
            })
        if request.method == "POST":
            posts.append((request.url.path, json.loads(request.read())))
            return httpx2.Response(200, json={})
        raise AssertionError("unexpected request")

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    assert adapter.cancel(_context(), "prompt-1") is True
    assert posts == [("/queue", {"delete": ["prompt-1"]})]


def test_cancel_interrupts_only_explicitly_running_job():
    posts: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET":
            return httpx2.Response(200, json={
                "queue_running": [[0, "prompt-1", {}, {}, []]],
                "queue_pending": [],
            })
        posts.append(request.url.path)
        return httpx2.Response(200, json={})

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    assert adapter.cancel(_context(), "prompt-1") is True
    assert posts == ["/interrupt"]


def test_cancel_does_not_interrupt_another_job_and_recognizes_completion():
    posts: list[str] = []
    completed = False

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            posts.append(request.url.path)
            return httpx2.Response(200)
        if request.url.path == "/queue":
            return httpx2.Response(200, json={
                "queue_running": [[0, "someone-else", {}, {}, []]],
                "queue_pending": [],
            })
        return httpx2.Response(200, json={"prompt-1": {"outputs": {}}} if completed else {})

    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(handler))
    assert adapter.cancel(_context(), "prompt-1") is False
    completed = True
    assert adapter.cancel(_context(), "prompt-1") is True
    assert posts == []


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx2.Response(400, text="bad graph"), "upstream_rejected"),
        (httpx2.Response(200, json={}), "comfyui_no_prompt"),
        (httpx2.Response(200, content=b"not-json"), "upstream_error"),
    ],
)
def test_submit_turns_bad_upstream_responses_into_failed_results(response, expected_code):
    adapter = ComfyUIAdapter(transport=httpx2.MockTransport(lambda request: response))
    result = adapter.submit(_context())
    assert result.status == "failed"
    assert result.error_code == expected_code


def test_network_and_bad_history_fail_without_raising_and_cancel_returns_false():
    def network_error(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("offline", request=request)

    broken = ComfyUIAdapter(transport=httpx2.MockTransport(network_error))
    submitted = broken.submit(_context())
    polled = broken.poll(_context(), "prompt-1")
    assert submitted.status == "failed"
    assert polled.status == "failed"
    assert broken.cancel(_context(), "prompt-1") is False

    invalid = ComfyUIAdapter(transport=httpx2.MockTransport(
        lambda request: httpx2.Response(200, content=b"[]")
    ))
    result = invalid.poll(_context(), "prompt-1")
    assert result.status == "failed"
    assert result.error_code == "comfyui_bad_history"
    assert invalid.cancel(_context(), "prompt-1") is False
