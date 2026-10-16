"""MP4 / QuickTime 的盒子(atom)与样本表:**只读结构,只写同长度的字节**。

为什么要自己写这一层。清除元数据这件事的价值在**画面和声音逐字节不动** —— 收尾的验收
(见 `gates.py`)比的是"每个样本的载荷和输入一模一样,只差我们点名清掉的那几段"。任何
"重写容器"的库都会顺手重排样本表、改 chunk 偏移、重算 moov,于是几乎每个字节都可能变,
那条验收就没法立了。

所以这里只做两件事:

1. **读**:把 moov 展开成盒子树,从 `stsz` / `stsc` / `stco` / `co64` 算出每个样本在文件里
   的绝对偏移与长度(这是"逐字节比对"和"原地改样本"都要的东西)。
2. **原地改**:只在**长度不变**的范围内改写字节 —— SEI NAL 换成填充 NAL、AAC 的 DSE 载荷
   清零、`compressorname` 清零、把不带 AI 标记的 `uuid` 盒子摘掉。样本长度一变,chunk 偏移
   就要全体重算,那不是这一层愿意承担的风险;摘 `uuid` 盒子也只在**文件尾部**追加或原地
   清零,不动任何已有偏移。

moov 会被整份读进内存(长片也就几百 KB 到几 MB);mdat 一律按样本 seek 读写,**绝不整份读**。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

#: 一个 moov 超过这个大小就不解析了 —— 说明这份文件不是我们以为的形状。
MAX_MOOV_BYTES = 64 * 1024 * 1024
#: 单个样本超过这个大小就拒绝原地改写(样本本身要在内存里过一遍)。
MAX_SAMPLE_BYTES = 32 * 1024 * 1024


class Mp4Error(ValueError):
    """这份文件不是我们认得的、能原地改的 MP4/QuickTime。"""


def _header(buf: bytes, pos: int, limit: int) -> tuple[int, str, int]:
    """读一个盒子头 → (总长度, 类型, 头长度)。`size == 0` 表示"一直到末尾"。"""
    if pos + 8 > limit:
        raise Mp4Error("truncated box header")
    size = struct.unpack_from(">I", buf, pos)[0]
    typ = buf[pos + 4:pos + 8].decode("latin-1")
    head = 8
    if size == 1:
        if pos + 16 > limit:
            raise Mp4Error("truncated large box header")
        size = struct.unpack_from(">Q", buf, pos + 8)[0]
        head = 16
    elif size == 0:
        size = limit - pos
    if size < head or pos + size > limit:
        raise Mp4Error(f"bad box {typ!r} at {pos} (size {size})")
    return size, typ, head


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from(">H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from(">I", buf, off)[0]


def _u64(buf: bytes, off: int) -> int:
    return struct.unpack_from(">Q", buf, off)[0]


#: 里面还有盒子、要往下走的。`meta` / `stsd` 特殊:它们是 full box,名字后面还有 version/flags。
_CONTAINERS = frozenset({
    "moov", "trak", "mdia", "minf", "stbl", "udta", "edts", "dinf", "mvex",
    "moof", "traf", "mfra", "ilst", "tref",
})
#: 采样描述里的"图像样本入口":`compressorname` 在这 78 字节固定部分的第 42 字节处
#: (`ffprobe` 看不见它,见 ADR 0062)。
VISUAL_SAMPLE_ENTRIES = frozenset({
    "avc1", "avc2", "avc3", "avc4", "hvc1", "hev1", "hvt1", "mp4v", "dvh1", "dvhe",
    "ap4h", "apch", "apcn", "apcs", "apco", "ap4x", "jpeg", "vp08", "vp09", "av01",
})
AUDIO_SAMPLE_ENTRIES = frozenset({"mp4a", "ac-3", "ec-3", "Opus", "alac", "fLaC", "samr", "sawb"})
#: 加了密的不在我们这条路上 —— 载荷里读不出画面,谈不上"画面逐字节相同"。
ENCRYPTED_SAMPLE_ENTRIES = frozenset({"encv", "enca", "encs", "enct"})
#: 承载 GPS / 位置:**默认剥**。
GPS_BOXES = frozenset({"loci", "©xyz", "gspd", "gsst", "gstd"})
#: 承载相机 / 软件 / 作者。列出来是为了能在对账文本里**点名说清楚**剥掉了什么。
KNOWN_METADATA_BOXES = frozenset({
    "©nam", "©ART", "©alb", "©gen", "©day", "©too", "©cmt", "©des", "©lyr", "©wrt",
    "©mak", "©mod", "©swr", "©aut", "©cpy", "©grp", "©enc", "©dir", "©prd", "©src",
    "©xyz", "©inf", "©isr", "©lab", "©Lal", "cprt", "desc", "purd", "ldes", "tvsh",
    "tven", "tvsn", "tvnn", "keys", "Xtra", "loci", "chpl", "titl", "dscp", "perf",
    "auth", "gnre", "albm", "yrrc", "rtng", "clsf", "kywd", "ID32", "covr",
})


@dataclass
class Box:
    typ: str
    start: int          # **文件里的绝对偏移**(moov 内的盒子解析后整体平移过)
    size: int
    head: int           # 头长度:8 或 16(64 位长度)
    children: list["Box"] = field(default_factory=list)
    #: full box 的 version/flags 之类的、名字后面的固定前缀长度(相对 payload)。
    skip: int = 0
    #: `uuid` 盒子的 16 字节 usertype。
    usertype: bytes = b""

    @property
    def payload(self) -> int:
        return self.start + self.head + self.skip

    @property
    def end(self) -> int:
        return self.start + self.size

    def find(self, typ: str) -> "Box | None":
        for child in self.children:
            if child.typ == typ:
                return child
        return None

    def find_all(self, typ: str) -> list["Box"]:
        return [child for child in self.children if child.typ == typ]

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def _parse(buf: bytes, start: int, end: int, base: int, depth: int = 0) -> list[Box]:
    """`buf` 是 moov 的内容;`base` 是 moov 在文件里的起点 —— 报出去的偏移都是文件绝对偏移。"""
    out: list[Box] = []
    pos = start
    while pos + 8 <= end:
        size, typ, head = _header(buf, pos, end)
        box = Box(typ=typ, start=base + pos, size=size, head=head)
        if typ == "uuid":
            box.usertype = bytes(buf[pos + head:pos + head + 16])
            box.head = head + 16
        if typ in _CONTAINERS and depth < 12:
            box.children = _parse(buf, pos + box.head, pos + size, base, depth + 1)
        elif typ == "meta" and depth < 12:
            box.skip = 4
            box.children = _parse(buf, pos + box.head + 4, pos + size, base, depth + 1)
        elif typ == "stsd" and depth < 12:
            box.skip = 8  # version/flags(4) + entry_count(4)
            box.children = _parse_entries(buf, pos + box.head + 8, pos + size, base)
        out.append(box)
        pos += size
    return out


def _parse_entries(buf: bytes, start: int, end: int, base: int) -> list[Box]:
    out: list[Box] = []
    pos = start
    while pos + 8 <= end:
        size, typ, head = _header(buf, pos, end)
        box = Box(typ=typ, start=base + pos, size=size, head=head)
        fixed = 78 if typ in VISUAL_SAMPLE_ENTRIES else (28 if typ in AUDIO_SAMPLE_ENTRIES else 0)
        child_at = pos + head + fixed
        if fixed and child_at < pos + size:
            box.children = _parse(buf, child_at, pos + size, base, 9)
        out.append(box)
        pos += size
    return out


@dataclass
class MediaTrack:
    """一条轨。**名字刻意不叫 `Track`** —— `db.models` 里有一个同名模型,数据归属棘轮按类名扫,
    会把这里当成"跨领域建行"(踩过)。这里只是从 moov 读出来的一堆事实,不是数据库的行。"""

    index: int
    handler: str               # 'vide' / 'soun' / 'meta' / 'tmcd' / 'text' / …
    codec: str                 # 样本入口的 fourcc:'avc1' / 'hvc1' / 'mp4a' / 'gpmd' / …
    timescale: int
    sample_sizes: list[int]
    chunk_offsets: list[int]
    samples_per_chunk: list[tuple[int, int]]   # (first_chunk 1-based, samples_per_chunk)
    total_duration: int
    #: 样本里每个 NAL 前面几个字节是长度(`avcC` / `hvcC` 的 lengthSizeMinusOne+1)。非 AVC/HEVC 是 0。
    nal_length_size: int = 0
    #: VisualSampleEntry 的 `compressorname` 字段在文件里的绝对偏移(没有就是 None)。
    compressorname_at: int | None = None
    box_start: int = 0
    box_end: int = 0
    track_id: int = 0

    @property
    def sample_count(self) -> int:
        return len(self.sample_sizes)

    @property
    def is_data(self) -> bool:
        """数据轨 / 遥测 / 时间码 / 字幕 / 附件:默认一律不进输出。"""
        return self.handler not in ("vide", "soun")

    def chunk_runs(self) -> dict[int, int]:
        """`stsc` 展开成 {chunk 序号(1 起): 这一 chunk 里几个样本}。"""
        runs: dict[int, int] = {}
        entries = self.samples_per_chunk
        if not entries:
            return runs
        total = len(self.chunk_offsets)
        for i, (first, per) in enumerate(entries):
            last = entries[i + 1][0] - 1 if i + 1 < len(entries) else total
            for chunk in range(first, min(last, total) + 1):
                runs[chunk] = per
        return runs

    def iter_samples(self):
        """逐个样本 yield `(序号, 文件偏移, 长度)` —— 按需 seek,**不整份读**。"""
        runs = self.chunk_runs()
        seq = 0
        total = len(self.sample_sizes)
        for chunk, offset in enumerate(self.chunk_offsets, start=1):
            cursor = offset
            for _ in range(runs.get(chunk, 0)):
                if seq >= total:
                    return
                size = self.sample_sizes[seq]
                yield seq, cursor, size
                cursor += size
                seq += 1

    def sample_spans(self) -> list[tuple[int, int]]:
        return [(offset, size) for _, offset, size in self.iter_samples()]


@dataclass
class Mp4File:
    path: Path
    size: int
    major_brand: str
    boxes: list[Box]
    tracks: list[MediaTrack]
    fragmented: bool
    encrypted: bool

    def top_level(self, typ: str) -> list[Box]:
        return [box for box in self.boxes if box.typ == typ]

    def find_moov_box(self, typ: str) -> Box | None:
        moov = self.top_level("moov")
        return moov[0].find(typ) if moov else None

    def all_boxes(self):
        for box in self.boxes:
            yield from box.walk()

    @property
    def moov_start(self) -> int:
        moov = self.top_level("moov")
        return moov[0].start if moov else 0


def open_mp4(path: Path) -> Mp4File:
    """打开一份 MP4/QuickTime:顶层盒子逐个读头(不读 body),只有 moov 整份读进内存。"""
    path = Path(path)
    size = path.stat().st_size
    boxes: list[Box] = []
    with path.open("rb") as handle:
        pos = 0
        while pos + 8 <= size:
            handle.seek(pos)
            raw = handle.read(16)
            if len(raw) < 8:
                break
            bsize = struct.unpack_from(">I", raw, 0)[0]
            typ = raw[4:8].decode("latin-1")
            head = 8
            if bsize == 1:
                if len(raw) < 16:
                    raise Mp4Error("truncated large box header")
                bsize = struct.unpack_from(">Q", raw, 8)[0]
                head = 16
            elif bsize == 0:
                bsize = size - pos
            if bsize < head or pos + bsize > size:
                raise Mp4Error(f"bad box {typ!r} at {pos} (size {bsize})")
            box = Box(typ=typ, start=pos, size=bsize, head=head)
            if typ == "uuid":
                box.usertype = bytes(raw[head:head + 16])
                box.head = head + 16
            boxes.append(box)
            pos += bsize

    moov_box = next((box for box in boxes if box.typ == "moov"), None)
    if moov_box is None:
        raise Mp4Error("no moov box")
    if moov_box.size > MAX_MOOV_BYTES:
        raise Mp4Error("moov too large to parse")
    # 只读 moov 那一段,后面几 GB 的 mdat 不进内存。
    with path.open("rb") as handle:
        handle.seek(moov_box.start)
        moov_raw = handle.read(moov_box.size)
    moov_start, moov_head, moov_size = moov_box.start, moov_box.head, moov_box.size
    moov_box.children = _parse(moov_raw, moov_head, moov_size, moov_start)

    major = ""
    ftyp = next((box for box in boxes if box.typ == "ftyp"), None)
    if ftyp is not None:
        with path.open("rb") as handle:
            handle.seek(ftyp.payload)
            major = handle.read(4).decode("latin-1")

    tracks: list[MediaTrack] = []
    for trak in moov_box.find_all("trak"):
        track = _track(trak, moov_raw, moov_start, len(tracks))
        if track is not None:
            tracks.append(track)
    return Mp4File(
        path=path, size=size, major_brand=major, boxes=boxes, tracks=tracks,
        fragmented=any(box.typ == "moof" for box in boxes) or moov_box.find("mvex") is not None,
        encrypted=any(track.codec in ENCRYPTED_SAMPLE_ENTRIES for track in tracks),
    )


def _rel(buf: bytes, box: Box, base: int) -> bytes:
    return buf[box.start - base:box.end - base]


def _track(trak: Box, moov: bytes, base: int, index: int) -> MediaTrack | None:
    mdia = trak.find("mdia")
    if mdia is None:
        return None
    timescale, duration = 0, 0
    mdhd = mdia.find("mdhd")
    if mdhd is not None:
        raw = _rel(moov, mdhd, base)
        if raw[0] == 1:
            timescale, duration = _u32(raw, 28), _u64(raw, 32)
        else:
            timescale, duration = _u32(raw, 20), _u32(raw, 24)
    handler = ""
    hdlr = mdia.find("hdlr")
    if hdlr is not None and hdlr.size >= hdlr.head + 20:
        # full box:version/flags(4) + pre_defined(4) + handler_type(4)
        handler = _rel(moov, hdlr, base)[16:20].decode("latin-1")
    minf = mdia.find("minf")
    stbl = minf.find("stbl") if minf is not None else None
    if stbl is None:
        return None
    codec = ""
    length_size = 0
    compressorname_at: int | None = None
    stsd = stbl.find("stsd")
    if stsd is not None and stsd.children:
        entry = stsd.children[0]
        codec = entry.typ
        if entry.typ in VISUAL_SAMPLE_ENTRIES:
            # SampleEntry 自己 8 字节(6 reserved + data_reference_index),再接
            # pre_defined/reserved/dimension/resolution/frame_count 那 34 字节,才是 compressorname。
            compressorname_at = entry.start + entry.head + 42
        for child in entry.children:
            if child.typ in ("avcC", "hvcC"):
                length_size = _nal_length_size(_rel(moov, child, base), child.typ)
    track_id = 0
    tkhd = trak.find("tkhd")
    if tkhd is not None:
        raw = _rel(moov, tkhd, base)
        # tkhd:version/flags(4) + creation + modification + track_ID
        track_id = _u32(raw, 28) if raw[0] == 1 else _u32(raw, 20)
    return MediaTrack(
        index=index, handler=handler, codec=codec, timescale=timescale,
        sample_sizes=_sample_sizes(moov, stbl, base),
        chunk_offsets=_chunk_offsets(moov, stbl, base),
        samples_per_chunk=_stsc(moov, stbl, base),
        total_duration=duration, nal_length_size=length_size,
        compressorname_at=compressorname_at, box_start=trak.start, box_end=trak.end,
        track_id=track_id,
    )


def _nal_length_size(raw: bytes, typ: str) -> int:
    """`avcC` / `hvcC` 里的 `lengthSizeMinusOne` —— 样本里每个 NAL 前几个字节是长度。

    `raw` 是整个盒子(含 size + type),所以载荷从第 8 字节起:

    - `avcC`:configurationVersion(1) + profile(1) + compatibility(1) + level(1),第 5 个载荷
      字节的低 2 位就是它。
    - `hvcC`:在它前面还压着 profile/compat/constraint/level/分段/并行/chroma/位深/帧率,
      那个字节落在载荷第 22 个。

    读错这个字节不会报错,只会**把每个 NAL 的长度前缀读成别的宽度** —— 后果是 SEI 定位整个偏掉
    (实测踩过:读成 2 字节时,4 字节前置零刚好让它"看起来"还能解析,到 H.265 就散架了)。
    """
    if typ == "avcC" and len(raw) >= 13:
        return (raw[12] & 0x03) + 1
    if typ == "hvcC" and len(raw) >= 30:
        return (raw[29] & 0x03) + 1
    return 0


def _sample_sizes(moov: bytes, stbl: Box, base: int) -> list[int]:
    stsz = stbl.find("stsz")
    if stsz is not None:
        raw = _rel(moov, stsz, base)
        fixed = _u32(raw, 12)
        count = _u32(raw, 16)
        if fixed:
            return [fixed] * count
        return [_u32(raw, 20 + 4 * i) for i in range(count)]
    stz2 = stbl.find("stz2")
    if stz2 is not None:
        raw = _rel(moov, stz2, base)
        field = raw[15]
        count = _u32(raw, 16)
        out: list[int] = []
        pos = 20
        if field == 16:
            out = [_u16(raw, pos + 2 * i) for i in range(count)]
        elif field == 8:
            out = list(raw[pos:pos + count])
        elif field == 4:
            for i in range(count):
                byte = raw[pos + i // 2]
                out.append((byte >> 4) if i % 2 == 0 else (byte & 0x0F))
        return out
    return []


def _chunk_offsets(moov: bytes, stbl: Box, base: int) -> list[int]:
    stco = stbl.find("stco")
    if stco is not None:
        raw = _rel(moov, stco, base)
        count = _u32(raw, 12)
        return [_u32(raw, 16 + 4 * i) for i in range(count)]
    co64 = stbl.find("co64")
    if co64 is not None:
        raw = _rel(moov, co64, base)
        count = _u32(raw, 12)
        return [_u64(raw, 16 + 8 * i) for i in range(count)]
    return []


def _stsc(moov: bytes, stbl: Box, base: int) -> list[tuple[int, int]]:
    stsc = stbl.find("stsc")
    if stsc is None:
        return []
    raw = _rel(moov, stsc, base)
    count = _u32(raw, 12)
    return [(_u32(raw, 16 + 12 * i), _u32(raw, 20 + 12 * i)) for i in range(count)]


# ---------------- 原地改 ----------------


def read_at(path: Path, offset: int, size: int) -> bytes:
    with Path(path).open("rb") as handle:
        handle.seek(offset)
        return handle.read(size)


class Reader:
    """**一个句柄读很多段。** 逐样本比对时 `read_at` 每个样本开关一次文件:
    3 分钟 1080p 有五千多个样本,光 `open()` 就占掉验收的大头(实测门禁 58 秒,其中绝大多数是它)。
    """

    def __init__(self, path: Path) -> None:
        self._handle = Path(path).open("rb")

    def read(self, offset: int, size: int) -> bytes:
        self._handle.seek(offset)
        return self._handle.read(size)

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "Reader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def write_at(path: Path, offset: int, data: bytes) -> None:
    """原地覆盖同样长度的字节。长度不符直接报错 —— 这一层只做等长改写。"""
    with Path(path).open("r+b") as handle:
        handle.seek(offset)
        current = handle.read(len(data))
        if len(current) != len(data):
            raise Mp4Error("short write target")
        handle.seek(offset)
        handle.write(data)


def append_box(path: Path, typ: str, payload: bytes, usertype: bytes = b"") -> int:
    """把一个盒子**追加到文件尾**。

    `uuid` 盒子的收留走这条路:放文件尾不动任何已有偏移(mp4 的顶层盒子顺序无约束,
    读 C2PA 的人扫的是顶层盒子而不是位置)。返回写进去的字节数。
    """
    body = (usertype + payload) if typ == "uuid" else payload
    header = struct.pack(">I", 8 + len(body)) + typ.encode("latin-1")
    with Path(path).open("ab") as handle:
        handle.write(header + body)
    return 8 + len(body)


def ftyp_compatible(path: Path) -> bool:
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(12)
    except OSError:
        return False
    return len(head) >= 12 and head[4:8] == b"ftyp"
