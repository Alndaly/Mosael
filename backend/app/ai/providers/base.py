from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
class ProviderContext:
    profile_id: str | None
    vendor: str
    api_key: str
    base_url: str = ""
    default_model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class GenerationProvider(ABC):
    name: str
    kind: str

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
    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> Path:
        """Run submit→poll→download synchronously; return the media file path."""


def sanitize_provider_error(message: str, credential: str | None) -> str:
    """Strip secrets and noise before an error can reach logs or clients (plan §18.5)."""
    text = message
    if credential:
        text = text.replace(credential, "***")
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1***", text)
    text = re.sub(r"(api[_-]?key[\"'=:\s]+)[A-Za-z0-9._-]+", r"\1***", text, flags=re.IGNORECASE)
    return text[:500]
