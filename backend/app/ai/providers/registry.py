"""内置供应商 Adapter 的唯一装配入口。

能力契约在 ``contracts``，协议 Implementation 在 ``adapters``；这个 Module 只回答两件事：
某个 ``(vendor, kind)`` 应使用哪个生成 Adapter，以及某个语音引擎 id 应构造哪个 Speech Adapter。
重复键在启动时直接失败，不能由后一次导入静默覆盖前一次注册。
"""

from __future__ import annotations

from collections.abc import Iterable

from app.ai.providers.adapters.alibaba.dashscope.image import QwenImageAdapter
from app.ai.providers.adapters.alibaba.dashscope.speech import BailianSpeechAdapter, CosyVoiceSpeechAdapter
from app.ai.providers.adapters.alibaba.dashscope.video import WanVideoAdapter
from app.ai.providers.adapters.bytedance.ark.image import SeedreamAdapter
from app.ai.providers.adapters.bytedance.ark.video import SeedanceAdapter
from app.ai.providers.adapters.bytedance.volcano.speech import VolcanoSpeechAdapter
from app.ai.providers.adapters.comfyui import ComfyUIGenerationAdapter
from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter
from app.ai.providers.adapters.google.veo import VeoAdapter
from app.ai.providers.adapters.kuaishou.kling.video import KlingVideoAdapter
from app.ai.providers.adapters.local.demucs_separation import DemucsSeparationAdapter
from app.ai.providers.adapters.microsoft.edge_speech import EdgeSpeechAdapter
from app.ai.providers.adapters.minimax.video import MiniMaxVideoAdapter
from app.ai.providers.adapters.openai.image import OpenAIImageAdapter
from app.ai.providers.adapters.openai.speech import OpenAISpeechAdapter
from app.ai.providers.contracts.generation import GenerationAdapter
from app.ai.providers.contracts.separation import SeparationAdapter
from app.ai.providers.contracts.speech import SpeechSynthesisError, SpeechAdapter


def _generation_adapters() -> tuple[GenerationAdapter, ...]:
    return (
        QwenImageAdapter(),
        WanVideoAdapter(),
        SeedanceAdapter(),
        SeedreamAdapter(),
        MiniMaxVideoAdapter(),
        VeoAdapter(),
        KlingVideoAdapter(),
        OpenAIImageAdapter("openai"),
        OpenAIImageAdapter("openai-compatible"),
        ComfyUIGenerationAdapter("image"),
        ComfyUIGenerationAdapter("video"),
        EvolinkGenerationAdapter("image"),
        EvolinkGenerationAdapter("video"),
    )


def _index_generation_adapters(
    adapters: Iterable[GenerationAdapter],
) -> dict[tuple[str, str], GenerationAdapter]:
    indexed: dict[tuple[str, str], GenerationAdapter] = {}
    for adapter in adapters:
        key = (adapter.vendor_id, adapter.media_kind)
        if key in indexed:
            raise RuntimeError(f"重复的生成 Adapter:{key[0]}/{key[1]}")
        indexed[key] = adapter
    return indexed


_GENERATION_ADAPTERS = _index_generation_adapters(_generation_adapters())


def get_generation_adapter(vendor_id: str, media_kind: str) -> GenerationAdapter | None:
    """按精确的供应商和能力类型返回生成 Adapter。"""
    return _GENERATION_ADAPTERS.get((vendor_id, media_kind))


# Podcast synthesis has a distinct request/result contract and therefore is not
# disguised as a SpeechAdapter.  It is nevertheless registered here so capability
# availability has one composition-time answer instead of source-code inspection.
_PODCAST_ADAPTER_VENDORS = frozenset({"volcano-podcast"})


def _index_speech_adapters(adapters: Iterable[type[SpeechAdapter]]) -> dict[str, type[SpeechAdapter]]:
    indexed: dict[str, type[SpeechAdapter]] = {}
    for adapter in adapters:
        if adapter.engine_id in indexed:
            raise RuntimeError(f"重复的语音 Adapter:{adapter.engine_id}")
        indexed[adapter.engine_id] = adapter
    return indexed


REMOTE_SPEECH_ADAPTERS = _index_speech_adapters(
    (
        OpenAISpeechAdapter,
        BailianSpeechAdapter,
        CosyVoiceSpeechAdapter,
        VolcanoSpeechAdapter,
        EdgeSpeechAdapter,
    )
)
_SPEECH_ENGINE_CONNECTION_VENDOR = {
    CosyVoiceSpeechAdapter.engine_id: BailianSpeechAdapter.engine_id,
}


def connection_vendor_for_speech_engine(engine: str) -> str:
    """返回语音引擎凭据所属的连接 vendor。"""
    return _SPEECH_ENGINE_CONNECTION_VENDOR.get(engine, engine)


def _index_separation_adapters(adapters: Iterable[SeparationAdapter]) -> dict[str, SeparationAdapter]:
    indexed: dict[str, SeparationAdapter] = {}
    for adapter in adapters:
        if adapter.engine_id in indexed:
            raise RuntimeError(f"重复的音频分离 Adapter:{adapter.engine_id}")
        indexed[adapter.engine_id] = adapter
    return indexed


#: 人声/背景音分离(ADR-0016)。**这是能力可用性的唯一答案** —— 调用方不按引擎名写 if,
#: 加一个引擎就是加一个 Adapter 加一行注册。
SEPARATION_ADAPTERS = _index_separation_adapters((DemucsSeparationAdapter(),))


def get_separation_adapter(engine: str = "") -> SeparationAdapter | None:
    """点名一个引擎;不点名就给**现在跑得起来的**第一个。

    「跑不跑得起来」是问出来的,不是配置出来的:本地引擎要装依赖和拉权重,云引擎要有凭据。
    一个都没有时返回 None —— 调用方据此退回"没有这个能力"的做法,而不是先调一次再看报错
    (那一次可能已经花了钱或者等了十分钟)。
    """
    #: "auto" 和空串是同一个意思 —— 节点下拉里给的是 auto(和转写节点同一个约定)。
    if engine and engine != "auto":
        return SEPARATION_ADAPTERS.get(engine)
    for adapter in SEPARATION_ADAPTERS.values():
        if adapter.runtime_ready():
            return adapter
    return None


def has_capability_implementation(vendor_id: str, capability: str) -> bool:
    """Whether the composed runtime can execute one declared Provider capability."""
    if capability == "chat":
        return True  # Chat uses the generic OpenAI-compatible/sidecar transport.
    if capability in {"image", "video"}:
        return get_generation_adapter(vendor_id, capability) is not None
    if capability == "tts":
        return vendor_id in REMOTE_SPEECH_ADAPTERS
    if capability == "podcast":
        return vendor_id in _PODCAST_ADAPTER_VENDORS
    return False


def build_speech_adapter(
    engine: str,
    api_key: str,
    voice: str = "",
    model: str = "",
    base_url: str = "",
) -> SpeechAdapter:
    """构造远程语音 Adapter；未知引擎返回用户可处理的错误。"""
    adapter = REMOTE_SPEECH_ADAPTERS.get(engine)
    if adapter is None:
        raise SpeechSynthesisError(f"未知的语音引擎:{engine}")
    if adapter is EdgeSpeechAdapter:
        return adapter(voice=voice)
    if adapter is OpenAISpeechAdapter:
        return adapter(api_key=api_key, model=model or "gpt-4o-mini-tts", base_url=base_url)
    return adapter(api_key=api_key, voice=voice, model=model, base_url=base_url)


__all__ = [
    "REMOTE_SPEECH_ADAPTERS",
    "SEPARATION_ADAPTERS",
    "get_separation_adapter",
    "build_speech_adapter",
    "connection_vendor_for_speech_engine",
    "get_generation_adapter",
    "has_capability_implementation",
]
