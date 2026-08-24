"""语音合成的适配器与注册表。

和同级的 `image/` `video/` 是同一件事的三面 —— 此前它住在 `ai/providers/speech.py` 里,
理由只是"它输出的是音频"。而一个供应商适配器的角色与它输出什么介质无关:百炼的 qwen-tts
和百炼的万相视频,共用一把 Key、同样的 HTTP 形状、同样的错误处理,却曾经分处两棵树。

**引擎目录不在这儿**(见 audio/tts/catalog.py):那份要读本地模型的就绪状态,搬进来会让
`ai` 和 `audio` 互相依赖成环。这里只管"有哪些远程引擎、怎么把它造出来"。
"""

from app.ai.providers.speech.bailian import (
    DASHSCOPE_NATIVE_BASE,
    BailianTTS,
    CosyVoiceTTS,
    extract_bailian_audio_url,
    is_cosyvoice,
    resolve_dashscope_native_base,
)
from app.ai.providers.speech.base import (
    REMOTE_PARALLEL,
    REMOTE_TIMEOUT_SECONDS,
    SpeechRequest,
    TTSError,
    TTSProvider,
    synthesize_many,
)
from app.ai.providers.speech.edge import EDGE_BUILTIN_VOICES, EdgeTTS
from app.ai.providers.speech.openai import OpenAITTS
from app.ai.providers.speech.volcano import PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES, VolcanoTTS

_ENGINE_VENDOR = {CosyVoiceTTS.id: BailianTTS.id}


def vendor_for_engine(engine: str) -> str:
    """这个引擎的凭据挂在哪个 vendor 下。"""
    return _ENGINE_VENDOR.get(engine, engine)


REMOTE_ENGINES = {
    OpenAITTS.id: OpenAITTS,
    BailianTTS.id: BailianTTS,
    CosyVoiceTTS.id: CosyVoiceTTS,
    VolcanoTTS.id: VolcanoTTS,
    EdgeTTS.id: EdgeTTS,
}


def build_remote_provider(engine: str, api_key: str, voice: str = "", model: str = "", base_url: str = ""):
    """Construct a remote engine, or raise a message the user can act on."""
    cls = REMOTE_ENGINES.get(engine)
    if cls is None:
        raise TTSError(f"未知的语音引擎:{engine}")
    if cls is EdgeTTS:
        return cls(voice=voice)  # 免费服务,无密钥可传
    if cls is OpenAITTS:
        return cls(api_key=api_key, model=model or "gpt-4o-mini-tts", base_url=base_url)
    return cls(api_key=api_key, voice=voice, model=model, base_url=base_url)
