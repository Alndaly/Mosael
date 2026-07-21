from __future__ import annotations

import pytest

from app.ai.providers import get_provider
from app.ai.providers.base import GenerationRequest, ProviderContext, ProviderError, sanitize_provider_error
from app.ai.providers.kling import build_submit_payload as kling_payload, extract_video_url as extract_kling_video_url
from app.ai.providers.openai_image import build_submit_payload as openai_payload, extract_image_bytes
from app.ai.providers.qwen_image import build_submit_payload as qwen_payload, extract_result_url
from app.ai.providers.seedance import build_submit_payload as seedance_payload, extract_video_url
from app.ai.providers.veo import build_submit_payload as veo_payload, extract_video_uri


def make_request(kind: str, **params) -> GenerationRequest:
    return GenerationRequest(kind=kind, model="m", prompt="a calm mountain lake", parameters=params)


def test_registry_resolves_providers() -> None:
    assert get_provider("alibaba", "image") is not None
    assert get_provider("bytedance", "video") is not None
    assert get_provider("google", "video") is not None
    assert get_provider("kuaishou", "video") is not None
    assert get_provider("openai", "image") is not None
    assert get_provider("openai-compatible", "image") is not None
    assert get_provider("mock", "image") is None
    assert get_provider("mock", "video") is None
    assert get_provider("nope", "image") is None


def test_guardrails_reject_out_of_bounds() -> None:
    provider = get_provider("alibaba", "image")
    with pytest.raises(ProviderError, match="num_images"):
        provider.validate_request(make_request("image", num_images=9))
    video = get_provider("bytedance", "video")
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


def test_openai_image_payload_and_parsing() -> None:
    request = GenerationRequest(
        kind="image",
        model="gpt-image-2",
        prompt="p",
        parameters={"size": "1024*576", "num_images": 2, "quality": "high"},
    )
    payload = openai_payload(request)
    assert payload == {"model": "gpt-image-2", "prompt": "p", "n": 2, "size": "1024x576", "quality": "high"}
    assert extract_image_bytes({"data": [{"b64_json": "aGk="}]}) == b"hi"
    with pytest.raises(ProviderError):
        extract_image_bytes({"data": []})


def test_veo_payload_and_parsing() -> None:
    request = GenerationRequest(
        kind="video",
        model="veo",
        prompt="p",
        parameters={"aspect_ratio": "9:16", "duration_seconds": 8, "resolution": "1080p", "seed": 12},
    )
    payload = veo_payload(request)
    assert payload == {
        "instances": [{"prompt": "p"}],
        "parameters": {"numberOfVideos": 1, "aspectRatio": "9:16", "durationSeconds": "8", "resolution": "1080p", "seed": 12},
    }
    assert extract_video_uri({"done": False}) is None
    assert (
        extract_video_uri(
            {"done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "https://x/v.mp4"}}]}}}
        )
        == "https://x/v.mp4"
    )
    with pytest.raises(ProviderError):
        extract_video_uri({"error": {"message": "blocked"}})


def test_kling_payload_and_parsing() -> None:
    request = GenerationRequest(
        kind="video",
        model="kling",
        prompt="p",
        negative_prompt="n",
        parameters={"duration_seconds": 5, "resolution": "1080p", "aspect_ratio": "9:16", "first_frame_url": "https://x/i.png"},
    )
    payload = kling_payload(request, ProviderContext(None, "kuaishou", "ak", default_model="kling-v3"))
    assert payload == {
        "model_name": "kling-v3",
        "prompt": "p",
        "mode": "pro",
        "aspect_ratio": "9:16",
        "duration": "5",
        "negative_prompt": "n",
        "image": "https://x/i.png",
    }
    assert extract_kling_video_url({"data": {"task_status": "processing"}}) is None
    assert (
        extract_kling_video_url({"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://x/v.mp4"}]}}})
        == "https://x/v.mp4"
    )
    with pytest.raises(ProviderError):
        extract_kling_video_url({"code": 1100, "message": "bad request"})


def test_error_sanitization_strips_secrets() -> None:
    message = "401 for url?api_key=sk-abc123 Bearer sk-abc123 body"
    cleaned = sanitize_provider_error(message, "sk-abc123")
    assert "sk-abc123" not in cleaned
