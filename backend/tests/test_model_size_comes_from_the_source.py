"""模型体积按**下载源上的实际文件**算,不按目录里写死的估算。

此前每个引擎的体积是当初抄下来的一个快照,而它同时当三样东西用:卡片上给用户看的「1.5 GB」、
进度条的分母、以及「装好了没有」的判据。上游改一次文件三样一起失准 —— F5 走 ModelScope
实际是 1,402,819,320(检查点 1,348,435,761 + vocab 13,800 + 声码器 54,369,759)= 1.40 GB,
而写死的是 1.50 GB,于是进度条走到 93% 就完成了。

问不到时退回估算是**对的**(离线也得能用),但必须说出它是估算。
"""
from __future__ import annotations

import pytest

from app.ai.runtime import remote_size, tts_models

#: 真实形状:ModelScope 递归列文件,目录项 Type=tree、Size=0。
MODELSCOPE_FILES = {
    "F5TTS_v1_Base/model_1250000.safetensors": 1_348_435_761,
    "F5TTS_v1_Base/vocab.txt": 13_800,
    # 同仓里的**别的**检查点。整仓当分母的话,进度条永远走不到头。
    "F5TTS_Base/model_1200000.safetensors": 1_348_645_281,
    "README.md": 630,
}
VOCODER_FILES = {"pytorch_model.bin": 54_365_991, "config.yaml": 461, "README.md": 1_830}


def test_only_the_files_this_download_takes_are_counted() -> None:
    """同一个仓库里有四份 1.35 GB 的检查点,而这次只取一份。"""
    picked = remote_size.total_bytes(
        MODELSCOPE_FILES,
        ("F5TTS_v1_Base/model_1250000.safetensors", "F5TTS_v1_Base/vocab.txt"),
    )
    assert picked == 1_348_449_561
    whole = remote_size.total_bytes(MODELSCOPE_FILES)
    assert whole > picked, "整仓当分母的话,进度条走不到头"


def test_unknown_is_none_not_zero() -> None:
    """问不到 ≠ 这些文件是 0 字节。混成一个,进度条的分母就成了 0。"""
    assert remote_size.total_bytes(None) is None
    assert remote_size.total_bytes(None, ("x",)) is None
    assert remote_size.total_bytes({}) == 0, "问到了、确实是空仓,那才是 0"


def test_the_real_total_replaces_the_hardcoded_guess(monkeypatch) -> None:
    engine = tts_models._BY_ID["f5-tts"]
    monkeypatch.setattr(
        remote_size, "cached_files",
        lambda source, repo: MODELSCOPE_FILES if source == "modelscope" else VOCODER_FILES,
    )
    total, estimated = tts_models.measured_total(engine, "modelscope")
    assert estimated is False
    assert total == 1_348_449_561 + 54_368_282
    assert total != engine.expected_bytes, "还在用写死的那个数"


def test_a_missing_answer_falls_back_and_says_so(monkeypatch) -> None:
    """离线时仍要能用 —— 但**不能把估算说成实测**。"""
    engine = tts_models._BY_ID["f5-tts"]
    monkeypatch.setattr(remote_size, "cached_files", lambda source, repo: None)
    total, estimated = tts_models.measured_total(engine, "modelscope")
    assert estimated is True
    assert total == engine.expected_bytes


def test_a_partial_answer_is_not_passed_off_as_measured(monkeypatch) -> None:
    """一半问到、一半没问到时,报那一半的和**比报估算更糟**:它看起来精确,而进度条会提前走满。"""
    engine = tts_models._BY_ID["f5-tts"]
    monkeypatch.setattr(
        remote_size, "cached_files",
        lambda source, repo: MODELSCOPE_FILES if source == "modelscope" else None,
    )
    total, estimated = tts_models.measured_total(engine, "modelscope")
    assert estimated is True
    assert total == engine.expected_bytes


@pytest.mark.parametrize("source", ["hf", "hf-mirror", "modelscope"])
def test_every_source_declares_what_it_downloads(source: str) -> None:
    """每个引擎在每个源上都要说得出"这次取哪些" —— 说不出就没有分母可算。"""
    for engine_id in ("f5-tts", "fish-speech"):
        parts = tts_models.download_parts(engine_id, source)
        assert parts, f"{engine_id} 在 {source} 上没有下载清单"
        for part_source, repo, _patterns in parts:
            assert part_source and repo


def test_the_vocoder_always_comes_from_huggingface() -> None:
    """声码器只在 HF 上(ModelScope 三个命名空间都是 404)。主源选 ModelScope 时它仍走 HF ——
    按主源去 ModelScope 上算它的大小,只会得到"问不到"而让整个总量退回估算。"""
    parts = tts_models.download_parts("f5-tts", "modelscope")
    vocoder = [p for p in parts if "vocos" in p[1]]
    assert vocoder and vocoder[0][0] == "hf"
