from __future__ import annotations

import base64
import mimetypes
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.domain.usage import estimate_text_tokens

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


@dataclass(frozen=True)
class GenerationRequest:
    kind: str  # "image" | "video"
    model: str
    prompt: str
    negative_prompt: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    source_files: tuple[Path, ...] = ()


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
                "source_images": len(request.source_files),
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
                "source_images": len(request.source_files),
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
