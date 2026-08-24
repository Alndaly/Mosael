"""Generation provider registry (plan §18.1): pluggable, never hardcoded in routes/UI."""

from __future__ import annotations

from app.ai.providers.base import (
    GenerationCallbacks,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
)
from app.ai.providers.comfyui import ComfyUIProvider
from app.ai.providers.kling import KlingProvider
from app.ai.providers.openai_image import OpenAIImageProvider
from app.ai.providers.qwen_image import QwenImageProvider
from app.ai.providers.wan_video import WanVideoProvider
from app.ai.providers.seedance import SeedanceProvider
from app.ai.providers.seedream import SeedreamProvider
from app.ai.providers.minimax_video import MiniMaxVideoProvider
from app.ai.providers.veo import VeoProvider

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
    "GenerationCallbacks",
    "GenerationProvider",
    "GenerationRequest",
    "GenerationResult",
    "ProviderContext",
    "ProviderError",
    "get_provider",
]
