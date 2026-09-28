"""火山引擎 · 即梦 AI 的 OmniHuman 1.5 说话照片(ADR 0028 阶段 4)。

官方文档(即梦 AI → OmniHuman1.5 → 调用步骤 3:视频生成,2026-09-28 读,页面最近更新 2026-09-21):
https://www.volcengine.com/docs/85621/1829013

- `POST https://visual.volcengineapi.com?Action=CVSubmitTask&Version=2022-08-31` 提交,
  `Action=CVGetResult` 查;**每一次请求都要账号级 AK/SK 签名**(服务 `cv`、地域 `cn-north-1`),没有 API Key 这条路。
- 请求体:`req_key`(固定 `jimeng_realman_avatar_picture_omni_v15`)、`image_url`、`audio_url`,可选 `prompt`、`seed`、
  `output_resolution`(720 / 1080,默认 1080)、`pe_fast_mode`、`mask_url`(指定图里哪个主体说话,要先调主体检测 ——
  这一版不接,一张图一个人)。
- **素材只收公网链接**:描述符标了 `url_only_roles`,本地素材由生成漏斗先传到用户的对象存储、换成限时直链再给这里
  (generation.public_links),这里只读 `<role>_url`。
- 音频必须短于 60 秒(文档:「过长情况下提交任务正常,查询任务会报错」50215),建议 15 秒以内;描述符的
  `source_duration_seconds` 在提交前就拦,长稿由「长稿分段配音」按它切。
- 查询回包先看外层 `code`(10000 才算成功),再看 `data.status`(`in_queue` / `generating` / `done` / `not_found` /
  `expired`);`video_url` 一小时有效,拿到就下。
- `pe_fast_mode` 照文档的建议跟着分辨率走(720 开、1080 关),不另做一个让人选的参数。
- 文档里的 `req_json.aigc_meta` 隐式标识要平台登记过的服务商 ID,这里不填编造的 ID;成片导出时 Mosael 自己写 AIGC
  元数据(ADR 0028 §5)。

接口形状照文档写,**还没拿真实密钥跑到终态**:第一次真跑时以接口自己的报错校准。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.adapters.bytedance.volcano.openapi_sign import signed_headers
from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    http_error_detail,
    http_status_category,
    metering_from_request,
    poll_until_ready,
    source_url_values,
    upstream_error,
)
from app.ai.media_transfer import download_to_path
from app.core.http_retry import RetryingClient

HOST = "visual.volcengineapi.com"
REGION = "cn-north-1"
SERVICE = "cv"
VERSION = "2022-08-31"
SUBMIT_ACTION = "CVSubmitTask"
QUERY_ACTION = "CVGetResult"
VENDOR_LABEL = "即梦 OmniHuman"
POLL_INTERVAL_SECONDS = 5.0

#: 模型 id → 接口的 req_key。目录里的 id 是给人看的名字,req_key 是接口认的那一串。
REQ_KEYS = {"omnihuman-1.5": "jimeng_realman_avatar_picture_omni_v15"}

#: 业务错误码 → 失败类别(文档「业务错误码」那张表)。
_CODE_CATEGORY = {
    50411: "content_blocked",  # Pre Img Risk Not Pass
    50511: "content_blocked",  # Post Img Risk Not Pass
    50412: "content_blocked",  # Text Risk Not Pass
    50512: "content_blocked",  # Post Text Risk Not Pass
    50513: "content_blocked",  # Pre Video Risk Not Pass
    50514: "content_blocked",  # Pre Audio Risk Not Pass
    50413: "content_blocked",  # 输入文本含敏感词、版权词
    50215: "invalid_params",  # Input invalid(音频超过 60 秒等)
    50429: "rate_limited",
    50430: "rate_limited",
    50500: "unavailable",
    50501: "unavailable",
}


def req_key_for(model: str) -> str:
    key = REQ_KEYS.get((model or "").strip())
    if not key:
        raise GenerationAdapterError("providerErr_upstreamInvalidParams", vendor=VENDOR_LABEL, detail=f"unknown model {model!r}")
    return key


def _url(request: GenerationRequest, role: str) -> str:
    """这个角色的公网直链。本地素材在漏斗里已经换成直链(`url_only_roles`),到这里还没有就是没挂。"""
    urls = source_url_values(request.parameters, role, request.kind)
    if urls:
        return str(urls[0])
    for item in request.sources:
        if item.role == role and item.public_url:
            return item.public_url
    raise GenerationAdapterError("providerErr_sourceMissing", vendor=VENDOR_LABEL, role=role)


def build_body(request: GenerationRequest) -> dict[str, Any]:
    """宿主请求 → 提交体。只发用户给了的格子。"""
    body: dict[str, Any] = {
        "req_key": req_key_for(request.model),
        "image_url": _url(request, FIRST_FRAME),
        "audio_url": _url(request, DRIVING_AUDIO),
    }
    if request.prompt.strip():
        body["prompt"] = request.prompt.strip()
    seed = request.parameters.get("seed")
    if seed is not None and str(seed).strip() != "":
        body["seed"] = int(seed)
    resolution = str(request.parameters.get("resolution") or "").strip().lower()
    if resolution:
        pixels = int(resolution.rstrip("p"))
        body["output_resolution"] = pixels
        #: 文档建议:720 开快速模式、1080 关 —— 和即梦客户端的效果一致。
        body["pe_fast_mode"] = pixels == 720
    return body


def raise_for_payload(payload: dict[str, Any]) -> None:
    """外层 code 不是 10000 就是失败(文档:「优先判断 code=10000,然后再判断 data.status」)。"""
    code = payload.get("code")
    if code in (None, 10000, "10000"):
        return
    try:
        number = int(code)
    except (TypeError, ValueError):
        number = -1
    raise upstream_error(VENDOR_LABEL, _CODE_CATEGORY.get(number), f"{code} {payload.get('message') or ''}".strip())


def extract_video(payload: dict[str, Any]) -> dict[str, Any] | None:
    """CVGetResult 的回包:做完回 data,还在跑回 None,失败按错误码抛。"""
    raise_for_payload(payload)
    data = payload.get("data") or {}
    status = str(data.get("status") or "")
    if status in ("not_found", "expired"):
        raise upstream_error(VENDOR_LABEL, "invalid_params", f"task {status}")
    if status != "done":
        return None
    if not data.get("video_url"):
        raise GenerationAdapterError("providerErr_noResultUrl", vendor=VENDOR_LABEL)
    return data


class _SignedClient:
    """给共用轮询循环用的外壳:它只会 `get(path)`,这里把 `<req_key>/<task_id>` 翻成那次签名 POST。"""

    def __init__(self, http: RetryingClient, ak: str, sk: str) -> None:
        self._http = http
        self._ak = ak
        self._sk = sk

    def call(self, action: str, body: dict[str, Any]) -> httpx.Response:
        query = f"Action={action}&Version={VERSION}"
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = signed_headers(self._ak, self._sk, query, raw, service=SERVICE, region=REGION, host=HOST)
        return self._http.post(f"/?{query}", headers=headers, content=raw)

    def get(self, poll_path: str) -> httpx.Response:
        req_key, _, task_id = poll_path.partition("/")
        return self.call(QUERY_ACTION, {"req_key": req_key, "task_id": task_id})


def _credentials(context: GenerationAdapterContext) -> tuple[str, str]:
    ak = (context.api_key or "").strip()
    sk = str(context.options.get("sk") or "").strip()
    if not ak or not sk:
        raise GenerationAdapterError("providerErr_volcanoVisualKeysMissing")
    return ak, sk


def _payload(response: httpx.Response) -> dict[str, Any]:
    """错误放在 4xx 的**正文**里:先读正文里的业务码,读不出再看状态码。"""
    try:
        payload = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise GenerationAdapterError(
            "providerErr_upstreamUnavailable", vendor=VENDOR_LABEL, detail=response.text[:200]
        ) from exc
    raise_for_payload(payload)
    response.raise_for_status()
    return payload


class VolcanoOmniHumanAdapter(GenerationAdapter):
    vendor_id = "volcano-visual"
    media_kind = "video"
    supports_resume = True

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        body = build_body(request)
        with self._scope(context) as client:
            try:
                payload = _payload(client.call(SUBMIT_ACTION, body))
            except httpx.HTTPError as exc:
                raise self._http_error(exc, context) from exc
            task_id = str((payload.get("data") or {}).get("task_id") or "").strip()
            if not task_id:
                raise GenerationAdapterError("providerErr_noTaskIdDetail", vendor=VENDOR_LABEL, detail=str(payload)[:200])
            return self._collect(client, f"{body['req_key']}/{task_id}", request, context, output_dir)

    def resume(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        with self._scope(context) as client:
            return self._collect(client, poll_path, request, context, output_dir)

    def _scope(self, context: GenerationAdapterContext) -> "_Scope":
        ak, sk = _credentials(context)
        base = (context.base_url or f"https://{HOST}").rstrip("/")
        return _Scope(RetryingClient(base_url=base, timeout=60), ak, sk)

    def _collect(self, client: _SignedClient, poll_path: str, request: GenerationRequest,
                 context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        try:
            data, terminal = poll_until_ready(client, poll_path, extract_video, interval=POLL_INTERVAL_SECONDS,
                                              vendor=VENDOR_LABEL)
            target = output_dir / "generated.mp4"
            download_to_path(str(data["video_url"]), target)
        except httpx.HTTPError as exc:
            raise self._http_error(exc, context) from exc
        return GenerationResult(output_paths=[target], usage=metering_from_request(request),
                                raw_usage={"status": (terminal.get("data") or {}).get("status"),
                                           "aigc_meta_tagged": (terminal.get("data") or {}).get("aigc_meta_tagged")})

    def _http_error(self, exc: httpx.HTTPError, context: GenerationAdapterContext) -> GenerationAdapterError:
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                raise_for_payload(response.json())
            except GenerationAdapterError as categorized:
                return categorized
            except ValueError:
                pass
        category = http_status_category(response.status_code) if response is not None else None
        return upstream_error(VENDOR_LABEL, category, http_error_detail(exc, str(context.options.get("sk") or "") or None))


class _Scope:
    """`with` 住底下的 httpx 客户端,交出去的是签名外壳。"""

    def __init__(self, http: RetryingClient, ak: str, sk: str) -> None:
        self._http = http
        self._signed = _SignedClient(http, ak, sk)

    def __enter__(self) -> _SignedClient:
        self._http.__enter__()
        return self._signed

    def __exit__(self, *exc: object) -> None:
        self._http.__exit__(*exc)
