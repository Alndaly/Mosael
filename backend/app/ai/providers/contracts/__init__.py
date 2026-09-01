"""供应商 Adapter 共同满足的能力契约。

这个包只定义调用方需要学习的 Interface；具体供应商协议、鉴权和字段翻译属于
``providers.adapters`` 的 Implementation，注册和选择属于 ``providers.registry``。
"""

from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_CLIP,
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_AUDIO,
    REFERENCE_IMAGE,
    REFERENCE_VIDEO,
    SOURCE_ROLES,
    SOURCE_VIDEO,
    GenerationCallbacks,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    SourceAsset,
)
from app.ai.providers.contracts.speech import (
    SpeechRequest,
    TTSError,
    TTSProvider,
    synthesize_many,
)

__all__ = [
    "DRIVING_AUDIO",
    "FIRST_CLIP",
    "FIRST_FRAME",
    "LAST_FRAME",
    "REFERENCE_AUDIO",
    "REFERENCE_IMAGE",
    "REFERENCE_VIDEO",
    "SOURCE_ROLES",
    "SOURCE_VIDEO",
    "GenerationCallbacks",
    "GenerationProvider",
    "GenerationRequest",
    "GenerationResult",
    "ProviderContext",
    "ProviderError",
    "SourceAsset",
    "SpeechRequest",
    "TTSError",
    "TTSProvider",
    "synthesize_many",
]
