"""供应商适配器注册表:pluggable, never hardcoded in routes/UI.

**这一层按供应商组织,不按能力。** 顶层每个名字都是一家供应商(alibaba/ bytedance/
openai/ kuaishou/ google.py minimax.py volcano.py edge.py comfyui/ evolink.py);
一家跨几种能力时,能力是它内部的模块名(alibaba/image.py、alibaba/video.py、
alibaba/speech.py)—— 百炼的 qwen 图像与万相视频共用一把 Key、同样的 HTTP 形状,
没理由分处两棵树。一套协议服务多种能力的网关(comfyui/、evolink.py)按同一规矩
各成一个单元。仅有的三个例外是公共的:base.py(图/视频契约)、speech/(语音契约+
注册表门面)、media_transfer.py(下载缝)。
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
from app.ai.providers.comfyui import ComfyUIProvider
from app.ai.providers.kuaishou.kling import KlingProvider
from app.ai.providers.openai.image import OpenAIImageProvider
from app.ai.providers.alibaba.image import QwenImageProvider
from app.ai.providers.alibaba.video import WanVideoProvider
from app.ai.providers.bytedance.video import SeedanceProvider
from app.ai.providers.bytedance.image import SeedreamProvider
from app.ai.providers.minimax import MiniMaxVideoProvider
from app.ai.providers.google import VeoProvider
from app.ai.providers.evolink import EvolinkProvider

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
