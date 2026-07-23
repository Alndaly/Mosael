"""Generation provider registry (plan §18.1): pluggable, never hardcoded in routes/UI."""

from __future__ import annotations

from app.ai.providers.base import GenerationProvider, GenerationRequest, GenerationResult, ProviderContext, ProviderError
from app.ai.providers.kling import KlingProvider
from app.ai.providers.openai_image import OpenAIImageProvider
from app.ai.providers.qwen_image import QwenImageProvider
from app.ai.providers.seedance import SeedanceProvider
from app.ai.providers.seedream import SeedreamProvider
from app.ai.providers.veo import VeoProvider

_PROVIDERS: dict[tuple[str, str], GenerationProvider] = {}


def _register(provider: GenerationProvider) -> None:
    _PROVIDERS[(provider.name, provider.kind)] = provider


_register(QwenImageProvider())
_register(SeedanceProvider())
_register(SeedreamProvider())
_register(VeoProvider())
_register(KlingProvider())
_register(OpenAIImageProvider("openai"))
_register(OpenAIImageProvider("openai-compatible"))


def get_provider(name: str, kind: str) -> GenerationProvider | None:
    return _PROVIDERS.get((name, kind))


__all__ = ["GenerationProvider", "GenerationRequest", "GenerationResult", "ProviderContext", "ProviderError", "get_provider"]
