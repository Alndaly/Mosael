"""没有语速参数的引擎,语速由宿主在合成之后补上(`media.tempo.stretch_in_place`)。

维护者问「Fish Speech S2 Pro 没办法调节语速吗」(2026-10-31)。它的请求结构里确实没有语速(本机检出与上游 main 都核过),
此前的回答是把语速控件藏起来;现在改成「由谁来调」:`native` 随请求交给引擎,`stretch` 按原速念、念完变速。
这里钉三件事:真的变了速(时长对得上)、原速什么都不动、原生吃语速的那一家**不会被再变一次**。
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import pytest

from app.ai.providers.adapters.alibaba.dashscope.speech import BailianSpeechAdapter, CosyVoiceSpeechAdapter
from app.core.config import settings
from app.media.tempo import TempoError, stretch_in_place

needs_ffmpeg = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")


def _tone(path: Path, seconds: float, rate: int = 24_000) -> None:
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x10\x00\xf0\xff" * int(seconds * rate / 2))


def _seconds(path: Path) -> float:
    with wave.open(str(path)) as handle:
        return handle.getnframes() / handle.getframerate()


@needs_ffmpeg
@pytest.mark.parametrize(("speed", "expected"), [(1.5, 2.0), (0.75, 4.0)])
def test_the_audio_really_gets_faster_or_slower(tmp_path: Path, speed: float, expected: float) -> None:
    audio = tmp_path / "speech.wav"
    _tone(audio, 3.0)

    stretch_in_place(audio, speed)

    assert _seconds(audio) == pytest.approx(expected, abs=0.05)
    assert not list(tmp_path.glob(".*stretched*")), "临时文件要换上去,不留在旁边"


def test_original_speed_leaves_the_file_alone(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    _tone(audio, 1.0)
    before = audio.read_bytes()

    stretch_in_place(audio, 1.0)

    assert audio.read_bytes() == before


def test_out_of_range_is_refused_without_touching_the_file(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    _tone(audio, 1.0)

    with pytest.raises(TempoError) as caught:
        stretch_in_place(audio, 3.0)

    assert caught.value.key == "tempoErr_outOfRange"
    assert _seconds(audio) == pytest.approx(1.0, abs=0.01)


def test_bailian_decides_per_model_so_cosyvoice_is_not_stretched_twice() -> None:
    """百炼一个 Adapter 管两族:CosyVoice 收 `rate`(原生),qwen-tts 不收(宿主变速)。

    按类判的话,配了 CosyVoice 模型的那条连接会被 `rate` 和宿主各变一次 —— 1.5 倍变成 2.25 倍。
    """
    assert BailianSpeechAdapter(api_key="k", model="cosyvoice-v2").speed_control == "native"
    assert BailianSpeechAdapter(api_key="k", model="qwen-tts").speed_control == "stretch"
    assert CosyVoiceSpeechAdapter(api_key="k").speed_control == "native"
