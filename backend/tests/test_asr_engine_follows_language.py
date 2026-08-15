"""语言决定用**哪个模型**,不决定用哪个引擎。

FunASR 不是中文引擎:它的 SenseVoice 按官方说明「支持超过 50 种语言,识别效果上优于 Whisper」。
此前目录里只有中文预设(paraformer-zh),于是两件事被混为一谈 ——

  ・命名上,FunASR 看起来就是"中文那个";
  ・逻辑上,非中文素材要么被中文权重转坏(转出来一堆错字、还被标成 language=zh),
    要么被推给别的引擎。

修法不是给 FunASR 降级,而是把"我们装了哪套权重"和"这个引擎能做什么"分开:引擎按可用性选,
语言在**模型**这一层承担。
"""

from __future__ import annotations

import pytest

from app.audio import asr_models, service


@pytest.fixture(autouse=True)
def _both_engines_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asr_models, "resolve_engine_python", lambda engine: f"/fake/{engine}")
    monkeypatch.setattr(service.settings, "asr_provider", "auto")


@pytest.mark.parametrize("language", ["", "zh", "zh-CN", "Chinese", "中文"])
def test_chinese_uses_the_paraformer_preset(language: str) -> None:
    """中文(或没说)用中文预设 —— Paraformer 在中文上确实更强,这也是这个产品的主场景。"""
    assert service.funasr_model_for(language) == service.FUNASR_ZH_MODEL


@pytest.mark.parametrize("language", ["en", "en-US", "ja", "ko", "fr", "auto"])
def test_other_languages_use_funasr_multilingual_model(language: str) -> None:
    """**非中文不该被赶去别的引擎** —— FunASR 自己就有 50+ 语种的模型,换模型即可。"""
    assert service.funasr_model_for(language) == service.FUNASR_MULTILINGUAL_MODEL


@pytest.mark.parametrize("language", ["", "zh", "en", "ja"])
def test_language_never_changes_the_engine(language: str) -> None:
    """引擎只看装没装。曾经这里写过「非中文一律走 WhisperX」—— 那是把"我们只装了中文预设"
    错记成了"FunASR 只能中文",等于把一次打包选择固化成了引擎的属性。"""
    assert service.resolve_asr_runtime(language)[1] == "funasr"


def test_the_multilingual_model_is_in_the_catalog() -> None:
    """能选它,就得能装它 —— 否则第一次用非中文素材时它会在转写中途现下 937MB。"""
    entry = next(e for e in asr_models.CATALOG if e.id == "funasr-sensevoice")
    assert entry.engine == "funasr"
    assert entry.request["funasr_model"] == service.FUNASR_MULTILINGUAL_MODEL


def test_an_explicit_setting_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.settings, "asr_provider", "whisperx")
    assert service.resolve_asr_runtime("zh")[1] == "whisperx"
