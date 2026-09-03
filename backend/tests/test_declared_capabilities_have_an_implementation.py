"""结构性约束:**供应商声明的每一样能力,都得真有东西去执行它。**

预设表里的 `capability_ids` 直接决定界面上那家能勾哪几档。加一个 id 是改一行数据的事,
而接一个适配器是写一个文件的事 —— 两者代价差得越远,越容易只做前者。那样界面会摆出一档
选了必然失败的能力,而用户要等到填完提示词、点了生成、等完一次排队,才收到一句"没有可用的
供应商"。

这条测试今天就差点用上:百炼确实提供视频与语音,于是很自然会想「把 video/tts 加进去就好」——
但当时 `("alibaba","video")` 根本没有注册,tts 那边也没有引擎类。

各能力由谁执行:
  · image / video → ai.providers 的注册表,按 (vendor, kind) 取
  · tts           → ai.providers.REMOTE_SPEECH_ADAPTERS,按语音引擎 id 取
  · chat          → 统一的 OpenAI 兼容客户端,不需要每家一个适配器
  · podcast       → 专用的 WebSocket 实现,按 vendor 取
"""

from __future__ import annotations

import pytest

from app.ai.providers import has_capability_implementation
from app.domain.provider_presets import provider_definition, provider_definitions

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

@pytest.mark.parametrize(
    ("vendor", "capability"),
    [
        (definition.vendor, capability)
        for definition in provider_definitions()
        for capability in definition.capability_ids
    ],
)
def test_每一档声明的能力都有人执行(vendor: str, capability: str) -> None:
    assert has_capability_implementation(vendor, capability), (
        f"预设 {vendor!r} 声明了 {capability!r},但没有任何东西能执行它 —— "
        f"界面会把这一档摆出来,而用户要等到点了生成才发现。"
        f"要么接上适配器,要么把它从 capability_ids 里去掉。"
    )


def test_百炼四档齐全() -> None:
    """点名钉住这一家:它是"同一把 Key 挂着四种能力"的典型,少写一样用户就得多建一个档案。"""
    alibaba = provider_definition("alibaba")
    assert alibaba is not None
    assert alibaba.capability_ids == ("chat", "image", "video", "tts")
    for capability in ("image", "video", "tts"):
        assert has_capability_implementation("alibaba", capability), f"百炼的 {capability} 没接上"
