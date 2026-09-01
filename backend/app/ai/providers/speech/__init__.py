"""语音合成的**门面**:契约(base.py)+ 注册表,实现在各家供应商目录里。

Adapter 按供应商组织(见上一级 __init__.py 的规矩):百炼的 qwen-tts 住在
`adapters/alibaba/speech.py`,和百炼的万相视频同一棵树 —— 它们共用一把 Key、同样的 HTTP 形状。
这个包只剩两个角色:契约长什么样(base.py)、有哪些远程引擎怎么造(这里)。
vendor 实现 import 契约,注册表 import vendor 实现 —— 单向,不成环。

**引擎目录不在这儿**(见 audio/tts/catalog.py):那份要读本地模型的就绪状态,搬进来会让
`ai` 和 `audio` 互相依赖成环。这里只管"有哪些远程引擎、怎么把它造出来"。
"""

from app.ai.providers.adapters.alibaba.speech import (
    DASHSCOPE_NATIVE_BASE,
    BailianTTS,
    CosyVoiceTTS,
    extract_bailian_audio_url,
    is_cosyvoice,
    resolve_dashscope_native_base,
)
from app.ai.providers.contracts.speech import (
    REMOTE_PARALLEL,
    REMOTE_TIMEOUT_SECONDS,
    SpeechRequest,
    TTSError,
    TTSProvider,
    synthesize_many,
)
from app.ai.providers.adapters.edge import EDGE_BUILTIN_VOICES, EdgeTTS
from app.ai.providers.adapters.openai.speech import OpenAITTS
from app.ai.providers.adapters.volcano import PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES, VolcanoTTS

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
