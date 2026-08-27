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
REFERENCE_AUDIO = "reference_audio"

#: **拿一段现成的视频当输入**,这是第三条路,和前两条都不一样。
#:
#: `source_video` 是**被改的那一段**:输出是它改过之后的样子,长度和内容都对得上(万相的
#: 视频编辑就是这个 —— 「把画面改成水彩风格」)。
#: `first_clip` 是**被接着往下拍的那一段**:输出以它开头,再往后长出新的内容(视频续写)。
#:
#: 两者都不是 `reference_video`:参考视频只提供风格和主体,它自己一帧都不出现在成片里。
#: 把三者混成一个角色的话,用户选「续写」拿到的会是一段重新生成的视频,而看不出哪里不对。
SOURCE_VIDEO = "source_video"
FIRST_CLIP = "first_clip"

#: **拿一段音频驱动画面** —— 口型同步、动作卡点。它不是参考音频(那只是"照这个风格来"),
#: 成片的节奏和口型是跟着它走的,所以两者不能混:选错了拿到的是一段对不上嘴的视频。
DRIVING_AUDIO = "driving_audio"

#: 全部角色。描述符(domain/generation/catalog)声明某个模型认哪几种,界面和智能体都读它。
SOURCE_ROLES = (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    REFERENCE_AUDIO,
    SOURCE_VIDEO,
    FIRST_CLIP,
    DRIVING_AUDIO,
)

#: **首尾帧**和**参考素材**是两回事,不是同一个东西的两种叫法。
#:
#: 首尾帧说的是「画面从这一格开始、到那一格结束」——它落在成片的第一帧和最后一帧上。
#: 参考素材说的是「照着这个人/这种风格/这段动作来」——它一帧都不出现在成片里,只influence。
#:
#: 两家接口都把这条界线画成**硬约束**,而不是建议。火山原话:
#:   `first/last frame content cannot be mixed with reference media content`
#: 所以描述符里它们分属两个互斥组:给了首帧就不能再给参考图,反过来也一样。此前我们把
#: 五个角色平铺成一串,界面上可以同时勾首帧和参考图 —— 提交必然 400,而用户看不出为什么。
KEYFRAME_ROLES = (FIRST_FRAME, LAST_FRAME)
REFERENCE_ROLES = (REFERENCE_IMAGE, REFERENCE_VIDEO, REFERENCE_AUDIO)
VIDEO_INPUT_ROLES = (SOURCE_VIDEO, FIRST_CLIP)
DRIVING_ROLES = (DRIVING_AUDIO,)


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
    FIRST_FRAME: ("first_frame_url",),
    LAST_FRAME: ("last_frame_url",),
    REFERENCE_IMAGE: ("reference_image_url",),
    REFERENCE_VIDEO: ("reference_video_url",),
    REFERENCE_AUDIO: ("reference_audio_url",),
    SOURCE_VIDEO: ("source_video_url", "video_url"),
    FIRST_CLIP: ("first_clip_url",),
    DRIVING_AUDIO: ("driving_audio_url",),
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
    untyped = _untyped_image_url(request, role)
    if untyped:
        return untyped
    path = request.source_for(role)
    return image_file_to_data_url(path) if path is not None else None


#: `image_url` 是个**不说角色的别名**:它只说"这张图是输入",而它到底是什么角色,取决于在生成
#: 什么 —— 视频的输入图是首帧(画面从它动起来),图像的输入图是参考图(图像没有"首帧"这回事)。
#:
#: 写成一条按 kind 分的规则,而不是让每个适配器各自解释一遍:此前火山图像那边自己读
#: `image_url` 当参考图,而 base 这里把它列在首帧名下 —— 同一个参数名,两处含义,谁都没写错,
#: 但读代码的人没法从任何一处看出全貌。
_UNTYPED_IMAGE_URL = "image_url"
_UNTYPED_IMAGE_ROLE_BY_KIND = {"video": FIRST_FRAME, "image": REFERENCE_IMAGE}


def _untyped_image_url(request: GenerationRequest, role: str) -> str | None:
    """`image_url` 在这次请求里算不算这个角色。"""
    if _UNTYPED_IMAGE_ROLE_BY_KIND.get(request.kind) != role:
        return None
    value = request.parameters.get(_UNTYPED_IMAGE_URL)
    return str(value) if value else None


def source_values(request: GenerationRequest, role: str) -> tuple[str, ...]:
    """取某个角色的**全部**素材。

    参考图可以给九张、参考视频三段(见 domain/generation/catalog 里各家的 `source_limits`),
    而 `source_value` 只会返回第一份。适配器此前一律走单数那个,于是用户挑了九张参考图,
    真正发出去的只有第一张 —— 不报错,只是效果不对,而且没人看得出来少了八张。

    首尾帧这种天然只有一份的角色照样可以用它,拿回来的元组长度就是 1。
    """
    urls = [str(value) for name in ROLE_URL_PARAMETERS.get(role, ()) for value in _as_list(request.parameters.get(name))]
    untyped = _untyped_image_url(request, role)
    if untyped and untyped not in urls:
        urls.append(untyped)
    if urls:
        return tuple(urls)
    return tuple(image_file_to_data_url(path) for path in request.sources_for(role))


def _as_list(value: Any) -> list[Any]:
    """参数里的 `<role>_url` 既可能是一个外链,也可能是一串。"""
    if value is None or value == "":
        return []
    return [one for one in value if one] if isinstance(value, (list, tuple)) else [value]


def first_frame_value(request: GenerationRequest) -> str | None:
    """图生视频的首帧。`source_value(request, FIRST_FRAME)` 的简写 —— 用得最多的那一个。"""
    return source_value(request, FIRST_FRAME)
