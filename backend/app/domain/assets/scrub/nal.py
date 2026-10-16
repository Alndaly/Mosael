"""H.264 / H.265 的 NAL 层:把 SEI 认出来,再**等长**换成填充 NAL。

`ffprobe` 看不见这一层,而这正是编码器设置、录制软件、以及一部分设备串号待的地方。已知的
两类载体:

- **H.264 的 SEI(NAL 类型 6)/ H.265 的前缀 SEI(39)、后缀 SEI(40)**,里面 `user_data_unregistered`
  (载荷类型 5)。x264 把整条命令行(`cabac=… ref=… me=…`)塞在这儿,ffmpeg 塞 `Lavc…`,
  不少机型塞固件版本和序列号。判据不是"能播就行",是**字节扫**:见 `gates.py`。
- 同一段字节里还有 `user_data_registered_itu_t_t35`(载荷类型 4):那是 HDR10+ / 隐藏字幕的
  家,所以**默认保留**,只在报告里点名。

**为什么是"等长换掉"而不是"抽掉"**:抽掉一个 NAL,样本长度就变了,moov 里的 `stsz` / `stco`
得整份重算,于是"画面载荷逐字节等于输入"这条验收就没法立。把 SEI 的 NAL 头改成**填充 NAL**
(H.264 类型 12 / H.265 类型 38)、载荷写成 `0xFF`,长度一个字节不差,而填充 NAL 按规范
就是给解码器丢的 —— 实测逐帧解码结果一致(见 `tests/test_media_scrub.py`)。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b

#: 我们能做 NAL 级改写的编码。别的编码(VP8/VP9/AV1/MPEG-4)只做容器层,报告里点名。
NAL_CODECS = {"avc1": "h264", "avc2": "h264", "avc3": "h264", "avc4": "h264", "hvc1": "hevc", "hev1": "hevc"}

#: H.264 / H.265 里承载自由文本与厂家数据的 SEI 载荷类型。
SEI_USER_DATA_UNREGISTERED = 5
SEI_USER_DATA_REGISTERED = 4

#: 填充 NAL 的类型:按规范就是"给解码器丢的"。
FILLER_NAL_TYPE = {"h264": 12, "hevc": 38}
#: 一个 access unit 里真正的画面数据(VCL)。验收要按它逐字节比 —— 见 `gates.py` 的 G6。
VCL_TYPES = {"h264": frozenset({1, 2, 3, 4, 5}), "hevc": frozenset(range(0, 32))}

#: C2PA(AI 生成标记)在 MP4 `uuid` 盒子与 SEI `user_data_unregistered` 里用的 UUID。
#: 实测:这两处是同一串;JUMBF 用 `jumd` 盒子再包一层。
C2PA_UUID = bytes.fromhex("6332706100110010800000aa00389b71")
#: 载荷里出现这几个词也算 AI 生成标记 —— 有的实现只写 JUMBF 描述符而不带那串 UUID。
PROVENANCE_MARKERS = (b"c2pa", b"jumbf", b"JUMBF")


class NalError(ValueError):
    """这份码流不是我们认得的形状。"""


@dataclass(frozen=True)
class Nal:
    start: int          # 在样本内的偏移(**含**长度前缀)
    end: int
    type: int
    header: int         # NAL 头长度:1(H.264)或 2(H.265)
    prefix: int         # 长度前缀的字节数(1 / 2 / 4)

    @property
    def nal_start(self) -> int:
        """NAL 头本身在样本内的偏移。"""
        return self.start + self.prefix

    @property
    def size(self) -> int:
        """整个 NAL(含头、**不含**长度前缀)的字节数。"""
        return self.end - self.nal_start

    def raw(self, sample: bytes) -> bytes:
        """这个 NAL 的原始字节(从 NAL 头开始)。"""
        return sample[self.nal_start:self.end]


def split_sample(sample: bytes, codec: str, length_size: int) -> list[Nal]:
    """把 AVCC / HVCC 格式的样本拆成 NAL 单元。

    `avc1` / `hvc1` 这类样本里,每个 NAL 前面是 `length_size` 字节的大端长度(见 stsd 的
    `avcC` / `hvcC`)。长度对不上就报错 —— 悄悄跳过等于把没清干净的字节报成清干净了。
    """
    if length_size not in (1, 2, 4):
        raise NalError(f"unsupported nal length size {length_size}")
    out: list[Nal] = []
    pos = 0
    header = 1 if codec == "h264" else 2
    total = len(sample)
    while pos + length_size <= total:
        size = int.from_bytes(sample[pos:pos + length_size], "big")
        start = pos
        pos += length_size
        if size == 0:
            # 长度 0 的 NAL 是允许的填充,不携带任何东西。
            continue
        if pos + size > total:
            raise NalError(f"NAL length {size} runs past the sample")
        out.append(Nal(start=start, end=pos + size, type=_nal_type(sample[pos], codec), header=header, prefix=length_size))
        pos += size
    if pos != total:
        raise NalError("trailing bytes after the last NAL")
    return out


def _nal_type(first: int, codec: str) -> int:
    if codec == "h264":
        return first & 0x1F
    return (first >> 1) & 0x3F


def unescape_rbsp(data: bytes) -> bytes:
    """去掉防竞争字节(`00 00 03` → `00 00`)。"""
    out = bytearray()
    zeros = 0
    for byte in data:
        if zeros >= 2 and byte == 0x03:
            zeros = 0
            continue
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


def sei_payloads(nal: bytes, nal_type: int, codec: str) -> list[tuple[int, bytes]]:
    """拆出 SEI 里的一段段载荷 → [(载荷类型, 载荷字节)]。

    载荷类型和长度都是"每个 0xFF 加 255"的编码。先去掉防竞争字节再读 —— 我们只关心
    "是什么类型、里面写了什么",不需要原始位偏移(整条 NAL 会被等长换掉)。
    """
    header = 1 if codec == "h264" else 2
    _ = nal_type
    raw = unescape_rbsp(nal[header:])
    out: list[tuple[int, bytes]] = []
    pos = 0
    while pos < len(raw):
        ptype = 0
        while pos < len(raw) and raw[pos] == 0xFF:
            ptype += 255
            pos += 1
        if pos >= len(raw):
            break
        ptype += raw[pos]
        pos += 1
        psize = 0
        while pos < len(raw) and raw[pos] == 0xFF:
            psize += 255
            pos += 1
        if pos >= len(raw):
            break
        psize += raw[pos]
        pos += 1
        if psize == 0:
            break
        out.append((ptype, raw[pos:pos + psize]))
        pos += psize
    return out


def filler_nal(length: int, codec: str) -> bytes:
    """造一个**长度正好是 `length` 字节**的填充 NAL。

    H.264 的类型 12 / H.265 的类型 38,载荷按规范是 `0xFF`。长度不够放下头部就报错 ——
    调用方只该拿它替换比头部长的 NAL(SEI 至少也有十几字节)。
    """
    header = 1 if codec == "h264" else 2
    if length < header + 1:
        raise NalError("NAL too short to become a filler")
    if codec == "h264":
        head = bytes([FILLER_NAL_TYPE["h264"]])          # forbidden=0, ref_idc=0, type=12
    else:
        # forbidden(1) + type(6) + layer_id(6) + temporal_id_plus1(3)
        head = bytes([FILLER_NAL_TYPE["hevc"] << 1, 0x01])
    return head + b"\xff" * (length - header)


def is_provenance_sei(payload_type: int, payload: bytes) -> bool:
    """这段 SEI 是不是 AI 生成标记(C2PA)。

    两种写法都认:注册的 `user_data_unregistered`(前 16 字节是 UUID)以及载荷里直接写着
    `c2pa` / `jumbf` 的实现。
    """
    if payload_type == SEI_USER_DATA_UNREGISTERED and payload[:16] == C2PA_UUID:
        return True
    lowered = payload.lower()
    return any(marker.lower() in lowered for marker in PROVENANCE_MARKERS)


def is_provenance_box(usertype: bytes, payload: bytes) -> bool:
    """`uuid` 盒子是不是 AI 生成标记。"""
    if usertype == C2PA_UUID:
        return True
    return any(marker.lower() in payload.lower() for marker in PROVENANCE_MARKERS)


def vcl_units(sample: bytes, codec: str, length_size: int) -> list[bytes]:
    """样本里的画面数据(VCL)NAL,**原样**列出 —— 验收比的就是这些字节。"""
    keep = VCL_TYPES[codec]
    return [nal.raw(sample) for nal in split_sample(sample, codec, length_size) if nal.type in keep]


def vcl_digest(sample: bytes, codec: str, length_size: int) -> tuple[int, ...]:
    """画面载荷的指纹:每个 VCL NAL 的长度 + 内容摘要(用标准库的 blake2b,免得多带依赖)。

    只比"长度序列"是不够的 —— 长度一样、字节不同(重编码过的画面常常长度相近)会被放过。
    """
    out: list[int] = []
    for unit in vcl_units(sample, codec, length_size):
        out.append(len(unit))
        out.append(int.from_bytes(blake2b(unit, digest_size=8).digest(), "big"))
    return tuple(out)
