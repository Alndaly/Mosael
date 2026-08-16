"""F5-TTS 的语言能力属于**模型**,不属于引擎。

此前代码里写死两个常量指向 `F5TTS_v1_Base`,于是「F5 支持什么语言」被回答成了「引擎支持什么
语言」,而用户日文配音得到的是一段听不懂的声音。真相是:同一个引擎、同一个 venv、同一段代码,
换一份日语微调权重就念得了 —— 运行时一直支持 `F5TTS(ckpt_file=…, vocab_file=…)`,只是那两个
值被钉死了。

所以这里钉住的是:**判据跟着盘上的权重走,而不是写在代码里的一句断言**。
"""
from __future__ import annotations

import pytest

from app.audio import f5_models
from app.audio.tts_language import clone_supports


def test_language_support_comes_from_installed_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    """装了日语模型,「念不念得了日文」的答案就该变 —— 不必改代码、不必重启。"""
    monkeypatch.setattr(f5_models, "installed", lambda model: model.id == "base")
    assert clone_supports("ja") is False

    monkeypatch.setattr(f5_models, "installed", lambda model: True)
    assert clone_supports("ja") is True


def test_no_evidence_means_the_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """中英文(以及拿不到硬证据的文本)走默认模型 —— 它就是为这种情况准备的。"""
    monkeypatch.setattr(f5_models, "installed", lambda model: model.id == "base")
    assert clone_supports("") is True
    assert f5_models.for_language("").id == f5_models.DEFAULT_MODEL_ID


def test_picking_a_model_requires_it_to_be_on_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """目录里**有**日语模型不等于**能用**它:没下载就是没下载。

    这个区分是整件事的关键 —— 「不知道」「没装」「不支持」是三件事,混在一起就会拿中英模型
    去念日文,然后报成功。
    """
    monkeypatch.setattr(f5_models, "installed", lambda model: model.id == "base")
    assert f5_models.for_language("ja") is None
    missing = f5_models.missing_for_language("ja")
    assert missing is not None and missing.id == "ja"

    monkeypatch.setattr(f5_models, "installed", lambda model: True)
    assert f5_models.for_language("ja").id == "ja"
    assert f5_models.missing_for_language("ja") is None


def test_every_model_declares_where_its_files_live() -> None:
    """每个条目都要能自己回答「从哪拉、拉哪两个文件」—— 少一样就是一次跑到一半才失败的下载。"""
    for model in f5_models.F5_MODELS:
        assert model.hf_repo and model.checkpoint and model.vocab, model.id
        assert model.languages, model.id
        assert model.expected_bytes > 0, model.id


def test_model_paths_do_not_collide() -> None:
    """权重共用一个托管目录,靠仓库里自带的目录前缀区分。

    撞车的话后下的那份会覆盖前一份,而两者大小接近、名字不同 —— 症状是"下完了还是念不对"。
    """
    paths = [model.checkpoint for model in f5_models.F5_MODELS]
    assert len(paths) == len(set(paths))


def test_latin_script_languages_cannot_be_detected() -> None:
    """法语、德语、西语、意语、芬兰语和英语共用拉丁字母 —— **没有任何字符能证明是哪一门**。

    所以它们的权重永远自动挑不中,只能由用户明说(weights_for 的 model_id)。装作能认出来的
    代价是给英文文本套上一份法语权重,而那同样是一段念不对的音频。
    """
    from app.audio.tts_language import detect_script

    for text in ("Bonjour tout le monde", "Guten Tag alle zusammen", "Hola a todos", "Hello world"):
        assert detect_script(text) == "", text


def test_scripts_that_do_give_evidence() -> None:
    from app.audio.tts_language import detect_script

    assert detect_script("Привет, как дела") == "ru"
    assert detect_script("مرحبا كيف حالك") == "ar"
    assert detect_script("नमस्ते कैसे हैं आप") == "hi"


def test_an_explicit_model_beats_the_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户明说要哪份权重时,不再看文字 —— 这是拉丁字母那几门语言唯一的用法。"""
    from app.audio import tts_models

    monkeypatch.setattr(f5_models, "installed", lambda model: True)
    picked = tts_models.weights_for("f5-tts", "Bonjour tout le monde", "fr")
    assert picked["checkpoint"].startswith("fr/")

    # 明说的那份没装 → 退回按文字挑(而不是拿一份不存在的权重去合成)。
    monkeypatch.setattr(f5_models, "installed", lambda model: model.id == "base")
    fallback = tts_models.weights_for("f5-tts", "Bonjour tout le monde", "fr")
    assert fallback["checkpoint"].startswith("F5TTS_v1_Base/")


def test_each_model_gets_its_own_directory_except_the_base() -> None:
    """这些社区权重的 vocab **全叫 `vocab.txt`** —— 共用一个目录就会互相覆盖。

    症状是"下完了还是念不对":装了法语再装德语,其中一个从此配着别人的 vocab 念,而两份文件
    大小相近、名字相同,从盘上看不出任何异常。
    """
    local_vocabs = [model.local_vocab for model in f5_models.F5_MODELS]
    assert len(local_vocabs) == len(set(local_vocabs))
    local_ckpts = [model.local_checkpoint for model in f5_models.F5_MODELS]
    assert len(local_ckpts) == len(set(local_ckpts))
    # 基础模型仍落在根目录:已经下好它的机器不该因为这次改动重下 1.35 GB。
    base = f5_models.get("base")
    assert base is not None and base.local_checkpoint == base.checkpoint
