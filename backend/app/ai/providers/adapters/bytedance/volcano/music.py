"""火山引擎 AI 音乐生成(人声歌曲 / 纯音乐 BGM)。

官方文档(音视频理解与处理 → AI 音乐生成大模型,2026-09-25 核):
- 公共字段:https://www.volcengine.com/docs/84992/1967910
- 人声歌曲 GenSongV4 / GenSongForTime:https://www.volcengine.com/docs/84992/2091679
- 纯音乐 GenBGM / GenBGMForTime:https://www.volcengine.com/docs/84992/2100970
- 查询任务 QuerySong:https://www.volcengine.com/docs/84992/2100960
- 错误码:https://www.volcengine.com/docs/84992/1404675
- 计费:https://www.volcengine.com/docs/84992/1404661
- 签名:https://www.volcengine.com/docs/6369/67269

**异步**:`POST https://open.volcengineapi.com/?Action=<X>&Version=2024-08-12`(JSON 体)交回
`Result.TaskID`,再用 `QuerySong` 查到终态(Status 0 排队 / 1 处理中 / 2 成功 / 3 失败)。
**每一次请求都要 AK/SK 签名**(服务名 `imagination`、地域 `cn-beijing`),没有 API Key 这条路。

**查询也是签名的 POST**,而共用的轮询循环(contracts.generation.poll_until_ready)只会 `GET` 一条
路径。所以这里给它一个很小的客户端外壳:`get("QuerySong/<TaskID>")` 在里面变成那次签名 POST。
回执照样在开始等之前落库(ADR 0019),重启后拿同一个回执接着查,不再提交。

模型 id 就是 Action 名(见 catalog 的 AUDIO_BUILTIN_MODELS):`*ForTime` 按秒后付费,`GenSongV4` /
`GenBGM` 走预付费资源包。账号开通的是哪一种就只能用哪一种。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.ai.audio_files import download_audio
from app.ai.providers.adapters.bytedance.volcano.openapi_sign import HOST, signed_headers
from app.ai.providers.contracts.generation import (
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    http_error_detail,
    http_status_category,
    metering_from_request,
    poll_until_ready,
    upstream_error,
)
from app.core.http_retry import RetryingClient

SERVICE = "imagination"
VERSION = "2024-08-12"
VENDOR_LABEL = "火山引擎音乐"
POLL_INTERVAL_SECONDS = 5.0
QUERY_ACTION = "QuerySong"

#: 人声歌曲的两个 Action 与纯音乐的两个 Action。不在这里的模型 id 不猜它是哪一种。
SONG_ACTIONS = ("GenSongForTime", "GenSongV4")
BGM_ACTIONS = ("GenBGMForTime", "GenBGM")

#: 错误码 → 失败类别(文档 1404675 的表)。
_CODE_CATEGORY = {
    100001: "unavailable",  # ServerError
    100010: "invalid_params",  # RequestParamsError
    100011: "not_entitled",  # ServerIpLimit(境外 IP 不让用)
    200020: "auth",  # InvalidSign
    200021: "auth",  # AuthExpired
    200022: "balance",  # APIOutOfLimit
    200023: "rate_limited",  # APIOutOfQps
    200024: "auth",  # AuthDisable
    200026: "invalid_params",  # TosBucketLimit
    200027: "balance",  # APIOutOfTime(资源包过期)
    200028: "not_entitled",  # APINoSource(没有开通 / 没有资源包)
    300030: "unavailable",  # AlgorithmError
    300052: "invalid_params",  # TaskNotFound
    300061: "content_blocked",  # InputLyricsPlagiarized
    300062: "content_blocked",  # OutputLyricsPlagiarized
    300063: "content_blocked",  # InputNotSafe
    300064: "content_blocked",  # OutputNotSafe
    300065: "invalid_params",  # NoChineseInInputText
    300066: "invalid_params",  # InvalidLang
    300067: "unavailable",  # ServerErrorSemantic, need retry
    400040: "rate_limited",  # QueueFull
}


def action_for(model: str) -> str:
    name = (model or "").strip()
    if name not in SONG_ACTIONS + BGM_ACTIONS:
        raise GenerationAdapterError("providerErr_upstreamInvalidParams", vendor=VENDOR_LABEL, detail=f"unknown model {name!r}")
    return name


def build_body(request: GenerationRequest) -> dict[str, Any]:
    """宿主请求 → 这一个 Action 的请求体。只发用户给了的格子(时长、版本、歌词都是可选的)。"""
    action = action_for(request.model)
    duration = request.parameters.get("duration_seconds")
    if action in BGM_ACTIONS:
        # 纯音乐只有一段描述(`Text`,只收中文)。版本默认且已经全量是 v5.0,不必发。
        body: dict[str, Any] = {"Text": request.prompt}
        if duration is not None:
            body["Duration"] = int(duration)
        return body
    body = {}
    lyrics = str(request.parameters.get("lyrics") or "").strip()
    # 文档:v4.x 上歌词和描述只能给一个、同时给以歌词为准。描述符标了 lyrics_excludes_prompt,
    # 两段都给的请求在提交前就被拦下,所以到这里只会有其中一段。
    if lyrics:
        body["Lyrics"] = lyrics
    elif request.prompt.strip():
        body["Prompt"] = request.prompt
    if duration is not None:
        body["Duration"] = int(duration)
    version = request.parameters.get("model_version")
    if version:
        body["ModelVersion"] = str(version)
    return body


def _code_of(payload: dict[str, Any]) -> tuple[int | None, str]:
    """回包里的错误:顶层 `Code`/`Message`,或 `ResponseMetadata.Error`。成功回 (None, "")。"""
    error = (payload.get("ResponseMetadata") or {}).get("Error") or {}
    code = payload.get("Code")
    if isinstance(error, dict) and error:
        raw = error.get("CodeN") or error.get("Code") or code
        message = f"{error.get('Code') or ''} {error.get('Message') or ''}".strip()
    elif code not in (None, 0, "0"):
        raw, message = code, str(payload.get("Message") or "")
    else:
        return None, ""
    try:
        number = int(raw)
    except (TypeError, ValueError):
        number = -1
    return number, message or str(raw)


def raise_for_payload(payload: dict[str, Any]) -> None:
    number, message = _code_of(payload)
    if number is not None:
        raise upstream_error(VENDOR_LABEL, _CODE_CATEGORY.get(number), f"{number} {message}".strip())


def extract_song(payload: dict[str, Any]) -> dict[str, Any] | None:
    """QuerySong 的回包:成功回 SongDetail,还在跑回 None,失败按错误码抛。"""
    raise_for_payload(payload)
    result = payload.get("Result") or {}
    status = result.get("Status")
    if status == 3:
        reason = result.get("FailureReason") or {}
        try:
            number = int(reason.get("Code"))
        except (TypeError, ValueError):
            number = -1
        raise upstream_error(VENDOR_LABEL, _CODE_CATEGORY.get(number), f"{reason.get('Code') or ''} {reason.get('Msg') or ''}".strip() or "failed")
    if status != 2:
        return None
    detail = result.get("SongDetail") or {}
    if not detail.get("AudioUrl"):
        raise GenerationAdapterError("providerErr_noResultUrl", vendor=VENDOR_LABEL)
    return detail


class _SignedClient:
    """给共用轮询循环用的外壳:它只会 `get(path)`,这里把 `QuerySong/<TaskID>` 翻成签名 POST。"""

    def __init__(self, http: RetryingClient, ak: str, sk: str) -> None:
        self._http = http
        self._ak = ak
        self._sk = sk

    def call(self, action: str, body: dict[str, Any]) -> httpx.Response:
        query = f"Action={action}&Version={VERSION}"
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = signed_headers(self._ak, self._sk, query, raw, service=SERVICE)
        return self._http.post(f"/?{query}", headers=headers, content=raw)

    def get(self, poll_path: str) -> httpx.Response:
        action, _, task_id = poll_path.partition("/")
        return self.call(action or QUERY_ACTION, {"TaskID": task_id})


def _credentials(context: GenerationAdapterContext) -> tuple[str, str]:
    ak = (context.api_key or "").strip()
    sk = str(context.options.get("sk") or "").strip()
    if not ak or not sk:
        raise GenerationAdapterError("providerErr_volcanoMusicKeysMissing")
    return ak, sk


class VolcanoMusicAdapter(GenerationAdapter):
    vendor_id = "volcano-music"
    media_kind = "audio"
    supports_resume = True

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        action = action_for(request.model)
        body = build_body(request)
        with self._client(context) as client:
            try:
                response = client.call(action, body)
                payload = _json_or_error(response, context)
            except httpx.HTTPError as exc:
                raise _http_error(exc, context) from exc
            raise_for_payload(payload)
            task_id = str((payload.get("Result") or {}).get("TaskID") or "").strip()
            if not task_id:
                raise GenerationAdapterError("providerErr_noTaskIdDetail", vendor=VENDOR_LABEL, detail=str(payload)[:200])
            return self._collect(client, f"{QUERY_ACTION}/{task_id}", request, context, output_dir)

    def resume(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        with self._client(context) as client:
            return self._collect(client, poll_path, request, context, output_dir)

    def _client(self, context: GenerationAdapterContext) -> "_ClientScope":
        ak, sk = _credentials(context)
        base = (context.base_url or f"https://{HOST}").rstrip("/")
        return _ClientScope(RetryingClient(base_url=base, timeout=60), ak, sk)

    def _collect(
        self, client: _SignedClient, poll_path: str, request: GenerationRequest,
        context: GenerationAdapterContext, output_dir: Path,
    ) -> GenerationResult:
        try:
            detail, terminal = poll_until_ready(
                client, poll_path, extract_song, interval=POLL_INTERVAL_SECONDS, vendor=VENDOR_LABEL,
            )
            # 文档:地址默认是 wav,转码后可能是 mp4 —— 扩展名由 audio_files 按回包定(mp4 容器记成 m4a)。
            target = download_audio(str(detail["AudioUrl"]), output_dir, fallback=".wav")
        except httpx.HTTPError as exc:
            raise _http_error(exc, context) from exc
        usage = metering_from_request(request)
        # 后付费按「成功生成的音频秒数」计(文档 1404661),回包的 SongDetail.Duration 就是那个数。
        try:
            seconds = float(detail.get("Duration"))
        except (TypeError, ValueError):
            seconds = 0.0
        if seconds > 0:
            usage["audio_seconds"] = seconds
        return GenerationResult(output_paths=[target], usage=usage, raw_usage=_scrubbed(terminal))


class _ClientScope:
    """`with` 住底下的 httpx 客户端,交出去的是签名外壳。"""

    def __init__(self, http: RetryingClient, ak: str, sk: str) -> None:
        self._http = http
        self._signed = _SignedClient(http, ak, sk)

    def __enter__(self) -> _SignedClient:
        self._http.__enter__()
        return self._signed

    def __exit__(self, *exc: object) -> None:
        self._http.__exit__(*exc)


def _json_or_error(response: httpx.Response, context: GenerationAdapterContext) -> dict[str, Any]:
    """火山把错误放在 4xx 的**正文**里,先读正文再判状态码 —— 正文里的错误码比状态码说得清。"""
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


def _http_error(exc: httpx.HTTPError, context: GenerationAdapterContext) -> GenerationAdapterError:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            raise_for_payload(response.json())
        except GenerationAdapterError as categorized:
            return categorized
        except ValueError:
            pass
    category = http_status_category(response.status_code) if response is not None else None
    secret = str(context.options.get("sk") or "") or None
    return upstream_error(VENDOR_LABEL, category, http_error_detail(exc, secret))


def _scrubbed(payload: dict[str, Any]) -> dict[str, Any]:
    """记进用量的那一份:任务号、状态、时长 —— 歌词和字幕时间轴不必落进用量表。"""
    result = payload.get("Result") or {}
    detail = result.get("SongDetail") or {}
    return {"TaskID": result.get("TaskID"), "Status": result.get("Status"), "Duration": detail.get("Duration")}
