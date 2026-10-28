"""清除前后的**事实**:容器里有什么、码流里有什么、我们清掉了哪些具体字节。

对账文本(`report.py`)和门禁(`gates.py`)读的是同一份事实 —— 这样"说要清 X"和"验证 X 没了"
不会各说各话。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.assets.scrub import aac as aac_mod, mp4 as mp4_mod, nal as nal_mod, policy
from app.domain.assets.scrub.mp4 import Mp4Error, Reader, read_at
from app.core.child_process import run_logged
from app.core.config import settings

#: 一次读进来做字节扫的块大小。**不整份读**。
CHUNK = 1 << 20


def scan_needles(path: Path, needles: list[bytes], *, limit: int = 0) -> dict[bytes, int]:
    """流式扫一段字节里出现过哪些特征串 → {特征串: 次数}。

    `limit` > 0 时只扫前 `limit` 字节(用于只关心文件头的场合)。分块读,**不整份进内存**。
    """
    counts = {needle: 0 for needle in needles}
    if not needles:
        return counts
    remaining = limit
    overlap = max(len(needle) for needle in needles) - 1
    tail = b""
    with Path(path).open("rb") as handle:
        while True:
            if limit and remaining <= 0:
                break
            size = CHUNK if not limit else min(CHUNK, remaining)
            chunk = handle.read(size)
            if not chunk:
                break
            remaining -= len(chunk)
            window = tail + chunk
            for needle in needles:
                counts[needle] += window.count(needle)
            tail = window[-overlap:] if overlap else b""
    return counts


def scan_span(path: Path, offset: int, size: int, needles: list[bytes]) -> dict[bytes, int]:
    """扫文件里的一段(比如 moov)。"""
    counts = {needle: 0 for needle in needles}
    if not needles or size <= 0:
        return counts
    with Path(path).open("rb") as handle:
        handle.seek(offset)
        remaining = size
        overlap = max(len(needle) for needle in needles) - 1
        tail = b""
        while remaining > 0:
            chunk = handle.read(min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            window = tail + chunk
            for needle in needles:
                counts[needle] += window.count(needle)
            tail = window[-overlap:] if overlap else b""
    return counts


@dataclass
class TrackFact:
    index: int
    handler: str
    codec: str
    samples: int
    timescale: int
    duration: int


@dataclass
class ContainerFacts:
    """容器层看到的东西。**mp4 一族才有** —— 别的容器这里只有 `container`。"""

    container: str = ""
    major_brand: str = ""
    is_mp4: bool = False
    fragmented: bool = False
    encrypted: bool = False
    tracks: list[TrackFact] = field(default_factory=list)
    #: moov 里出现的、我们认识的元数据盒子(名字)。
    metadata_boxes: list[str] = field(default_factory=list)
    #: `uuid` 盒子 → (十六进制 UUID, 字节数, 是不是 AI 生成标记)。
    uuid_boxes: list[tuple[str, int, bool]] = field(default_factory=list)
    #: stsd 里非空的 `compressorname` 文本。
    compressornames: list[str] = field(default_factory=list)
    #: ffprobe 读出来的标签(只用来**发现**,不用来验收)。
    tags: dict[str, str] = field(default_factory=dict)
    #: 有没有封面图(`covr` 盒子,或一条 marked attached_pic 的流)。
    cover: bool = False

    @property
    def video_tracks(self) -> list[TrackFact]:
        return [track for track in self.tracks if track.handler == "vide"]

    @property
    def audio_tracks(self) -> list[TrackFact]:
        return [track for track in self.tracks if track.handler == "soun"]

    @property
    def data_tracks(self) -> list[TrackFact]:
        return [track for track in self.tracks if track.handler not in ("vide", "soun")]


@dataclass
class BitstreamFacts:
    """码流层看到的东西。**`ffprobe` 一个都看不见。**"""

    codec: str = ""
    #: SEI 载荷类型 → 次数(整段视频扫完的合计)。
    sei_types: dict[int, int] = field(default_factory=dict)
    #: 保留的 SEI:类型 → 次数(报告里点名说"保留了什么、为什么")。
    sei_kept: dict[int, int] = field(default_factory=dict)
    #: AI 生成标记的 SEI 段数。
    sei_provenance: int = 0
    #: `user_data_unregistered` 里认出来的 UUID(十六进制)。
    sei_uuids: list[str] = field(default_factory=list)
    aac: aac_mod.AacFinding = field(default_factory=aac_mod.AacFinding)
    #: 这份文件里**打印得出来的**隐私串(SEI 文本、compressorname、标签值)。门禁拿它去
    #: 输出里找 —— 在输出里再出现一次,就说明没清干净。
    private_values: list[str] = field(default_factory=list)


@dataclass
class MediaFacts:
    path: Path
    size: int
    container: ContainerFacts = field(default_factory=ContainerFacts)
    bitstream: BitstreamFacts = field(default_factory=BitstreamFacts)
    #: 没做的那几层,以及为什么。
    unsupported: list[str] = field(default_factory=list)
    #: 这次清除里最大的单次读取(证"没有整份读进内存")。
    max_read: int = 0

    @property
    def provenance_present(self) -> bool:
        return self.bitstream.sei_provenance > 0 or any(box[2] for box in self.container.uuid_boxes)


def _printable(raw: bytes) -> str:
    """把一段字节里能读的字符取出来,给报告和门禁用(不可打印的丢掉)。"""
    text = "".join(chr(byte) if 0x20 <= byte < 0x7F else " " for byte in raw)
    return re.sub(r"\s+", " ", text).strip()


def probe_tags(path: Path) -> dict[str, str]:
    """用 `ffprobe` 读一遍标签。**只用它来发现** —— 验收一律靠扫字节(见 `gates.py`)。"""
    import json
    import logging


    try:
        proc = run_logged(
            [settings.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=120, what="探素材", level=logging.DEBUG,
        )
        data = json.loads(proc.stdout or "{}")
    except Exception:
        return {}
    tags: dict[str, str] = {}
    for key, value in (data.get("format") or {}).get("tags", {}).items():
        tags[str(key)] = str(value)
    for stream in data.get("streams") or []:
        for key, value in (stream.get("tags") or {}).items():
            tags.setdefault(f"{stream.get('codec_type')}:{key}", str(value))
    return tags


def read_container(path: Path, *, tags: dict[str, str] | None = None) -> ContainerFacts:
    """容器层的事实。不是 mp4 一族就只报一个容器名(码流层那半照做)。"""
    facts = ContainerFacts(tags=dict(tags or {}))
    facts.container = path.suffix.lstrip(".").lower() or "unknown"
    try:
        media = mp4_mod.open_mp4(path)
    except (Mp4Error, OSError):
        return facts
    facts.is_mp4 = True
    facts.major_brand = media.major_brand
    facts.fragmented = media.fragmented
    facts.encrypted = media.encrypted
    facts.container = "mp4" if media.major_brand in ("isom", "iso2", "mp41", "mp42", "avc1", "dash", "cmfc") else "mov"
    for track in media.tracks:
        facts.tracks.append(TrackFact(
            index=track.index, handler=track.handler, codec=track.codec,
            samples=track.sample_count, timescale=track.timescale, duration=track.total_duration,
        ))
    seen: set[str] = set()
    for box in media.all_boxes():
        if box.typ in mp4_mod.KNOWN_METADATA_BOXES or box.typ in mp4_mod.GPS_BOXES:
            if box.typ not in seen:
                seen.add(box.typ)
                facts.metadata_boxes.append(box.typ)
        if box.typ == "uuid":
            payload = _box_payload(path, box.start + box.head, box.size - box.head, 4096)
            is_prov = nal_mod.is_provenance_box(box.usertype, payload)
            facts.uuid_boxes.append((box.usertype.hex(), box.size, is_prov))
    if "covr" in facts.metadata_boxes or any("attached_pic" in key for key in facts.tags):
        facts.cover = True
    for track in media.tracks:
        if track.compressorname_at:
            raw = read_at(path, track.compressorname_at, 32)
            length = raw[0]
            name = _printable(raw[1:1 + min(length, 31)]) if length else ""
            if name:
                facts.compressornames.append(name)
    return facts


def _box_payload(path: Path, offset: int, size: int, limit: int) -> bytes:
    if size <= 0:
        return b""
    return read_at(path, offset, min(size, limit))


def _scan_video(reader: Reader, track, codec: str, bits: BitstreamFacts) -> None:
    """逐样本扫 SEI:类型、UUID、要不要清。**只读。**"""
    length_size = track.nal_length_size
    if not length_size:
        return
    for _, offset, size in track.iter_samples():
        sample = reader.read(offset, size)
        try:
            nals = nal_mod.split_sample(sample, codec, length_size)
        except nal_mod.NalError:
            bits.unsupported.append("视频样本的 NAL 长度对不上,SEI 层跳过")
            return
        for nal in nals:
            if nal.type not in (6, 39, 40):
                continue
            body = nal.raw(sample)
            for payload_type, payload in nal_mod.sei_payloads(body, nal.type, codec):
                bits.sei_types[payload_type] = bits.sei_types.get(payload_type, 0) + 1
                if payload_type != nal_mod.SEI_USER_DATA_UNREGISTERED:
                    bits.sei_kept[payload_type] = bits.sei_kept.get(payload_type, 0) + 1
                    continue
                uuid = payload[:16].hex()
                if uuid not in bits.sei_uuids:
                    bits.sei_uuids.append(uuid)
                if nal_mod.is_provenance_sei(payload_type, payload):
                    bits.sei_provenance += 1
                text = _printable(payload[16:])
                if text:
                    _remember(bits.private_values, text)


def _remember(values: list[str], text: str) -> None:
    """记下要清的串,给门禁拿去输出里找。太短的(比如 "1"、"a")不当签名。"""
    for piece in (text,):
        if len(piece) >= 6 and piece not in values:
            values.append(piece)


def _scan_audio(reader: Reader, track, bits: BitstreamFacts) -> None:
    findings: list[aac_mod.AacFinding] = []
    for _, offset, size in track.iter_samples():
        findings.append(aac_mod.scan(reader.read(offset, size)))
    bits.aac = aac_mod.total(findings)


def inspect(path: Path) -> MediaFacts:
    """把一份文件看一遍:**只读**,只报事实,不判断"该不该清"。"""
    facts = MediaFacts(path=path, size=path.stat().st_size)
    facts.container = read_container(path, tags=probe_tags(path))
    media = None
    if facts.container.is_mp4:
        try:
            media = mp4_mod.open_mp4(path)
        except (Mp4Error, OSError):
            media = None
    if media is None:
        facts.unsupported.append("不是 MP4 / QuickTime 一族:容器层与码流层的字节级改写都没做")
        return facts
    video = [track for track in media.tracks if track.handler == "vide"]
    audio = [track for track in media.tracks if track.handler == "soun"]
    fourcc = video[0].codec if video else ""
    codec = nal_mod.NAL_CODECS.get(fourcc, fourcc)
    facts.bitstream.codec = codec
    if not video:
        facts.unsupported.append(policy.REFUSE["no_video"])
        return facts
    if fourcc in nal_mod.NAL_CODECS:
        with Reader(path) as reader:
            _scan_video(reader, video[0], codec, facts.bitstream)
    else:
        facts.unsupported.append(f"编码 {fourcc or '未知'} 不支持按字节重写 NAL:SEI 层没做")
    with Reader(path) as reader:
        for track in audio:
            if track.codec == "mp4a":
                _scan_audio(reader, track, facts.bitstream)
            elif track.codec in mp4_mod.AUDIO_SAMPLE_ENTRIES:
                facts.unsupported.append(f"音轨编码 {track.codec} 不是 AAC:帧内元素层没做")
    for name in facts.container.compressornames:
        _remember(facts.bitstream.private_values, name)
    for key, value in facts.container.tags.items():
        if _is_private_key(key) and value.strip().lower() not in _GENERIC_TAG_VALUES:
            _remember(facts.bitstream.private_values, value)
    return facts


#: 这些值不是隐私,而且换哪个 muxer 都会写一遍(ffmpeg 默认的 `hdlr` 名字、语言 und)。
#: 把它们记成"要清的串"会让门禁永远红 —— 那是自欺,不是严格。
_GENERIC_TAG_VALUES = frozenset({
    "videohandler", "soundhandler", "core media video", "core media audio", "und", "unknown",
    "lavf", "libavformat",
})


def _is_private_key(key: str) -> bool:
    low = key.lower()
    for names in policy.DEFAULT_STRIP_KEYS.values():
        for name in names:
            if name.lower() in low:
                return True
    return False


__all__ = [
    "BitstreamFacts", "CHUNK", "ContainerFacts", "MediaFacts", "TrackFact",
    "inspect", "probe_tags", "read_container", "scan_needles", "scan_span",
]
