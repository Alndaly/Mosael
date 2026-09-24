"""内置降噪:ffmpeg 的频谱降噪(afftdn),先量噪声再下手。

**永远跑得起来** —— ffmpeg 本来就随应用带着,不装任何东西。所以降噪这个能力在任何一台机器上
都不会"消失",`auto` 挑的也是它(ADR-0017 决定 2)。

**为什么要先量**:afftdn 的 `nf` 是"噪声大概在多少分贝"。写死一个值的话,噪声比它响就当成了
信号、一点都不降;比它轻就把说话声当噪声削掉。实测一段 −31 dB 的白噪声,`nf=-50` 降完还是
−31.7 dB,而同一段在 `nf=-20` 下降到 −61.5。所以每段音频先量一遍:按 50 ms 切片算响度,
取第 10 百分位当噪声底 —— 说话总有停顿,停顿里剩下的就是噪声。

适合稳态噪声:空调、风扇、电流声、底噪。人声鼎沸、背景音乐这类非稳态的它降不掉 ——
那是模型类引擎的活(见 ADR-0017 的 B / C)。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.ai.providers.contracts.denoise import (
    subprocess_failure,
    DENOISE_TIMEOUT_SECONDS,
    LIGHT,
    MEDIUM,
    STRENGTHS,
    STRONG,
    DenoiseError,
    DenoiseRequest,
)
from app.core.child_process import run_logged
from app.core.config import settings

#: 档位 → (噪声底往上抬几 dB 作为 nf, 最多削多少 dB)。
#: 数值来自实测(间断正弦当"说话",叠粉噪):停顿里的噪声分别压低约 6 / 12 / 20 dB
#: (噪声 −53、−65 dB 两档),说话段响度变化不超过 0.1 dB;信噪比只有 10 dB 的录音三档是
#: 6 / 9 / 9 dB(受下面那道线限制);没有停顿的连续音频几乎不动(0.1 dB)。
_PROFILE: dict[str, tuple[float, float]] = {
    LIGHT: (2.0, 12.0),
    MEDIUM: (8.0, 24.0),
    STRONG: (12.0, 40.0),
}
#: nf 至少比信号低这么多。没有停顿的音频(整段音乐)第 10 百分位就是音乐本身,
#: 不设这道线的话,nf 会被抬到信号上。**这道线不能画得太保守**:起初是 15 dB,结果信噪比
#: 只有 10 来 dB 的录音(正是最需要降噪的那种)nf 被压到噪声底以下,三档降得一样少。
_SIGNAL_HEADROOM_DB = 6.0
#: afftdn 接受的 nf 范围。
_NF_MIN, _NF_MAX = -80.0, -20.0
#: 量不出来时(整段数字静音)用的噪声底。
_FALLBACK_FLOOR_DB = -60.0
_HIGHPASS_HZ = 70

_RMS = re.compile(r"RMS_level=(-?\d+(?:\.\d+)?)")


def measure_levels(audio: Path) -> tuple[float, float] | None:
    """(噪声底, 信号电平),单位 dB。按 50 ms 切片算响度,取第 10 / 第 90 百分位。

    整段都是数字静音时返回 None。
    """
    result = run_logged(
        [
            settings.ffmpeg, "-v", "error", "-i", str(audio),
            "-af",
            # 降到 16 kHz 只为量得快 —— 这是在量,不是在出成品。
            "aresample=16000,asetnsamples=n=800:p=0,astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=DENOISE_TIMEOUT_SECONDS,
        what="测量噪声底",
    )
    if result.returncode != 0:
        raise subprocess_failure("providerErr_denoiseMeasureFailed", result.stderr, tool="ffmpeg")
    # 数字静音的切片报的是 -inf,正则不收它 —— 它不是噪声,是没有声音。
    levels = sorted(float(value) for value in _RMS.findall(result.stdout))
    if not levels:
        return None
    return levels[int(len(levels) * 0.1)], levels[int(len(levels) * 0.9)]


def filter_for(strength: str, levels: tuple[float, float] | None) -> str:
    """这一档、这段音频该用的滤镜链。单独拿出来,测试不用真的跑 ffmpeg 就能钉住判据。"""
    lift, reduction = _PROFILE[strength]
    floor, signal = levels if levels else (_FALLBACK_FLOOR_DB, _FALLBACK_FLOOR_DB + 30)
    noise_floor = min(floor + lift, signal - _SIGNAL_HEADROOM_DB)
    noise_floor = max(_NF_MIN, min(_NF_MAX, noise_floor))
    # 高通先把 70 Hz 以下的嗡声(电源、桌面震动)切掉 —— 人声基频在那之上。
    return f"highpass=f={_HIGHPASS_HZ},afftdn=nr={reduction:g}:nf={noise_floor:.1f}"


class FfmpegDenoiseAdapter:
    engine_id = "ffmpeg"
    label_key = "denoiseEngine_ffmpeg"
    description_key = "denoiseDesc_ffmpeg"
    strengths = STRENGTHS
    removes_music = False
    setup_hint_key = ""

    def runtime_ready(self) -> bool:
        # ffmpeg 是应用本体的依赖:没有它素材库都导不进东西,不在这里另做探测。
        return True

    def denoise(self, request: DenoiseRequest, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            chain = filter_for(request.strength, measure_levels(request.audio_path))
            result = run_logged(
                [
                    settings.ffmpeg, "-y", "-v", "error", "-i", str(request.audio_path),
                    "-af", chain, "-c:a", "pcm_s16le", str(out_path),
                ],
                capture_output=True,
                text=True,
                timeout=DENOISE_TIMEOUT_SECONDS,
                what="降噪",
            )
        except subprocess.TimeoutExpired as exc:
            raise DenoiseError("providerErr_denoiseTimeout") from exc
        if result.returncode != 0 or not out_path.is_file():
            raise subprocess_failure("providerErr_denoiseFailed", result.stderr, tool="ffmpeg")
        return out_path
