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
