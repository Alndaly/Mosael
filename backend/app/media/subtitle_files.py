"""SRT / WebVTT 字幕文件:读成 (起, 止, 文本) 的一列,或把一列写成文件。

只认格式本身,不认时间线 —— 落到哪条轨、超出内容怎么办,是 domain/sequences/subtitle_io 的事。

读的时候要扛住的几件事(都是真实文件里常见的):
- **编码**:带 BOM 的 UTF-8 / UTF-16、不带 BOM 的 UTF-8,以及国内字幕站常见的 GBK(GB18030 是它的超集)。
- **换行**:CRLF、CR、LF 混着来。
- **时间码**:SRT 用逗号分毫秒(00:00:01,500),VTT 用点(00:00:01.500),VTT 还允许省掉小时(00:01.500)。
- **标记**:<i>、<b>、<font>、VTT 的 <v 说话人>、<c.类名>、时间戳标签 —— 字幕轨上只存纯文本,全部去掉。
- VTT 的 NOTE / STYLE / REGION 块、cue 标识、时间码后面的 cue 设置。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from app.core.i18n import LocalizedError

#: 字幕文件里一条字幕:时间线秒(起、止)和文本(多行用 \n 连)。
@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


class SubtitleFileError(LocalizedError, ValueError):
    """读不出来。带文案 key(`subfileErr_*`),按读的人的语言翻。"""


_TIMESTAMP = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
_TIMING = re.compile(rf"^\s*{_TIMESTAMP}\s*-->\s*{_TIMESTAMP}")
_TAG = re.compile(r"<[^>]*>")
_ENCODINGS = ("utf-8", "gb18030")


def decode(data: bytes) -> str:
    """字节 → 文本。BOM 说了算;没有 BOM 先试 UTF-8,再试 GB18030;都不对就报错,不猜出一堆乱码。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in _ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SubtitleFileError("subfileErr_encoding")


def _seconds(hours: str | None, minutes: str, seconds: str, fraction: str) -> float:
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(fraction.ljust(3, "0")) / 1000


def _clean(line: str) -> str:
    return html.unescape(_TAG.sub("", line)).strip()


def parse(text: str) -> list[Cue]:
    """SRT 或 VTT 文本 → 按起点排好的字幕。没有一条读得出来就报错。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        head = lines[0].strip()
        if head.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_at = next((i for i, line in enumerate(lines[:2]) if _TIMING.match(line)), None)
        if timing_at is None:
            continue
        match = _TIMING.match(lines[timing_at])
        assert match is not None
        start = _seconds(*match.groups()[:4])
        end = _seconds(*match.groups()[4:])
        body = "\n".join(cleaned for cleaned in (_clean(line) for line in lines[timing_at + 1:]) if cleaned)
        if body and end > start:
            cues.append(Cue(start=start, end=end, text=body))
    if not cues:
        raise SubtitleFileError("subfileErr_noCues")
    return sorted(cues, key=lambda cue: cue.start)


def resolve_overlaps(cues: list[Cue], *, min_seconds: float = 0.2) -> list[Cue]:
    """同一条字幕轨上字幕不叠着放:前一条还没完、后一条已经开始时,前一条截到后一条的起点。

    截完不到 `min_seconds` 的(几乎完全被盖住)就并进后一条:两句话同时上屏,读得出来的只有一句,
    合成两行至少两句都看得见。
    """
    resolved: list[Cue] = []
    for cue in sorted(cues, key=lambda one: one.start):
        if resolved and resolved[-1].end > cue.start:
            previous = resolved[-1]
            if cue.start - previous.start >= min_seconds:
                resolved[-1] = Cue(previous.start, cue.start, previous.text)
            else:
                resolved[-1] = Cue(previous.start, max(previous.end, cue.end), f"{previous.text}\n{cue.text}")
                continue
        resolved.append(cue)
    return resolved


def _stamp(seconds: float, separator: str) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{index}\n{_stamp(cue.start, ',')} --> {_stamp(cue.end, ',')}\n{cue.text}"
        for index, cue in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + "\n"


def to_vtt(cues: list[Cue]) -> str:
    # VTT 的正文里 `-->` 会被当成时间行、`<` `&` 是标记 —— 转义掉,读回来是同一句话。
    blocks = [
        f"{_stamp(cue.start, '.')} --> {_stamp(cue.end, '.')}\n"
        + html.escape(cue.text, quote=False).replace("-->", "--&gt;")
        for cue in cues
    ]
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"
