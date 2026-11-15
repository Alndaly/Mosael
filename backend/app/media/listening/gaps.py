"""连贯性:中间有没有断、开头结尾空多久、结尾怎么收、有没有爆音。

被维护者否掉的那版 BGM 就是这几样:4.4–5.8 秒几乎全空、13–16 秒三下孤立的满频带脉冲 —— 听起来断断续续、
「啪」的一下。都按**相对这段声音本身**的电平判:安静的钢琴曲和响的电子乐用同一个绝对门限,前者会被说成到处都断。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.media.listening.decode import Pcm

#: 电平帧 20 ms。断档:连续低于门限至少 0.3 秒。短断:0.08–0.3 秒 —— 一段音乐里反复出现就是「一卡一卡」
#: (那版 BGM 13–16 秒:响 0.4 秒、断 0.15 秒,来回六次);人声里它是正常的换气和停顿,由 `findings` 按内容区分。
LEVEL_FRAME = 0.02
DROPOUT_MIN = 0.3
SHORT_GAP_MIN = 0.08
#: 比这段声音主体的典型电平低这么多算「没声」;再轻也不高于 −50 dBFS 的绝对下限。
SILENCE_BELOW_BODY = 35.0
SILENCE_FLOOR = -50.0
#: 结尾最后 0.25 秒还在主体电平以下这么多之内,就是被切断的,不是收住的。
HARD_CUT_WITHIN = 12.0
#: 爆音:2 ms 一帧的差分能量(高频)比前后 150 ms 的平均高出这么多,且自身不算轻(差分域里的 dB)。
#: 两段真实 BGM 里鼓点、起音最突出的也只高出 22.5 dB。
CLICK_FRAME = 0.002
CLICK_CONTEXT = 0.15
CLICK_ABOVE = 25.0
CLICK_FLOOR = -45.0
CLICK_EDGE_FRAMES = 3
CLICK_EDGE_DROP = 15.0


@dataclass(frozen=True)
class Gaps:
    head_silence: float
    tail_silence: float
    #: 中途断掉的段落 [起, 止](秒)。
    dropouts: list[list[float]]
    #: 中途短暂的断(秒,起点)。
    short_gaps: list[float]
    #: "fade"(收住)/ "hard_cut"(切断)/ "silence"(本来就以静音结尾)。
    ending: str
    #: 孤立的爆音出现的时刻(秒)。
    clicks: list[float]


def gaps(pcm: Pcm) -> Gaps:
    frame = int(pcm.rate * LEVEL_FRAME)
    mono = pcm.mono[: len(pcm.mono) // frame * frame]
    level = 10 * np.log10(np.maximum((mono.reshape(-1, frame).astype(np.float64) ** 2).mean(axis=1), 1e-18))
    audible = level[level > -70]
    body = float(np.median(audible)) if len(audible) else -70.0
    silent = level < max(SILENCE_FLOOR, body - SILENCE_BELOW_BODY) if len(audible) else np.ones_like(level, bool)
    runs = _runs(silent)
    head = runs[0][1] if runs and runs[0][0] == 0 else 0
    tail = len(silent) - runs[-1][0] if runs and runs[-1][1] == len(silent) else 0
    dropouts = [
        [round(start * LEVEL_FRAME, 2), round(end * LEVEL_FRAME, 2)]
        for start, end in runs
        if start > 0 and end < len(silent) and (end - start) * LEVEL_FRAME >= DROPOUT_MIN
    ]
    short_gaps = [
        round(start * LEVEL_FRAME, 2)
        for start, end in runs
        if start > 0 and end < len(silent) and SHORT_GAP_MIN <= (end - start) * LEVEL_FRAME < DROPOUT_MIN
    ]
    return Gaps(
        head_silence=round(head * LEVEL_FRAME, 2),
        tail_silence=round(tail * LEVEL_FRAME, 2),
        dropouts=dropouts,
        short_gaps=short_gaps,
        ending=_ending(level, tail, body),
        clicks=_clicks(pcm),
    )


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist(), strict=True))


def _ending(level: np.ndarray, tail_frames: int, body: float) -> str:
    if tail_frames * LEVEL_FRAME >= 0.2:
        return "silence"
    last = level[-int(0.25 / LEVEL_FRAME):]
    energy = 10 * np.log10(max(float(np.mean(10 ** (last / 10))), 1e-18))
    return "hard_cut" if energy > body - HARD_CUT_WITHIN else "fade"


def _clicks(pcm: Pcm) -> list[float]:
    """一阶差分只留下高频;一记爆音在所有频段同时出现,差分后比周围突出得多,而鼓点、人声的起音不会。"""
    frame = int(pcm.rate * CLICK_FRAME)
    diff = np.diff(pcm.mono.astype(np.float64))
    diff = diff[: len(diff) // frame * frame]
    if not len(diff):
        return []
    energy = (diff.reshape(-1, frame) ** 2).mean(axis=1)
    context = int(CLICK_CONTEXT / CLICK_FRAME)
    near = 5  # 前后 10 ms 不算进参照:一记爆音本身有几毫秒宽。
    total = np.convolve(energy, np.ones(2 * context + 1), mode="same")
    centre = np.convolve(energy, np.ones(2 * near + 1), mode="same")
    reference = (total - centre) / (2 * (context - near))
    loud = 10 * np.log10(np.maximum(energy, 1e-18))
    above = loud - 10 * np.log10(np.maximum(reference, 1e-18))
    #: 一记爆音只有几毫秒:前后 6 ms 都已经落回去 15 dB 以下。鼓点、辅音的起音会拖十几毫秒,不算。
    edge = CLICK_EDGE_FRAMES
    before = np.concatenate((np.full(edge, -180.0), loud[:-edge]))
    after = np.concatenate((loud[edge:], np.full(edge, -180.0)))
    brief = (before < loud - CLICK_EDGE_DROP) & (after < loud - CLICK_EDGE_DROP)
    hits = np.flatnonzero((above > CLICK_ABOVE) & (loud > CLICK_FLOOR) & brief)
    clicks: list[float] = []
    for index in hits:
        at = round(index * CLICK_FRAME, 2)
        if not clicks or at - clicks[-1] > 0.05:
            clicks.append(at)
    return clicks
