"""语音这一侧的门面。

适配器本身已经搬进 `ai/providers/speech/` —— 一个供应商适配器的角色与它输出什么介质无关。
这里留下的是**这个部署现在能用什么**:引擎目录(catalog)要读本地模型的就绪状态,那是
audio 的事,搬过去会让 ai 反过来依赖 audio 而成环。

对外仍从这一个名字出:调用方问的是「语音引擎」这个概念,不该关心它由哪两处拼成。
"""

from app.ai.providers.speech import (
    DASHSCOPE_NATIVE_BASE,
    EDGE_BUILTIN_VOICES,
    PODCAST_SPEAKERS,
    REMOTE_ENGINES,
    REMOTE_PARALLEL,
    REMOTE_TIMEOUT_SECONDS,
    VOLCANO_BUILTIN_VOICES,
    BailianTTS,
    CosyVoiceTTS,
    EdgeTTS,
    OpenAITTS,
    SpeechRequest,
    TTSError,
    TTSProvider,
    VolcanoTTS,
    build_remote_provider,
    extract_bailian_audio_url,
    is_cosyvoice,
    resolve_dashscope_native_base,
    synthesize_many,
    vendor_for_engine,
)
from app.audio.tts.catalog import active_model_for, describe_engines

__all__ = [
    "DASHSCOPE_NATIVE_BASE", "EDGE_BUILTIN_VOICES", "PODCAST_SPEAKERS", "REMOTE_ENGINES",
    "REMOTE_PARALLEL", "REMOTE_TIMEOUT_SECONDS", "VOLCANO_BUILTIN_VOICES", "BailianTTS",
    "CosyVoiceTTS", "EdgeTTS", "OpenAITTS", "SpeechRequest", "TTSError", "TTSProvider",
    "VolcanoTTS", "active_model_for", "build_remote_provider", "describe_engines",
    "extract_bailian_audio_url", "is_cosyvoice", "resolve_dashscope_native_base",
    "synthesize_many", "vendor_for_engine",
]
