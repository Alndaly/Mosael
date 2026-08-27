from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient
from app.ai.providers.video.kling_elements import build_element_contents, ensure_element

from app.ai.providers.base import (
    poll_until_ready,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    LAST_FRAME,
    first_frame_value,
    source_value,
    source_values,
    REFERENCE_IMAGE,
    metering_from_request,
    provider_http_error,
)

"""
Kling video adapter:
text2video / image2video task creation → task polling → download video URL.
Official Kling accounts use AccessKey + SecretKey JWT auth. Some compatible
gateways accept a plain Bearer token; both paths are supported by the resolved
provider profile without branching in the runner.
"""

KLING_BASE = "https://api.klingai.com"
DEFAULT_MODEL_ID = "kling-v3"

#: **可灵有两代接口,形状完全不同。**
#:
#: 旧的(2.x 及更早):`POST /v1/videos/image2video`,参数平铺(`model_name` / `image` /
#: `image_tail` / `duration` 是字符串)。
#: 新的(3.0 起):`POST /image-to-video/kling-3.0`,请求体是 `contents` 数组 + `settings`
#: 对象 —— 提示词、首帧、尾帧、**主体**都是数组里的一项,靠 `type` 区分。
#:
#: 多图参考只在新接口上有:它靠 `type: "element"` 引用主体库里的主体(见 kling_elements),
#: 旧接口里根本没有承载它的字段。所以这里按型号分两条路,而不是把新字段硬塞进旧形状。
_V3_MODELS = ("kling-v3", "kling-v3-omni", "kling-3.0", "kling-3.0-turbo")


def uses_contents_array(model: str) -> bool:
    name = str(model or "").strip().lower()
    return name in _V3_MODELS or name.startswith("kling-v3") or name.startswith("kling-3")


def v3_endpoint(model: str) -> str:
    """新接口的路径把型号写在 URL 里,而不是请求体的 model 字段。"""
    name = str(model or "").strip().lower()
    return "/image-to-video/kling-3.0-turbo" if "turbo" in name else "/image-to-video/kling-3.0"


def build_v3_payload(
    request: GenerationRequest,
    context: ProviderContext | None = None,
    element_ids: list[str] | None = None,
) -> dict[str, Any]:
    """新接口的请求体:一个 `contents` 数组 + 一个 `settings` 对象。

    `element_ids` 由调用方先备好(建主体是一次独立的异步任务,不能在拼请求体的时候顺手做)。
    """
    contents: list[dict[str, Any]] = [{"type": "prompt", "text": request.prompt}]
    first_frame = first_frame_value(request)
    if first_frame:
        contents.append({"type": "first_frame", "url": str(first_frame)})
    # 文档原话:「支持仅首帧图生视频和首尾帧图生视频,**不支持仅尾帧**图生视频」。
    last_frame = source_value(request, LAST_FRAME)
    if first_frame and last_frame:
        contents.append({"type": "last_frame", "url": str(last_frame)})
    contents.extend(build_element_contents(list(element_ids or [])))

    settings: dict[str, Any] = {
        "duration": int(float(request.parameters.get("duration_seconds", 5))),
        "resolution": str(request.parameters.get("resolution", "720p")).lower(),
    }
    # 音画同出:给了才发,不替用户默认打开 —— 有声比无声贵。
    if request.parameters.get("generate_audio"):
        settings["audio"] = "native"
    if request.parameters.get("multi_shot") is not None:
        settings["multi_shot"] = bool(request.parameters["multi_shot"])
    payload: dict[str, Any] = {"contents": contents, "settings": settings}
    if request.parameters.get("external_task_id"):
        payload["options"] = {"external_task_id": str(request.parameters["external_task_id"])}
    return payload


def resolve_model(request: GenerationRequest, context: ProviderContext) -> str:
    if request.model != "kling":
        return request.model
    return context.default_model or DEFAULT_MODEL_ID


def build_submit_payload(request: GenerationRequest, context: ProviderContext | None = None) -> dict[str, Any]:
    model = resolve_model(request, context or ProviderContext(None, "kuaishou", "", default_model=""))
    duration = str(int(float(request.parameters.get("duration_seconds", 5))))
    resolution = str(request.parameters.get("resolution", "720p"))
    payload: dict[str, Any] = {
        "model_name": model,
        "prompt": request.prompt,
        "mode": str(request.parameters.get("mode") or ("pro" if resolution == "1080p" else "std")),
        "aspect_ratio": str(request.parameters.get("aspect_ratio", "16:9")),
        "duration": duration,
    }
    if request.negative_prompt:
        payload["negative_prompt"] = request.negative_prompt
    for key in ("cfg_scale", "camera_control", "external_task_id"):
        if request.parameters.get(key) not in (None, ""):
            payload[key] = request.parameters[key]

    first_frame = first_frame_value(request)
    if first_frame:
        payload["image"] = str(first_frame)
    # 尾帧走 image_tail(可灵把首尾帧拆成两个字段,而不是一个带 role 的数组)。
    # 只给尾帧不给首帧是不成立的 —— 那条接口是 image2video,首帧是它的必填项。
    last_frame = source_value(request, LAST_FRAME)
    if first_frame and last_frame:
        payload["image_tail"] = str(last_frame)
    return payload


def endpoint_for(request: GenerationRequest) -> str:
    return "/v1/videos/image2video" if first_frame_value(request) else "/v1/videos/text2video"


def extract_video_url(task_payload: dict[str, Any]) -> str | None:
    code = task_payload.get("code")
    if code not in (None, 0):
        raise ProviderError(f"Generation failed: {task_payload.get('message') or code}")

    data = task_payload.get("data") if isinstance(task_payload.get("data"), dict) else task_payload
    status = str(data.get("task_status", "")).lower()
    if status in ("submitted", "processing", "running", "queued"):
        return None
    if status in ("failed", "fail", "canceled", "cancelled"):
        message = data.get("task_status_msg") or data.get("message") or status
        raise ProviderError(f"Generation failed: {message}")
    if status != "succeed":
        return None

    result = data.get("task_result") or data.get("result") or {}
    candidates: list[Any] = [
        result.get("video_url") if isinstance(result, dict) else None,
        result.get("url") if isinstance(result, dict) else None,
    ]
    videos = result.get("videos") if isinstance(result, dict) else None
    if isinstance(videos, list):
        for video in videos:
            if isinstance(video, dict):
                candidates.extend([video.get("url"), video.get("video_url")])
    for candidate in candidates:
        if candidate:
            return str(candidate)
    raise ProviderError("Provider returned success without a video URL")


def extract_video_url_v3(task_payload: dict[str, Any]) -> str | None:
    """新接口的查询回的是**一个数组**(`data` 是列表,因为 /tasks 支持批量查),
    终态词也换了:`succeeded` 而不是旧接口的 `succeed`,结果在 `outputs[]` 里按 `type` 分。

    照抄旧接口那份解析的话,一切看起来都在"处理中",一直轮询到超时 —— 而任务其实早就成了。
    """
    code = task_payload.get("code")
    if code not in (None, 0):
        raise ProviderError(f"Generation failed: {task_payload.get('message') or code}")
    rows = task_payload.get("data")
    if isinstance(rows, dict):
        rows = rows.get("result") if isinstance(rows.get("result"), list) else [rows]
    if not isinstance(rows, list) or not rows:
        return None
    task = rows[0]
    status = str(task.get("status") or "").lower()
    if status in ("failed", "fail", "canceled", "cancelled"):
        raise ProviderError(f"Generation failed: {task.get('message') or status}")
    if status != "succeeded":
        return None
    for output in task.get("outputs") or []:
        if output.get("type") == "video" and output.get("url"):
            return str(output["url"])
    raise ProviderError("Provider returned success without a video URL")


class KlingProvider(GenerationProvider):
    name = "kuaishou"
    kind = "video"

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        if not context.api_key:
            raise ProviderError("Kling Access Key/API key is not configured (settings → 生成服务)")
        base_url = (context.base_url or KLING_BASE).rstrip("/")
        model = resolve_model(request, context)
        v3 = uses_contents_array(model)
        headers = {"Authorization": auth_header(context), "Content-Type": "application/json"}
        try:
            with RetryingClient(base_url=base_url, timeout=60, headers=headers, follow_redirects=True) as client:
                if v3:
                    # 多图参考:先把那几张图变成一个主体(查得到就复用,查不到才建),再引用它。
                    # 这一步是**另一个异步任务**,得在提交生成之前跑完 —— 拼请求体的时候顺手做
                    # 不了,那里没有 client 也不该在那里等三分钟。
                    references = list(source_values(request, REFERENCE_IMAGE))
                    element_ids = (
                        [ensure_element(client, references, description=request.prompt[:100])]
                        if references
                        else []
                    )
                    endpoint = v3_endpoint(model)
                    body = build_v3_payload(request, context, element_ids=element_ids)
                    # 新接口查任务是统一的 /tasks?task_ids=,不是在生成路径底下。
                    poll_path_for = lambda task: f"/tasks?task_ids={task}"
                else:
                    endpoint = endpoint_for(request)
                    body = build_submit_payload(request, context)
                    poll_path_for = lambda task: f"{endpoint}/{task}"

                submit = client.post(endpoint, json=body)
                submit.raise_for_status()
                data = submit.json().get("data") or {}
                task_id = data.get("id") or data.get("task_id") or submit.json().get("task_id") or ""
                if not task_id:
                    raise ProviderError("Provider did not return a task id")

                url, poll_payload = poll_until_ready(
                    client, poll_path_for(task_id), extract_video_url_v3 if v3 else extract_video_url
                )

                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "generated.mp4"
                download = client.get(url)
                download.raise_for_status()
                target.write_bytes(download.content)
                return GenerationResult(output_path=target, usage=metering_from_request(request), raw_usage=poll_payload)
        except httpx.HTTPError as exc:
            raise ProviderError(provider_http_error("Kling request failed", exc, context.api_key)) from exc


def auth_header(context: ProviderContext) -> str:
    secret_key = str(context.extra.get("secret_key") or "")
    if not secret_key:
        return f"Bearer {context.api_key}"
    now = int(time.time())
    token = _jwt_hs256(
        {"iss": context.api_key, "exp": now + 1800, "nbf": now - 5},
        secret_key,
    )
    return f"Bearer {token}"


def _jwt_hs256(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join([_b64url_json(header), _b64url_json(payload)])
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _b64url_json(value: dict[str, Any]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
