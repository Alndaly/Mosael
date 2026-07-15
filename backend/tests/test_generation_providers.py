from __future__ import annotations

import shutil
import time

import pytest

from app.ai.providers import get_provider
from app.ai.providers.base import GenerationRequest, ProviderError, sanitize_provider_error
from app.ai.providers.qwen_image import build_submit_payload as qwen_payload, extract_result_url
from app.ai.providers.seedance import build_submit_payload as seedance_payload, extract_video_url
from tests.util import fresh_client

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def make_request(kind: str, **params) -> GenerationRequest:
    return GenerationRequest(kind=kind, model="m", prompt="a calm mountain lake", parameters=params)


def test_registry_resolves_providers() -> None:
    assert get_provider("mock", "image") is not None
    assert get_provider("mock", "video") is not None
    assert get_provider("alibaba", "image") is not None
    assert get_provider("bytedance", "video") is not None
    assert get_provider("nope", "image") is None


def test_guardrails_reject_out_of_bounds() -> None:
    provider = get_provider("mock", "image")
    with pytest.raises(ProviderError, match="num_images"):
        provider.validate_request(make_request("image", num_images=9))
    video = get_provider("mock", "video")
    with pytest.raises(ProviderError, match="duration_seconds"):
        video.validate_request(make_request("video", duration_seconds=60))
    with pytest.raises(ProviderError, match="resolution"):
        video.validate_request(make_request("video", resolution="8k"))
    with pytest.raises(ProviderError, match="Prompt"):
        video.validate_request(GenerationRequest(kind="video", model="m", prompt="  "))


def test_qwen_payload_shape() -> None:
    request = GenerationRequest(
        kind="image", model="qwen-image", prompt="p", negative_prompt="n",
        parameters={"size": "1024x576", "num_images": 2, "seed": 7},
    )
    payload = qwen_payload(request)
    assert payload["model"] == "qwen-image"
    assert payload["input"] == {"prompt": "p", "negative_prompt": "n"}
    assert payload["parameters"] == {"size": "1024*576", "n": 2, "seed": 7}


def test_qwen_poll_parsing() -> None:
    assert extract_result_url({"output": {"task_status": "RUNNING"}}) is None
    assert extract_result_url({"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://x/y.png"}]}}) == "https://x/y.png"
    with pytest.raises(ProviderError):
        extract_result_url({"output": {"task_status": "FAILED"}})


def test_seedance_payload_shape() -> None:
    request = GenerationRequest(
        kind="video", model="seedance", prompt="waves",
        parameters={"duration_seconds": 5, "resolution": "720p", "aspect_ratio": "16:9", "first_frame_url": "https://x/f.png"},
    )
    payload = seedance_payload(request)
    assert payload["model"].startswith("seedance-1-0")
    assert payload["content"][0]["text"] == "waves --resolution 720p --duration 5 --ratio 16:9"
    assert payload["content"][1]["image_url"]["url"] == "https://x/f.png"


def test_seedance_poll_parsing() -> None:
    assert extract_video_url({"status": "running"}) is None
    assert extract_video_url({"status": "succeeded", "content": {"video_url": "https://x/v.mp4"}}) == "https://x/v.mp4"
    with pytest.raises(ProviderError):
        extract_video_url({"status": "failed"})


def test_error_sanitization_strips_secrets() -> None:
    message = "401 for url?api_key=sk-abc123 Bearer sk-abc123 body"
    cleaned = sanitize_provider_error(message, "sk-abc123")
    assert "sk-abc123" not in cleaned


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_mock_generation_end_to_end_creates_asset() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    res = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": ws["id"],
            "provider": "mock",
            "model": "mock-image",
            "kind": "image",
            "prompt": "sunset over the sea",
            "parameters": {"size": "320x180"},
        },
    ).json()
    job_id = res["job"]["id"]

    deadline = time.time() + 60
    job = res["job"]
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.3)
    assert job["status"] == "succeeded", job.get("error")

    asset = client.get(f"/api/assets?workspace_id={ws['id']}").json()[0]
    assert asset["source"] == "generated"
    assert asset["kind"] == "image"
    assert asset["media_info"]["has_thumbnail"] is True

    generations = client.get(f"/api/generation/jobs?workspace_id={ws['id']}").json()
    assert generations[0]["result_asset_id"] == asset["id"]
