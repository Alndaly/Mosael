"""在下东西的时候就说在下东西 —— 别说成"加载"。

用户选了 F5-TTS,界面十几分钟停在「首次加载权重(mps)」。而实测那段时间里:

    worker 进程 CPU 0.1%,内存 0.7 GB      ← 没在算
    ~/.cache/huggingface/.../vocos-mel-24khz/blobs/*.incomplete 在长

它在**下载**声码器(约 55 MB;这台机器上 HuggingFace 是 46 KB/s,所以要十几分钟),
而不是在加载权重。两件事的等待理由完全不同:加载是本地的、只能等;下载慢是网络问题,
用户可以换源、可以先去干别的、可以判断"这不正常"。

**说成"加载"就把一个可判断的处境变成了一个不可判断的处境。** 这是今天反复出现的同一个
形状(20% 不是进度、「已安装」不是能用、「引擎已就绪」不是能合成),只是换了一处地方。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "ai" / "runtime"))
import tts_worker  # noqa: E402


def test_it_says_downloading_when_the_vocoder_is_missing(tmp_path, monkeypatch) -> None:
    said: list[str] = []
    monkeypatch.setattr(tts_worker, "_progress", lambda phase, fraction, message="": said.append(f"{phase}:{message}"))
    monkeypatch.setattr(tts_worker, "_hf_cached", lambda name: False)

    tts_worker.announce_f5_fetch()

    assert any("下载" in line for line in said), said
    assert any("声码器" in line or "vocos" in line for line in said), said


def test_it_does_not_cry_wolf_once_it_is_cached(tmp_path, monkeypatch) -> None:
    """已经缓存过就别再说"要下载" —— 那会让人以为每次都在重下。"""
    said: list[str] = []
    monkeypatch.setattr(tts_worker, "_progress", lambda phase, fraction, message="": said.append(message))
    monkeypatch.setattr(tts_worker, "_hf_cached", lambda name: True)

    tts_worker.announce_f5_fetch()

    assert not any("下载" in line for line in said), said


def test_the_cache_check_looks_for_real_bytes(tmp_path, monkeypatch) -> None:
    """一个只有 refs/ 的空目录**不算**缓存过 —— 这正是下载失败后留下的样子
    (fish 那次:目录在,里面只有一个空的 refs/main)。"""
    root = tmp_path / "hub"
    (root / "models--charactr--vocos-mel-24khz" / "refs").mkdir(parents=True)
    monkeypatch.setattr(tts_worker, "_hf_cache_roots", lambda: [root])

    assert tts_worker._hf_cached("models--charactr--vocos-mel-24khz") is False

    blobs = root / "models--charactr--vocos-mel-24khz" / "blobs"
    blobs.mkdir()
    (blobs / "abc").write_bytes(b"x" * 20_000_000)

    assert tts_worker._hf_cached("models--charactr--vocos-mel-24khz") is True


def test_it_warns_before_f5_pulls_whisper_to_auto_transcribe(monkeypatch) -> None:
    """参考文本留空时,F5 的"自动识别"= 下一个 1.6 GB 的 Whisper。

    现场:用户按我的建议改用 F5(理由正是"它会自己识别"),然后卡在「生成中」——
    实际在下 openai/whisper-large-v3-turbo,这台机器上 46 KB/s ≈ 十小时。

    "自动"这个词让它听起来是免费的。**代价要在付出之前说**,而且要说清怎么绕开
    (填上参考文本就完全跳过这一步)。
    """
    said: list[str] = []
    monkeypatch.setattr(tts_worker, "_progress", lambda phase, fraction, message="": said.append(message))
    monkeypatch.setattr(tts_worker, "_hf_cached", lambda name: name != tts_worker.F5_ASR_CACHE)

    tts_worker.announce_f5_fetch(reference_text="")

    joined = " ".join(said)
    assert "识别" in joined and ("1.6" in joined or "GB" in joined), said
    assert "参考文本" in joined, f"没说清怎么绕开:{said}"


def test_no_whisper_warning_when_the_reference_text_is_given() -> None:
    """填了文本就不会走那条路 —— 别吓唬人。"""
    said: list[str] = []
    tts_worker._progress = lambda phase, fraction, message="": said.append(message)  # type: ignore[assignment]
    tts_worker.announce_f5_fetch(reference_text="今天是个好天气")

    assert not any("识别" in line for line in said), said
