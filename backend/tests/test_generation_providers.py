from __future__ import annotations

import pytest

from app.ai.providers import get_provider
from app.ai.providers.base import FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, SourceAsset
import httpx

from app.ai.providers.base import (
    GenerationRequest,
    ProviderContext,
    ProviderError,
    metering_from_request,
    provider_http_error,
    sanitize_provider_error,
)
from app.ai.providers.video.kling import build_submit_payload as kling_payload, extract_video_url as extract_kling_video_url
from app.ai.providers.image.openai import build_edit_fields as openai_edit_fields, build_submit_payload as openai_payload, extract_image_bytes
from app.ai.providers.image.qwen import (
    DASHSCOPE_BASE,
    build_edit_payload as qwen_edit_payload,
    build_submit_payload as qwen_payload,
    download_result_asset,
    extract_result_urls,
    resolve_dashscope_base,
    resolve_qwen_edit_base,
)
from app.ai.providers.video.seedance import (
    ARK_BASE,
    build_submit_payload as seedance_payload,
    extract_video_url,
    resolve_seedance_base,
)
from app.ai.providers.video.veo import _with_first_frame_inline, build_submit_payload as veo_payload, extract_video_uri
from app.ai.providers.evolink import (
    _upload as evolink_upload,
    build_image_payload as evolink_image_payload,
    build_video_payload as evolink_video_payload,
    collect_image_urls as evolink_collect_image_urls,
    extract_result_urls as extract_evolink_result_urls,
)


def make_request(kind: str, **params) -> GenerationRequest:
    return GenerationRequest(kind=kind, model="m", prompt="a calm mountain lake", parameters=params)


def test_registry_resolves_providers() -> None:
    assert get_provider("alibaba", "image") is not None
    assert get_provider("bytedance", "video") is not None
    assert get_provider("google", "video") is not None
    assert get_provider("kuaishou", "video") is not None
    assert get_provider("openai", "image") is not None
    assert get_provider("openai-compatible", "image") is not None
    assert get_provider("evolink", "image") is not None
    assert get_provider("evolink", "video") is not None
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


def test_evolink_uses_gateway_parameter_names_and_wider_video_limits() -> None:
    request = GenerationRequest(
        kind="video",
        model="seedance-1.5-pro",
        prompt="a runner in a park",
        parameters={
            "duration_seconds": 12,
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "generate_audio": True,
            "first_frame_url": "https://files.example/first.jpg",
            "last_frame_url": "https://files.example/last.jpg",
        },
    )
    assert evolink_video_payload(request) == {
        "model": "seedance-1.5-pro",
        "prompt": "a runner in a park",
        "duration": 12,
        "quality": "1080p",
        "aspect_ratio": "9:16",
        "generate_audio": True,
        "image_urls": ["https://files.example/first.jpg", "https://files.example/last.jpg"],
    }
    provider = get_provider("evolink", "video")
    provider.validate_request(make_request("video", duration_seconds=15, resolution="4k"))
    with pytest.raises(ProviderError, match="3 and 15"):
        provider.validate_request(make_request("video", duration_seconds=16))


def test_evolink_image_payload_preserves_all_reference_urls() -> None:
    request = GenerationRequest(
        kind="image",
        model="gpt-image-1.5",
        prompt="edit the coat",
        parameters={
            "size": "1024*1536",
            "num_images": 2,
            "reference_image_url": ["https://files.example/a.png", "https://files.example/b.png"],
        },
    )
    assert evolink_image_payload(request) == {
        "model": "gpt-image-1.5",
        "prompt": "edit the coat",
        "size": "1024x1536",
        "n": 2,
        "image_urls": ["https://files.example/a.png", "https://files.example/b.png"],
    }


def test_evolink_uploads_local_inputs_in_semantic_role_order(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    reference = tmp_path / "reference.png"
    for path in (first, last, reference):
        path.write_bytes(path.stem.encode())
    request = GenerationRequest(
        kind="video",
        model="seedance-1.5-pro",
        prompt="move",
        sources=(
            SourceAsset(role=REFERENCE_IMAGE, path=reference),
            SourceAsset(role=LAST_FRAME, path=last),
            SourceAsset(role=FIRST_FRAME, path=first),
        ),
    )
    monkeypatch.setattr(
        "app.ai.providers.evolink._upload",
        lambda path, _context: f"https://files.example/{path.name}",
    )
    urls = evolink_collect_image_urls(request, ProviderContext("p", "evolink", "key"))
    assert urls == [
        "https://files.example/first.png",
        "https://files.example/last.png",
        "https://files.example/reference.png",
    ]


def test_evolink_upload_reuses_browser_image_normalization(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.heic"
    preview = tmp_path / "browser-preview.jpg"
    source.write_bytes(b"heic")
    preview.write_bytes(b"jpeg")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"success": True, "data": {"file_url": "https://files.example/preview.jpg"}}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, path: str, **kwargs):
            captured["path"] = path
            captured["files"] = kwargs["files"]
            return FakeResponse()

    monkeypatch.setattr(
        "app.ai.providers.evolink.browser_compatible_image",
        lambda path, directory: (preview, "image/jpeg"),
    )
    monkeypatch.setattr("app.ai.providers.evolink.RetryingClient", FakeClient)

    url = evolink_upload(source, ProviderContext("p", "evolink", "secret"))

    assert url == "https://files.example/preview.jpg"
    assert captured["path"] == "/api/v1/files/upload/stream"
    assert captured["files"] == {"file": ("browser-preview.jpg", b"jpeg", "image/jpeg")}


def test_evolink_task_terminal_states() -> None:
    assert extract_evolink_result_urls({"status": "processing", "progress": 40}) is None
    assert extract_evolink_result_urls(
        {
            "status": "completed",
            "results": ["https://cdn.example/a.mp4"],
            "result_data": [{"video_url": "https://cdn.example/b.mp4"}],
        }
    ) == ["https://cdn.example/a.mp4", "https://cdn.example/b.mp4"]
    with pytest.raises(ProviderError, match="policy rejected"):
        extract_evolink_result_urls(
            {"status": "failed", "error": {"code": "content_policy", "message": "policy rejected"}}
        )


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
        sources=tuple(SourceAsset(role=REFERENCE_IMAGE, path=p) for p in (source,)),
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
    assert extract_result_urls({"output": {"task_status": "RUNNING"}}) is None
    assert extract_result_urls({"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://x/y.png"}]}}) == [
        "https://x/y.png"
    ]
    assert extract_result_urls(
        {"output": {"choices": [{"message": {"content": [{"image": "https://x/edit.png"}], "role": "assistant"}}]}}
    ) == ["https://x/edit.png"]
    with pytest.raises(ProviderError):
        extract_result_urls({"output": {"task_status": "FAILED"}})


def test_qwen_多张产出一张都不能少() -> None:
    """`n` 选了几就回几条,**每一条都要取**。

    此前这里 return 第一条就走 —— 用户选了 4 张、按 4 张计了费,拿回来一张,而且没有任何
    地方会报错:界面上就是安安静静地只多出一张图。
    """
    assert extract_result_urls(
        {"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://x/1.png"}, {"url": "https://x/2.png"}]}}
    ) == ["https://x/1.png", "https://x/2.png"]
    assert extract_result_urls(
        {
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://x/a.png"}, {"image": "https://x/b.png"}]}},
                ]
            }
        }
    ) == ["https://x/a.png", "https://x/b.png"]


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

    # 下载走的是带重试的传输层(RetryingClient),桩要打在它上面 —— 打 httpx.Client 拦不住,
    # 因为子类在导入期就绑定了真类,结果会真的去连那个域名。
    monkeypatch.setattr("app.ai.providers.image.qwen.RetryingClient", FakeClient)
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
        sources=tuple(SourceAsset(role=FIRST_FRAME, path=p) for p in (first_frame,)),
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


def test_seedance_两代都走方舟_没有第二个端点() -> None:
    """2026-08-27 真机核过:拿方舟密钥打 LAS 一律 401,那是另一套凭据,而设置里只让用户
    配一份火山密钥 —— 那条分支从来没跑通过。同一把密钥打方舟的 seedance-1 正常出片。"""
    context = ProviderContext(None, "bytedance", "sk-test", base_url=ARK_BASE)
    assert resolve_seedance_base("doubao-seedance-1-0-pro-250528", context) == ARK_BASE
    assert resolve_seedance_base("doubao-seedance-2-0-260128", context) == ARK_BASE


def test_seedance_参考素材每一份都发得出去() -> None:
    """挂九张参考图就该发九张。此前走单数的 source_value,只发得出第一张 ——
    不报错,只是效果不对,而且界面上看不出少了八张。"""
    request = GenerationRequest(
        kind="video",
        model="doubao-seedance-2-0-260128",
        prompt="waves",
        parameters={
            "reference_image_url": ["https://x/a.png", "https://x/b.png", "https://x/c.png"],
            "reference_video_url": "https://x/v.mp4",
            "reference_audio_url": "https://x/a.mp3",
        },
    )
    content = seedance_payload(request)["content"]
    images = [one for one in content if one.get("role") == "reference_image"]
    assert [one["image_url"]["url"] for one in images] == ["https://x/a.png", "https://x/b.png", "https://x/c.png"]
    # 类型要跟着角色走 —— 接口会校验这一对配不配(`role=... invalid for type=...`)。
    assert [one["type"] for one in content if one.get("role") == "reference_video"] == ["video_url"]
    assert [one["type"] for one in content if one.get("role") == "reference_audio"] == ["audio_url"]


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
    assert extract_image_bytes({"data": [{"b64_json": "aGk="}]}) == [b"hi"]
    # n 是几就有几条 —— 只读 data[0] 的话,多出来的那几张连同它们的钱一起消失。
    assert extract_image_bytes({"data": [{"b64_json": "aGk="}, {"b64_json": "eW8="}]}) == [b"hi", b"yo"]
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
        sources=tuple(SourceAsset(role=FIRST_FRAME, path=p) for p in (first_frame,)),
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
        sources=tuple(SourceAsset(role=FIRST_FRAME, path=p) for p in (first_frame,)),
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
    from app.ai.providers.image.seedream import build_image_payload, extract_image_url

    assert get_provider("bytedance", "image") is not None

    # 4.x:参考图走 image 数组;尺寸统一成 x 分隔
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n0000")
    payload = build_image_payload(
        GenerationRequest(
            kind="image",
            model="doubao-seedream-4-0-250828",
            prompt="蓝调海边",
            parameters={"size": "2048*2048"},
            sources=tuple(SourceAsset(role=REFERENCE_IMAGE, path=p) for p in (ref,)),
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
