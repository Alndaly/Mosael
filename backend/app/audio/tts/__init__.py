"""语音引擎:一家一个文件,和 `ai/providers/` 对齐。

这一层此前是 `audio/tts/` 一个 670 行的模块 —— 契约、六家适配器、注册表、
三张音色表全在里面。而隔壁图像/视频的适配器是一家一个文件。同一类东西两种摆法,没有理由
支撑它;真正的代价是加一家供应商时得在一个大袋子里找位置,而不是新开一个文件。

对外的名字全部从这里出,所以拆分对调用方是透明的 —— 这不是"多路兼容",是**一个包的门面**:
调用方本来就该问「语音引擎」这个概念要东西,而不是问某个具体文件。
"""

from app.audio.tts.base import (
    REMOTE_PARALLEL,
    REMOTE_TIMEOUT_SECONDS,
    SpeechRequest,
    TTSError,
    TTSProvider,
    synthesize_many,
)
from app.audio.tts.bailian import (
    DASHSCOPE_NATIVE_BASE,
    BailianTTS,
    CosyVoiceTTS,
    extract_bailian_audio_url,
    is_cosyvoice,
    resolve_dashscope_native_base,
)
from app.audio.tts.edge import EDGE_BUILTIN_VOICES, EdgeTTS
from app.audio.tts.openai import OpenAITTS
from app.audio.tts.registry import (
    REMOTE_ENGINES,
    active_model_for,
    build_remote_provider,
    describe_engines,
    vendor_for_engine,
)
from app.audio.tts.volcano import PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES, VolcanoTTS

__all__ = [
    "DASHSCOPE_NATIVE_BASE",
    "EDGE_BUILTIN_VOICES",
    "PODCAST_SPEAKERS",
    "REMOTE_ENGINES",
    "REMOTE_PARALLEL",
    "REMOTE_TIMEOUT_SECONDS",
    "VOLCANO_BUILTIN_VOICES",
    "BailianTTS",
    "CosyVoiceTTS",
    "EdgeTTS",
    "OpenAITTS",
    "SpeechRequest",
    "TTSError",
    "TTSProvider",
    "VolcanoTTS",
    "active_model_for",
    "build_remote_provider",
    "describe_engines",
    "extract_bailian_audio_url",
    "is_cosyvoice",
    "resolve_dashscope_native_base",
    "synthesize_many",
    "vendor_for_engine",
]
