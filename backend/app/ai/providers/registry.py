"""内置供应商 Adapter 的唯一装配入口。

能力契约在 ``contracts``，协议 Implementation 在 ``adapters``；这个 Module 只回答两件事：
某个 ``(vendor, kind)`` 应使用哪个生成 Adapter，以及某个语音引擎 id 应构造哪个 TTS Adapter。
重复键在启动时直接失败，不能由后一次导入静默覆盖前一次注册。
"""

from __future__ import annotations

from collections.abc import Iterable

from app.ai.providers.adapters.alibaba.image import QwenImageProvider
from app.ai.providers.adapters.alibaba.speech import BailianTTS, CosyVoiceTTS
from app.ai.providers.adapters.alibaba.video import WanVideoProvider
from app.ai.providers.adapters.bytedance.image import SeedreamProvider
from app.ai.providers.adapters.bytedance.video import SeedanceProvider
from app.ai.providers.adapters.comfyui import ComfyUIProvider
from app.ai.providers.adapters.edge import EdgeTTS
from app.ai.providers.adapters.evolink import EvolinkProvider
from app.ai.providers.adapters.google import VeoProvider
from app.ai.providers.adapters.kuaishou.kling import KlingProvider
from app.ai.providers.adapters.minimax import MiniMaxVideoProvider
from app.ai.providers.adapters.openai.image import OpenAIImageProvider
from app.ai.providers.adapters.openai.speech import OpenAITTS
from app.ai.providers.adapters.volcano import VolcanoTTS
from app.ai.providers.contracts.generation import GenerationProvider
from app.ai.providers.contracts.speech import TTSError, TTSProvider


def _generation_adapters() -> tuple[GenerationProvider, ...]:
    return (
        QwenImageProvider(),
        WanVideoProvider(),
        SeedanceProvider(),
        SeedreamProvider(),
        MiniMaxVideoProvider(),
        VeoProvider(),
        KlingProvider(),
        OpenAIImageProvider("openai"),
        OpenAIImageProvider("openai-compatible"),
        ComfyUIProvider("image"),
        ComfyUIProvider("video"),
        EvolinkProvider("image"),
        EvolinkProvider("video"),
    )


def _index_generation_adapters(
    adapters: Iterable[GenerationProvider],
) -> dict[tuple[str, str], GenerationProvider]:
    indexed: dict[tuple[str, str], GenerationProvider] = {}
    for adapter in adapters:
        key = (adapter.name, adapter.kind)
        if key in indexed:
            raise RuntimeError(f"重复的生成 Adapter:{key[0]}/{key[1]}")
        indexed[key] = adapter
    return indexed


_GENERATION_ADAPTERS = _index_generation_adapters(_generation_adapters())


def get_provider(name: str, kind: str) -> GenerationProvider | None:
    """按精确的供应商和能力类型返回生成 Adapter。"""
    return _GENERATION_ADAPTERS.get((name, kind))


def _index_speech_adapters(adapters: Iterable[type[TTSProvider]]) -> dict[str, type[TTSProvider]]:
    indexed: dict[str, type[TTSProvider]] = {}
    for adapter in adapters:
        if adapter.id in indexed:
            raise RuntimeError(f"重复的语音 Adapter:{adapter.id}")
        indexed[adapter.id] = adapter
    return indexed


REMOTE_ENGINES = _index_speech_adapters((OpenAITTS, BailianTTS, CosyVoiceTTS, VolcanoTTS, EdgeTTS))
_ENGINE_VENDOR = {CosyVoiceTTS.id: BailianTTS.id}


def vendor_for_engine(engine: str) -> str:
    """返回语音引擎凭据所属的连接 vendor。"""
    return _ENGINE_VENDOR.get(engine, engine)


def build_remote_provider(
    engine: str,
    api_key: str,
    voice: str = "",
    model: str = "",
    base_url: str = "",
) -> TTSProvider:
    """构造远程语音 Adapter；未知引擎返回用户可处理的错误。"""
    adapter = REMOTE_ENGINES.get(engine)
    if adapter is None:
        raise TTSError(f"未知的语音引擎:{engine}")
    if adapter is EdgeTTS:
        return adapter(voice=voice)
    if adapter is OpenAITTS:
        return adapter(api_key=api_key, model=model or "gpt-4o-mini-tts", base_url=base_url)
    return adapter(api_key=api_key, voice=voice, model=model, base_url=base_url)


__all__ = ["REMOTE_ENGINES", "build_remote_provider", "get_provider", "vendor_for_engine"]
