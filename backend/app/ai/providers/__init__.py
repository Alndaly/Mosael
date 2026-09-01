"""AI Provider 的稳定公共 Interface。

调用方从这里取得能力契约和 Registry 查询；``contracts`` 定义 Seam，``adapters`` 保存供应商
协议 Implementation，``registry`` 是唯一装配入口。领域 Module 不应直接选择具体 Adapter。
"""

from app.ai.providers.adapters.alibaba.speech import (
    DASHSCOPE_NATIVE_BASE,
    BailianTTS,
    CosyVoiceTTS,
    extract_bailian_audio_url,
    is_cosyvoice,
    resolve_dashscope_native_base,
)
from app.ai.providers.adapters.edge import EDGE_BUILTIN_VOICES, EdgeTTS
from app.ai.providers.adapters.openai.speech import OpenAITTS
from app.ai.providers.adapters.volcano import (
    PODCAST_SPEAKERS,
    VOLCANO_BUILTIN_VOICES,
    VolcanoTTS,
)
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
    allowed_source_url_parameters,
    roles_supplied_via_url,
)
from app.ai.providers.contracts.speech import (
    REMOTE_PARALLEL,
    REMOTE_TIMEOUT_SECONDS,
    SpeechRequest,
    TTSError,
    TTSProvider,
    synthesize_many,
)
from app.ai.providers.registry import (
    REMOTE_ENGINES,
    build_remote_provider,
    get_provider,
    vendor_for_engine,
)

__all__ = [
    "DASHSCOPE_NATIVE_BASE",
    "DRIVING_AUDIO",
    "EDGE_BUILTIN_VOICES",
    "FIRST_CLIP",
    "FIRST_FRAME",
    "LAST_FRAME",
    "PODCAST_SPEAKERS",
    "REFERENCE_AUDIO",
    "REFERENCE_IMAGE",
    "REFERENCE_VIDEO",
    "REMOTE_ENGINES",
    "REMOTE_PARALLEL",
    "REMOTE_TIMEOUT_SECONDS",
    "SOURCE_ROLES",
    "SOURCE_VIDEO",
    "VOLCANO_BUILTIN_VOICES",
    "BailianTTS",
    "CosyVoiceTTS",
    "EdgeTTS",
    "GenerationCallbacks",
    "GenerationProvider",
    "GenerationRequest",
    "GenerationResult",
    "OpenAITTS",
    "ProviderContext",
    "ProviderError",
    "SourceAsset",
    "SpeechRequest",
    "TTSError",
    "TTSProvider",
    "VolcanoTTS",
    "allowed_source_url_parameters",
    "build_remote_provider",
    "extract_bailian_audio_url",
    "get_provider",
    "is_cosyvoice",
    "resolve_dashscope_native_base",
    "roles_supplied_via_url",
    "synthesize_many",
    "vendor_for_engine",
]
