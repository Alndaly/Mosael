from __future__ import annotations

import base64
import mimetypes
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any

import httpx

from app.core.token_estimate import estimate_text_tokens

"""
Generation provider contract (plan §18.2). A provider turns a validated
request into a downloaded media file; asset/artifact registration and job
bookkeeping happen in the domain runner, never here.
"""

MAX_NUM_IMAGES = 4
MAX_VIDEO_DURATION_SECONDS = 10
ALLOWED_VIDEO_RESOLUTIONS = ("480p", "720p", "1080p")


class ProviderError(RuntimeError):
    """Raised for provider failures; message must already be safe to surface."""


#: 一份输入素材**拿来干什么**。
#:
#: 各家的接口本来就带这个概念 —— Seedance / MiniMax 的 content 数组按 `role` 区分,
#: 可灵分 `image` 与 `image_tail`。我们这一层此前把它抹平成一个扁平的 Path 元组,谁是首帧
#: 靠「第 0 个」这条约定。于是尾帧、参考图、参考视频都没地方放:再加一个位置约定,每个适配器
#: 都得记住第几个是什么,而记错了不会报错,只会生成出别的东西。
FIRST_FRAME = "first_frame"
LAST_FRAME = "last_frame"
REFERENCE_IMAGE = "reference_image"
REFERENCE_VIDEO = "reference_video"

#: 全部角色。描述符(domain/generation/catalog)声明某个模型认哪几种,界面和智能体都读它。
SOURCE_ROLES = (FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, REFERENCE_VIDEO)


@dataclass(frozen=True)
class SourceAsset:
    """一份输入素材,带着它的用途。"""

    role: str
    path: Path


@dataclass(frozen=True)
class GenerationRequest:
    kind: str  # "image" | "video"
    model: str
    prompt: str
    negative_prompt: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    sources: tuple[SourceAsset, ...] = ()

    def source_for(self, role: str) -> Path | None:
        """取这个角色的素材;没有就是 None。同一角色给了多份时取第一份。"""
        for item in self.sources:
            if item.role == role:
                return item.path
        return None

    def sources_for(self, role: str) -> tuple[Path, ...]:
        """取这个角色的**全部**素材 —— 参考图可以给多张。"""
        return tuple(item.path for item in self.sources if item.role == role)


@dataclass(frozen=True)
class GenerationResult:
    output_path: Path
    usage: dict[str, Any] = field(default_factory=dict)
    raw_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderContext:
    profile_id: str | None
    vendor: str
    api_key: str
    base_url: str = ""
    default_model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationCallbacks:
    """Optional live channel from a provider's poll loop back to the job.

    on_progress reports a coarse fraction (0..1) plus a user-facing message; is_cancelled
    is checked between provider round-trips so a user cancel can stop the remote work
    (e.g. ComfyUI /interrupt) instead of merely abandoning it. Providers that opt in set
    supports_callbacks and accept the keyword; everyone else keeps the old signature —
    the runner only passes callbacks where they are understood.
    """

    on_progress: Any  # Callable[[float, str], None]
    is_cancelled: Any  # Callable[[], bool]


class GenerationProvider(ABC):
    name: str
    kind: str
    #: Providers that accept generate(..., callbacks=...) set this True.
    supports_callbacks: bool = False

    def requires_credentials(self) -> bool:
        return True

    def validate_request(self, request: GenerationRequest) -> None:
        """Shared guardrails (plan §18.5); providers may add their own."""
        if not request.prompt.strip():
            raise ProviderError("Prompt must not be empty")
        if request.kind == "image":
            num_images = int(request.parameters.get("num_images", 1))
            if not 1 <= num_images <= MAX_NUM_IMAGES:
                raise ProviderError(f"num_images must be between 1 and {MAX_NUM_IMAGES}")
        if request.kind == "video":
            duration = float(request.parameters.get("duration_seconds", 5))
            if not 1 <= duration <= MAX_VIDEO_DURATION_SECONDS:
                raise ProviderError(f"duration_seconds must be between 1 and {MAX_VIDEO_DURATION_SECONDS}")
            resolution = str(request.parameters.get("resolution", "720p"))
            if resolution not in ALLOWED_VIDEO_RESOLUTIONS:
                raise ProviderError(f"resolution must be one of {', '.join(ALLOWED_VIDEO_RESOLUTIONS)}")

    @abstractmethod
    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        """Run submit→poll→download synchronously; return the media file plus provider usage."""


def metering_from_request(request: GenerationRequest) -> dict[str, Any]:
    """Provider-neutral metering facts that can be priced even before a provider returns usage."""
    units: dict[str, Any] = {"requests": 1}
    prompt_text = "\n".join(part for part in (request.prompt, request.negative_prompt) if part.strip())
    if prompt_text:
        units["input_characters"] = len(prompt_text)
        units["input_tokens"] = estimate_text_tokens(prompt_text)
        units["total_tokens"] = units["input_tokens"]
        units["token_estimate"] = True
    if request.kind == "image":
        size = str(request.parameters.get("size") or "")
        units.update(
            {
                "images": int(request.parameters.get("num_images", 1)),
                "source_images": len(request.sources),
            }
        )
        if size:
            units["size"] = size.replace("*", "x")
    elif request.kind == "video":
        units.update(
            {
                "videos": 1,
                "video_seconds": float(request.parameters.get("duration_seconds", 5)),
                "resolution": str(request.parameters.get("resolution", "720p")),
                "aspect_ratio": str(request.parameters.get("aspect_ratio", "")),
                "source_images": len(request.sources),
            }
        )
    return units


def sanitize_provider_error(message: str, credential: str | None) -> str:
    """Strip secrets and noise before an error can reach logs or clients (plan §18.5)."""
    text = message
    if credential:
        text = text.replace(credential, "***")
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1***", text)
    text = re.sub(r"(api[_-]?key[\"'=:\s]+)[A-Za-z0-9._-]+", r"\1***", text, flags=re.IGNORECASE)
    return text[:500]


def provider_http_error(label: str, exc: httpx.HTTPError, credential: str | None) -> str:
    """Surface provider HTTP failures with the response body when available.

    httpx's default message links to MDN but omits the provider's JSON error, which is the
    part users need to fix a model name, unsupported size, or missing capability.
    """
    message = f"{label}: {exc}"
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.text.strip()
        except Exception:  # noqa: BLE001 - best-effort diagnostics only
            body = ""
        if body:
            message = f"{message}; body: {body[:800]}"
    return sanitize_provider_error(message, credential)


def image_file_to_base64(path: Path) -> tuple[str, str]:
    """Return (mime_type, base64) for a local image source file."""
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return mime_type, base64.b64encode(path.read_bytes()).decode("ascii")


def image_file_to_data_url(path: Path) -> str:
    """Return a data URL for providers that accept image URLs or base64-like image fields."""
    mime_type, data = image_file_to_base64(path)
    return f"data:{mime_type};base64,{data}"


#: 异步任务的默认节奏。各家可以覆盖,但没有理由的话就用这一份 —— 此前七个文件各定义了一次
#: 自己的 POLL_INTERVAL,而它们的值本来就一样。
POLL_INTERVAL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 300.0


def poll_until_ready(
    client: Any,
    poll_path: str,
    extract: "Callable[[dict[str, Any]], str | None]",
    *,
    interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = POLL_TIMEOUT_SECONDS,
    timed_out_message: str = "Generation timed out",
) -> tuple[str, dict[str, Any]]:
    """轮询一个异步任务到终态,返回 (产物地址, 终态回包)。

    几乎所有外部生成 API 都是同一个形状:提交拿 id → 轮询到终态 → 下载。此前**六家各写了一遍
    这个循环**,各自定义间隔、各自抛超时 —— 代价不是行数,是每家都可能漏掉一件事,而没有任何
    机制能发现谁漏了。

    `extract` 负责读懂那一家的终态:拿到地址就回地址,还没结束回 None,失败**自己抛**
    (它才知道那家把失败原因放在哪个字段)。

    计时用 `time.monotonic()` 而不是 `time.time()`:墙钟会跳(NTP 校时、夏令时),跳一下
    要么把还在跑的任务判成超时,要么让它多等一个小时。六家原本都用的是墙钟。
    """
    deadline = time.monotonic() + timeout
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(poll_path)
        response.raise_for_status()
        payload = response.json()
        url = extract(payload)
        if url:
            return url, payload
        time.sleep(interval)
    # 超时文案让调用方给:有几家写的是自己的措辞(「MiniMax 视频生成超时」),那句话会一路
    # 显示到用户眼前,收成一份通用句子等于把"是哪一家超时了"这个信息删掉。
    raise ProviderError(timed_out_message)


#: 每个角色对应的「直接给个 url」参数名。界面既可以选素材库里的图,也可以粘一个外链;
#: 两条路进来的东西是同一样,所以在这里合流,而不是让每个适配器各写一遍回落。
ROLE_URL_PARAMETERS = {
    FIRST_FRAME: ("first_frame_url", "image_url"),
    LAST_FRAME: ("last_frame_url",),
    REFERENCE_IMAGE: ("reference_image_url",),
    REFERENCE_VIDEO: ("reference_video_url",),
}


def source_value(request: GenerationRequest, role: str) -> str | None:
    """取某个角色的素材,拿成可以直接塞进请求体的字符串:**先看参数里的 url,再回落上传的文件**。

    住在这里而不是某一家的模块里 —— 各家取法完全一样,而它此前(只有首帧那一版)定义在
    kling.py:万相得反过来 import 那一家,seedance 干脆整段抄了一遍。一个共享约定住在某个
    供应商的文件里,读的人只会以为它是那家特有的东西。
    """
    for name in ROLE_URL_PARAMETERS.get(role, ()):
        value = request.parameters.get(name)
        if value:
            return str(value)
    path = request.source_for(role)
    return image_file_to_data_url(path) if path is not None else None


def first_frame_value(request: GenerationRequest) -> str | None:
    """图生视频的首帧。`source_value(request, FIRST_FRAME)` 的简写 —— 用得最多的那一个。"""
    return source_value(request, FIRST_FRAME)
