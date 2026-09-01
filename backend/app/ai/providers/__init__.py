"""供应商适配器注册表:pluggable, never hardcoded in routes/UI.

**Adapter Implementation 按供应商组织,能力 Interface 单独放在 contracts。**
``adapters/`` 里的每个名字是一套连接协议；一家横跨几种能力时，能力是它内部的模块名
（例如 ``adapters/alibaba/image.py``、``video.py``、``speech.py``）—— 百炼的 qwen
图像与万相视频共用一把 Key、同样的 HTTP 形状，
没理由分处两棵树。一套协议服务多种能力的网关(comfyui/、evolink.py)按同一规矩
各成一个单元。公共能力契约在 ``contracts/``，下载 Seam 在 ``media_transfer.py``；
本 Module 只保留稳定公共 Interface，注册装配随后收敛到 ``registry.py``。
"""

from __future__ import annotations

from app.ai.providers.contracts.generation import (
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
    allowed_source_url_parameters,
    roles_supplied_via_url,
)
from app.ai.providers.adapters.comfyui import ComfyUIProvider
from app.ai.providers.adapters.kuaishou.kling import KlingProvider
from app.ai.providers.adapters.openai.image import OpenAIImageProvider
from app.ai.providers.adapters.alibaba.image import QwenImageProvider
from app.ai.providers.adapters.alibaba.video import WanVideoProvider
from app.ai.providers.adapters.bytedance.video import SeedanceProvider
from app.ai.providers.adapters.bytedance.image import SeedreamProvider
from app.ai.providers.adapters.minimax import MiniMaxVideoProvider
from app.ai.providers.adapters.google import VeoProvider
from app.ai.providers.adapters.evolink import EvolinkProvider

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
_register(EvolinkProvider("image"))
_register(EvolinkProvider("video"))


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
    "allowed_source_url_parameters",
    "roles_supplied_via_url",
]
