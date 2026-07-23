from __future__ import annotations

import pytest

from app.ai.providers import get_provider
import httpx

from app.ai.providers.base import (
    GenerationRequest,
    ProviderContext,
    ProviderError,
    metering_from_request,
    provider_http_error,
    sanitize_provider_error,
)
from app.ai.providers.kling import build_submit_payload as kling_payload, extract_video_url as extract_kling_video_url
from app.ai.providers.openai_image import build_edit_fields as openai_edit_fields, build_submit_payload as openai_payload, extract_image_bytes
from app.ai.providers.qwen_image import (
    DASHSCOPE_BASE,
    build_edit_payload as qwen_edit_payload,
    build_submit_payload as qwen_payload,
    download_result_asset,
    extract_result_url,
    resolve_dashscope_base,
    resolve_qwen_edit_base,
)
from app.ai.providers.seedance import (
    ARK_BASE,
    LAS_BASE,
    build_submit_payload as seedance_payload,
    extract_video_url,
    resolve_seedance_base,
)
from app.ai.providers.veo import _with_first_frame_inline, build_submit_payload as veo_payload, extract_video_uri


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


def test_generation_metering_estimates_prompt_tokens() -> None:
    units = metering_from_request(
        GenerationRequest(
            kind="image",
            model="qwen-image",
            prompt="海边散步的女孩",
            negative_prompt="low quality",
            parameters={"num_images": 2, "size": "1024x1024"},
        )
    )
    assert units["images"] == 2
    assert units["input_characters"] > 0
    assert units["input_tokens"] > 0
    assert units["total_tokens"] == units["input_tokens"]
    assert units["token_estimate"] is True


def test_qwen_payload_shape() -> None:
    request = GenerationRequest(
        kind="image", model="qwen-image", prompt="p", negative_prompt="n",
        parameters={"size": "1024x576", "num_images": 2, "seed": 7},
    )
    payload = qwen_payload(request)
    assert payload["model"] == "qwen-image"
    assert payload["input"] == {"prompt": "p", "negative_prompt": "n"}
    assert payload["parameters"] == {"size": "1024*576", "n": 2, "seed": 7}


def test_qwen_edit_payload_uses_uploaded_reference_image(tmp_path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"image-bytes")
    request = GenerationRequest(
        kind="image",
        model="qwen-image-edit",
        prompt="把女孩变成男孩",
        negative_prompt="low quality",
        parameters={"num_images": 1, "size": "1024x1024", "seed": 9},
        source_files=(source,),
    )
    payload = qwen_edit_payload(request)
    content = payload["input"]["messages"][0]["content"]
    assert payload["model"] == "qwen-image-edit"
    assert content == [
        {"image": "data:image/png;base64,aW1hZ2UtYnl0ZXM="},
        {"text": "把女孩变成男孩"},
    ]
    assert payload["parameters"] == {"n": 1, "watermark": False, "negative_prompt": "low quality", "seed": 9}


def test_qwen_image_uses_native_dashscope_endpoint_even_when_chat_base_url_is_compatible_mode() -> None:
    context = ProviderContext(
        profile_id="p1",
        vendor="alibaba",
        api_key="sk-test",
        base_url="https://llm-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    assert resolve_dashscope_base(context) == DASHSCOPE_BASE
    assert resolve_qwen_edit_base(context) == "https://llm-example.cn-beijing.maas.aliyuncs.com"

    custom = ProviderContext(
        profile_id="p1",
        vendor="alibaba",
        api_key="sk-test",
        extra={"dashscope_base_url": "https://dashscope.example.com/"},
    )
    assert resolve_dashscope_base(custom) == "https://dashscope.example.com"


def test_qwen_poll_parsing() -> None:
    assert extract_result_url({"output": {"task_status": "RUNNING"}}) is None
    assert extract_result_url({"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://x/y.png"}]}}) == "https://x/y.png"
    assert (
        extract_result_url(
            {"output": {"choices": [{"message": {"content": [{"image": "https://x/edit.png"}], "role": "assistant"}}]}}
        )
        == "https://x/edit.png"
    )
    with pytest.raises(ProviderError):
        extract_result_url({"output": {"task_status": "FAILED"}})


def test_qwen_download_result_url_does_not_reuse_dashscope_headers(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"png-bytes"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str) -> FakeResponse:
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr("app.ai.providers.qwen_image.httpx.Client", FakeClient)
    target = tmp_path / "generated.png"
    signed_url = "https://dashscope-oss.example.com/out.png?Signature=abc"

    download_result_asset(signed_url, target)

    assert captured["url"] == signed_url
    assert "headers" not in captured["kwargs"]
    assert target.read_bytes() == b"png-bytes"


def test_seedance_payload_shape() -> None:
    request = GenerationRequest(
        kind="video",
        model="doubao-seedance-2-0-260128",
        prompt="waves",
        parameters={
            "duration_seconds": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "first_frame_url": "https://x/f.png",
            "generate_audio": True,
        },
    )
    payload = seedance_payload(request)
    assert payload["model"] == "doubao-seedance-2-0-260128"
    assert payload["content"][0]["text"] == "waves"
    assert payload["content"][1]["image_url"]["url"] == "https://x/f.png"
    assert payload["content"][1]["role"] == "first_frame"
    assert payload["duration"] == 5
    assert payload["resolution"] == "720p"
    assert "ratio" not in payload
    assert payload["generate_audio"] is True


def test_seedance_payload_accepts_uploaded_first_frame(tmp_path) -> None:
    first_frame = tmp_path / "first.png"
    first_frame.write_bytes(b"image-bytes")
    request = GenerationRequest(
        kind="video",
        model="doubao-seedance-2-0-260128",
        prompt="waves",
        parameters={"duration_seconds": 5, "resolution": "720p", "aspect_ratio": "16:9"},
        source_files=(first_frame,),
    )
    payload = seedance_payload(request)
    assert payload["content"][1]["image_url"]["url"] == "data:image/png;base64,aW1hZ2UtYnl0ZXM="
    assert payload["content"][1]["role"] == "first_frame"
    assert "ratio" not in payload


def test_seedance_text_to_video_keeps_ratio_as_a_json_parameter() -> None:
    request = GenerationRequest(
        kind="video",
        model="doubao-seedance-1-0-pro-250528",
        prompt="waves",
        parameters={"duration_seconds": 5, "resolution": "720p", "aspect_ratio": "16:9"},
    )
    payload = seedance_payload(request)
    assert payload["content"] == [{"type": "text", "text": "waves"}]
    assert payload["ratio"] == "16:9"


def test_seedance_one_x_routes_to_las_when_profile_uses_default_ark_base() -> None:
    context = ProviderContext(None, "bytedance", "sk-test", base_url=ARK_BASE)
    assert resolve_seedance_base("doubao-seedance-1-5-pro-251215", context) == LAS_BASE
    assert resolve_seedance_base("doubao-seedance-2-0-260128", context) == ARK_BASE


def test_seedance_poll_parsing() -> None:
    assert extract_video_url({"status": "running"}) is None
    assert extract_video_url({"status": "succeeded", "content": {"video_url": "https://x/v.mp4"}}) == "https://x/v.mp4"
    assert extract_video_url({"status": "succeeded", "output": {"video_url": "https://x/out.mp4"}}) == "https://x/out.mp4"
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


def test_openai_image_edit_fields() -> None:
    request = GenerationRequest(
        kind="image",
        model="gpt-image-2",
        prompt="edit it",
        parameters={"size": "1024*1024", "num_images": 2, "quality": "high", "input_fidelity": "high"},
    )
    assert openai_edit_fields(request) == {
        "model": "gpt-image-2",
        "prompt": "edit it",
        "n": "2",
        "size": "1024x1024",
        "quality": "high",
        "input_fidelity": "high",
    }


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


def test_veo_payload_accepts_uploaded_first_frame(tmp_path) -> None:
    first_frame = tmp_path / "first.jpg"
    first_frame.write_bytes(b"image-bytes")
    request = GenerationRequest(
        kind="video",
        model="veo",
        prompt="p",
        source_files=(first_frame,),
    )
    payload = veo_payload(_with_first_frame_inline(request, "sk-test"))
    assert payload["instances"][0]["image"]["inlineData"] == {
        "mimeType": "image/jpeg",
        "data": "aW1hZ2UtYnl0ZXM=",
    }


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


def test_kling_payload_accepts_uploaded_first_frame(tmp_path) -> None:
    first_frame = tmp_path / "first.png"
    first_frame.write_bytes(b"image-bytes")
    request = GenerationRequest(
        kind="video",
        model="kling",
        prompt="p",
        parameters={"duration_seconds": 5, "resolution": "720p", "aspect_ratio": "9:16"},
        source_files=(first_frame,),
    )
    payload = kling_payload(request, ProviderContext(None, "kuaishou", "ak", default_model="kling-v3"))
    assert payload["image"] == "data:image/png;base64,aW1hZ2UtYnl0ZXM="


def test_error_sanitization_strips_secrets() -> None:
    message = "401 for url?api_key=sk-abc123 Bearer sk-abc123 body"
    cleaned = sanitize_provider_error(message, "sk-abc123")
    assert "sk-abc123" not in cleaned


def test_provider_http_error_includes_safe_response_body() -> None:
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(400, request=request, text='{"error":"model sk-abc123 unsupported"}')
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    message = provider_http_error("Provider failed", exc, "sk-abc123")
    assert "body:" in message
    assert "unsupported" in message
    assert "sk-abc123" not in message


def test_seedream_registry_and_payload_shape(tmp_path) -> None:
    from app.ai.providers.seedream import build_image_payload, extract_image_url

    assert get_provider("bytedance-image", "image") is not None

    # 4.x:参考图走 image 数组;尺寸统一成 x 分隔
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n0000")
    payload = build_image_payload(
        GenerationRequest(
            kind="image",
            model="doubao-seedream-4-0-250828",
            prompt="蓝调海边",
            parameters={"size": "2048*2048"},
            source_files=(ref,),
        )
    )
    assert payload["model"] == "doubao-seedream-4-0-250828"
    assert payload["size"] == "2048x2048"
    assert payload["watermark"] is False
    assert isinstance(payload["image"], list) and payload["image"][0].startswith("data:image/png;base64,")
    assert "seed" not in payload

    # 3.x t2i:无参考图、支持 seed
    payload3 = build_image_payload(
        GenerationRequest(
            kind="image",
            model="doubao-seedream-3-0-t2i-250415",
            prompt="蓝调海边",
            parameters={"size": "1024x1024", "seed": 42},
        )
    )
    assert payload3["seed"] == 42
    assert "image" not in payload3

    assert extract_image_url({"data": [{"url": "https://cdn/x.png"}]}) == "https://cdn/x.png"
    with pytest.raises(ProviderError):
        extract_image_url({"data": []})
