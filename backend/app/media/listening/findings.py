"""从量到的数得出问题清单。阈值都写在这里,同一段声音永远得出同一份清单。

`expect` 是调用方说的「这是什么声音」—— 同一个数在不同内容里意思不一样:音乐里反复的短断是「一卡一卡」,
念白里是换气;音乐中间断 0.5 秒是坏了,念白里是一个停顿。不说(`any`)时按中等严重度报,文案里写明两种读法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.core.i18n import tr
from app.media.listening.gaps import Gaps
from app.media.listening.levels import Levels
from app.media.loudness import Loudness
from app.media.listening.timbre import Timbre

Expect = Literal["music", "speech", "any"]
Severity = Literal["high", "medium", "low"]

#: 短视频平台的响度惯例约 −14 LUFS;低于 −23 放在手机上要把音量开到很大,高于 −9 几乎一定被压限过狠。
TOO_QUIET = -23.0
TOO_LOUD = -9.0
#: 真峰值高过它,平台转码后会破音(平台建议 ≤ −1 dBTP)。
TRUE_PEAK_HOT = -1.0
#: 音乐里短断达到这个密度(每分钟)、且至少这么多次,算一卡一卡。
CHOPPY_PER_MINUTE = 6.0
CHOPPY_AT_LEAST = 3
#: 念白里停顿超过这么久才算断。
SPEECH_PAUSE_MAX = 1.5
HEAD_SILENCE_MAX = 0.5
DC_OFFSET_MAX = 0.02
PHASE_INVERTED_BELOW = -0.2
NOISE_LIKE_ABOVE = 0.3


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: Severity
    message: str
    #: 出在哪些时刻(秒);整段性的问题为空。
    at: list[float] = field(default_factory=list)


def findings(
    loudness: Loudness | None, levels: Levels, gaps: Gaps, timbre: Timbre, *, seconds: float, expect: Expect
) -> list[Finding]:
    out: list[Finding] = []

    def add(kind: str, severity: Severity, at: list[float] | None = None, **params: object) -> None:
        out.append(Finding(kind=kind, severity=severity, message=tr(f"listenFinding_{kind}", **params), at=at or []))

    if loudness is None or loudness.integrated is None:
        add("silent", "high")
        return out
    if levels.clipped_at:
        add("clipping", "high", levels.clipped_at[:10], count=len(levels.clipped_at))
    if loudness.true_peak is not None and loudness.true_peak > TRUE_PEAK_HOT:
        add("truePeakHot", "high" if loudness.true_peak > 0 else "medium", value=loudness.true_peak)
    if loudness.integrated < TOO_QUIET:
        add("tooQuiet", "low", value=loudness.integrated)
    elif loudness.integrated > TOO_LOUD:
        add("tooLoud", "medium", value=loudness.integrated)
    if gaps.clicks:
        add("clicks", "high", gaps.clicks[:10], count=len(gaps.clicks))

    pauses = gaps.dropouts if expect != "speech" else [one for one in gaps.dropouts if one[1] - one[0] > SPEECH_PAUSE_MAX]
    if pauses:
        add("dropouts", "high" if expect == "music" else "medium", [start for start, _ in pauses[:10]],
            count=len(pauses), longest=round(max(end - start for start, end in pauses), 2))
    if expect != "speech" and len(gaps.short_gaps) >= CHOPPY_AT_LEAST and (
        len(gaps.short_gaps) / max(seconds, 1.0) * 60 >= CHOPPY_PER_MINUTE
    ):
        add("choppy" if expect == "music" else "choppyAny", "high" if expect == "music" else "medium",
            gaps.short_gaps[:10], count=len(gaps.short_gaps))
    if gaps.ending == "hard_cut":
        add("hardCut", "medium", [round(seconds, 2)])
    if gaps.head_silence > HEAD_SILENCE_MAX:
        add("headSilence", "low", [0.0], value=gaps.head_silence)
    if levels.dc_offset > DC_OFFSET_MAX:
        add("dcOffset", "low", value=levels.dc_offset)
    if levels.channel_correlation is not None and levels.channel_correlation < PHASE_INVERTED_BELOW:
        add("phaseInverted", "medium", value=levels.channel_correlation)
    if timbre.noisiness > NOISE_LIKE_ABOVE:
        add("noiseLike", "medium", value=timbre.noisiness)
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda finding: order[finding.severity])
