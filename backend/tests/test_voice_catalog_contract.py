"""每一家念字引擎(和播客)交出来的音色目录都是同一个形状(ADR 0087)。

界面、合成前的语言检查、字幕配音按语言挑音色,读的都是 `VoiceOption` 上那几格。某一家把语言写成 `中文`、
把性别写成 `女`、或者把 `cloned` 当成自己的来源,下游不会报错,只会悄悄地判错 —— 所以在这里一次守住。
接一家新引擎时,这条测试替它把关。
"""

from __future__ import annotations

import re

import pytest

from app.ai.providers import VOICE_SOURCES, VoiceCatalogContext, VoiceOption, podcast_engine, speech_engines

#: BCP 47 的常见形状:主语言 + 可选的地区 / 变体(`zh`、`zh-CN`、`en-US`)。
_BCP47 = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_GENDERS = {"", "female", "male", "neutral"}


def _catalogs() -> list[tuple[str, list[VoiceOption]]]:
    """不带连接、不带模型问一遍:内置清单(百炼给对所有模型都有效的那一组)。"""
    found = [(engine.engine_id, engine.voices(VoiceCatalogContext())) for engine in speech_engines()]
    found.append((podcast_engine().engine_id, list(podcast_engine().speakers)))
    return found


@pytest.mark.parametrize(("engine", "voices"), _catalogs(), ids=lambda value: value if isinstance(value, str) else "")
def test_每一家的音色目录都是同一个形状(engine: str, voices: list[VoiceOption]) -> None:
    assert voices, f"{engine}:没给连接、没给模型时也该有一份内置清单,空下拉读起来像「这个引擎没有音色」"
    assert len({voice.id for voice in voices}) == len(voices), f"{engine}:音色 id 重复"
    for voice in voices:
        assert isinstance(voice, VoiceOption)
        assert voice.id and voice.label, f"{engine}:{voice}"
        #: 克隆音色是工作区的领域数据,由领域层并进清单 —— 任何一家 Adapter 都不该自称给出了它。
        assert voice.source in VOICE_SOURCES and voice.source != "cloned", f"{engine}:{voice.id} 的来源 {voice.source}"
        assert all(_BCP47.match(language) for language in voice.languages), f"{engine}:{voice.id} 的语言 {voice.languages}"
        assert voice.gender in _GENDERS, f"{engine}:{voice.id} 的性别 {voice.gender}"


def test_随模型变的那家按模型给_并记下它属于哪一族() -> None:
    """百炼:换到别的模型族上,同名音色未必念得出来 —— 所以每一项带着 `models`。认不出的模型回空,界面退回手填 id。"""
    from app.ai.providers.adapters.alibaba.dashscope.speech import BailianSpeechAdapter

    flash = BailianSpeechAdapter.voices(VoiceCatalogContext(model="qwen3-tts-flash-2025-11-27"))
    assert flash and {voice.models for voice in flash} == {("qwen3-tts-flash",)}
    assert BailianSpeechAdapter.voices(VoiceCatalogContext(model="qwen3-tts-vd-2026-01-26")) == []
