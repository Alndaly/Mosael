"""AI Provider 的稳定公共 Interface。

调用方从这里取得能力契约和 Registry 查询；``contracts`` 定义 Seam，``adapters`` 保存供应商
协议 Implementation，``registry`` 是唯一装配入口。领域 Module 不应直接选择具体 Adapter。
"""

from app.ai.providers.adapters.alibaba.dashscope.speech import (
    DASHSCOPE_NATIVE_BASE,
    BailianSpeechAdapter,
    CosyVoiceSpeechAdapter,
    extract_bailian_audio_url,
    is_cosyvoice,
    resolve_dashscope_native_base,
)
from app.ai.providers.adapters.microsoft.edge_speech import EDGE_BUILTIN_VOICES, EdgeSpeechAdapter
from app.ai.providers.adapters.openai.speech import OpenAISpeechAdapter
from app.ai.providers.adapters.bytedance.volcano.speech import (
    PODCAST_SPEAKERS,
    VOLCANO_BUILTIN_VOICES,
    VolcanoSpeechAdapter,
)
from app.ai.providers.adapters.bytedance.volcano.podcast import (
    PodcastAction,
    PodcastSynthesisError,
    PodcastSynthesisResult,
    synthesize_volcano_podcast,
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
    GenerationProgressCallbacks,
    GenerationAdapter,
    GenerationRequest,
    GenerationResult,
    GenerationAdapterContext,
    GenerationAdapterError,
    SourceAsset,
    allowed_source_url_parameters,
    roles_supplied_via_url,
)
from app.ai.providers.contracts.speech import (
    MAX_PARALLEL_SPEECH_REQUESTS,
    SPEECH_REQUEST_TIMEOUT_SECONDS,
    SpeechSynthesisRequest,
    SpeechSynthesisError,
    SpeechAdapter,
    synthesize_many,
)
from app.ai.providers.registry import (
    REMOTE_SPEECH_ADAPTERS,
    build_speech_adapter,
    get_generation_adapter,
    has_capability_implementation,
    connection_vendor_for_speech_engine,
)

__all__ = [
    "DASHSCOPE_NATIVE_BASE",
    "DRIVING_AUDIO",
    "EDGE_BUILTIN_VOICES",
    "FIRST_CLIP",
    "FIRST_FRAME",
    "LAST_FRAME",
    "PODCAST_SPEAKERS",
    "PodcastAction",
    "PodcastSynthesisError",
    "PodcastSynthesisResult",
    "REFERENCE_AUDIO",
    "REFERENCE_IMAGE",
    "REFERENCE_VIDEO",
    "REMOTE_SPEECH_ADAPTERS",
    "MAX_PARALLEL_SPEECH_REQUESTS",
    "SPEECH_REQUEST_TIMEOUT_SECONDS",
    "SOURCE_ROLES",
    "SOURCE_VIDEO",
    "VOLCANO_BUILTIN_VOICES",
    "BailianSpeechAdapter",
    "CosyVoiceSpeechAdapter",
    "EdgeSpeechAdapter",
    "GenerationProgressCallbacks",
    "GenerationAdapter",
    "GenerationRequest",
    "GenerationResult",
    "OpenAISpeechAdapter",
    "GenerationAdapterContext",
    "GenerationAdapterError",
    "SourceAsset",
    "SpeechSynthesisRequest",
    "SpeechSynthesisError",
    "SpeechAdapter",
    "VolcanoSpeechAdapter",
    "allowed_source_url_parameters",
    "build_speech_adapter",
    "extract_bailian_audio_url",
    "get_generation_adapter",
    "has_capability_implementation",
    "is_cosyvoice",
    "resolve_dashscope_native_base",
    "roles_supplied_via_url",
    "synthesize_many",
    "synthesize_volcano_podcast",
    "connection_vendor_for_speech_engine",
]
