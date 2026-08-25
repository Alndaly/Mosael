"""Generation provider registry (plan §18.1): pluggable, never hardcoded in routes/UI."""

from __future__ import annotations

from app.ai.providers.base import (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    SOURCE_ROLES,
    GenerationCallbacks,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    SourceAsset,
)
from app.ai.providers.comfyui import ComfyUIProvider
from app.ai.providers.video.kling import KlingProvider
from app.ai.providers.image.openai import OpenAIImageProvider
from app.ai.providers.image.qwen import QwenImageProvider
from app.ai.providers.video.wan import WanVideoProvider
from app.ai.providers.video.seedance import SeedanceProvider
from app.ai.providers.image.seedream import SeedreamProvider
from app.ai.providers.video.minimax import MiniMaxVideoProvider
from app.ai.providers.video.veo import VeoProvider

_PROVIDERS: dict[tuple[str, str], GenerationProvider] = {}


def _register(provider: GenerationProvider) -> None:
    _PROVIDERS[(provider.name, provider.kind)] = provider


_register(QwenImageProvider())
_register(WanVideoProvider())
_register(SeedanceProvider())
_register(SeedreamProvider())
_register(MiniMaxVideoProvider())
_register(VeoProvider())
_register(KlingProvider())
_register(OpenAIImageProvider("openai"))
_register(OpenAIImageProvider("openai-compatible"))
_register(ComfyUIProvider("image"))
_register(ComfyUIProvider("video"))


def get_provider(name: str, kind: str) -> GenerationProvider | None:
    return _PROVIDERS.get((name, kind))


__all__ = [
    "FIRST_FRAME",
    "LAST_FRAME",
    "REFERENCE_IMAGE",
    "REFERENCE_VIDEO",
    "SOURCE_ROLES",
    "SourceAsset",
    "GenerationCallbacks",
    "GenerationProvider",
    "GenerationRequest",
    "GenerationResult",
    "ProviderContext",
    "ProviderError",
    "get_provider",
]
