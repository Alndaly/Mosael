"""Generation provider registry (plan §18.1): pluggable, never hardcoded in routes/UI."""

from __future__ import annotations

from app.ai.providers.base import GenerationProvider, GenerationRequest, ProviderError
from app.ai.providers.mock import MockImageProvider, MockVideoProvider
from app.ai.providers.qwen_image import QwenImageProvider
from app.ai.providers.seedance import SeedanceProvider

_PROVIDERS: dict[tuple[str, str], GenerationProvider] = {}


def _register(provider: GenerationProvider) -> None:
    _PROVIDERS[(provider.name, provider.kind)] = provider


_register(MockImageProvider())
_register(MockVideoProvider())
_register(QwenImageProvider())
_register(SeedanceProvider())


def get_provider(name: str, kind: str) -> GenerationProvider | None:
    return _PROVIDERS.get((name, kind))


__all__ = ["GenerationProvider", "GenerationRequest", "ProviderError", "get_provider"]
