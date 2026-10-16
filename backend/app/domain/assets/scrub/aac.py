"""AAC 帧里 `ffprobe` 看不见的那一层:`data_stream_element` 与 `fill_element`。

AAC 的每个访问单元(MP4 的 `mp4a` 样本里就是裸的 `raw_data_block`,没有 ADTS 头)是一串
定长语法元素:

    raw_data_block() {
        while ((id_syn_ele = getbits(3)) != ID_END) {
            SCE(0) | CPE(1) | CCE(2) | LFE(3) | DSE(4) | PCE(5) | FIL(6)
        }
        byte_alignment();
    }

`DSE`(4)按定义就是"给应用塞任意字节"的口子 —— 有设备把账号、序列号、型号塞这儿;
`FIL`(6)按定义是填充,但 ffmpeg 自己的 AAC 编码器**把 `Lavc63.1.102` 这种版本串写进了
填充字节**(实测,见 `tests/test_media_scrub.py`)。两者 `ffprobe` 都不显示。

**能做到什么、做不到什么,说清楚**:要走到 `DSE`,得先跳过它前面的元素;而 `SCE`/`CPE`
的帧内数据是 Huffman 编码的,跳过去等于写一个完整的 AAC 解码器。所以本模块只解析
**帧首那一段**(`DSE` / `FIL` / `PCE` 连着排的前缀),走到第一个音频元素就停。
其余位置的 `DSE` 用启发式**报出来**(见 `scan`),但不清 —— 猜错一个比特就是音频损坏,
而"猜"不该出现在这条路上。

**替换是等长的**:一个 `DSE` 占 `16 + 8n` 比特(带转义是 `24 + 8n`),一律 ≡ 0 (mod 8);
而单个 `FIL` 恒为 `4 + 8u` 比特 ≡ 4 (mod 8),凑不出来。两个 `FIL` 加起来 ≡ 0 (mod 8),
可以凑出 ≥ 56 且 ≡ 0 (mod 8) 的比特数(见 `dse_replacement`)。于是**元素被换掉、长度一
比特不差**,后面的字节一个都不用动,容器里的 `stsz` 也就不用重算。
"""

from __future__ import annotations

from dataclasses import dataclass

ID_SCE, ID_CPE, ID_CCE, ID_LFE, ID_DSE, ID_PCE, ID_FIL, ID_END = range(8)
#: 走到这些元素就得停 —— 它们的长度要完整解码器才算得出来。
AUDIO_ELEMENTS = frozenset({ID_SCE, ID_CPE, ID_CCE, ID_LFE})
#: 前缀里能自己算长度、可以跳过的。
SKIPPABLE = frozenset({ID_DSE, ID_PCE, ID_FIL})
class AacError(ValueError):
    """这不是一个我们看得懂的 AAC raw_data_block。"""


class BitReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    @property
    def remaining(self) -> int:
        return len(self.data) * 8 - self.pos

    def bits(self, count: int) -> int:
        if count <= 0:
            return 0
        if self.pos + count > len(self.data) * 8:
            raise AacError("read past the end of the access unit")
        value = 0
        for _ in range(count):
            byte = self.data[self.pos >> 3]
            value = (value << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return value

    def align(self) -> None:
        self.pos = (self.pos + 7) & ~7


class BitWriter:
    def __init__(self) -> None:
        self._bits: list[int] = []

    def bit(self, value: int) -> None:
        self._bits.append(value & 1)

    def bits(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self._bits.append((value >> shift) & 1)

    def raw(self, bits: list[int]) -> None:
        self._bits.extend(bits)

    @property
    def length(self) -> int:
        return len(self._bits)

    def to_bytes(self) -> bytes:
        out = bytearray()
        for i in range(0, len(self._bits), 8):
            byte = 0
            for bit in self._bits[i:i + 8]:
                byte = (byte << 1) | bit
            byte <<= max(0, 8 - (len(self._bits) - i))
            out.append(byte)
        return bytes(out)


def bits_of(data: bytes, start: int, end: int) -> list[int]:
    out: list[int] = []
    for pos in range(start, min(end, len(data) * 8)):
        out.append((data[pos >> 3] >> (7 - (pos & 7))) & 1)
    return out


#: 单个 `fill_element` 的转义上限:`cnt = 15` 时再读 8 比特 `esc_count`,`cnt += esc_count - 1`,
#: 于是能表达的长度单位最大 `14 + 255 = 269`。
MAX_FILL_UNITS = 269
#: 要凑出一个 `DSE` 的长度形状(`≡ 0 (mod 8)`),得几个 `fill_element`:每个恒为 `7 + 8u`
#: 比特(`3` 比特元素号 + `4` 比特长度字段 + 填充字节),而 `8 × 7 = 56 ≡ 0 (mod 8)`。
FILLS_PER_REPLACEMENT = 8
#: 少于这么多比特的 `DSE`(载荷 ≤ 4 字节)放不下 8 个填充元素,只能原地清零。
MIN_REPLACEABLE_BITS = FILLS_PER_REPLACEMENT * 7


def _emit_fil(units: int) -> list[int]:
    """一个 `fill_element`,长度**恰好** `7 + 8 * units` 比特。

    `units` 是"折合多少个长度单位",不是填充字节数 —— 转义那一支里两者差 1:

    - `units <= 14`:`id_syn_ele(3) + cnt(4)` + `units` 个填充字节 → `7 + 8u`。
    - `units >= 15`:`cnt` 写 15,再写 8 比特 `esc_count = units - 15`;解码方算回
      `cnt = 15 + esc_count - 1 = units - 1` 个填充字节 → `7 + 8(units-1) + 8 = 7 + 8u`。

    两支的形状因此一致,合起来覆盖 `units ∈ [0, 269]` 的每个整数。
    """
    if units < 0 or units > MAX_FILL_UNITS:
        raise AacError(f"fill element units out of range: {units}")
    writer = BitWriter()
    writer.bits(ID_FIL, 3)
    if units <= 14:
        writer.bits(units, 4)
        for _ in range(units):
            writer.bits(0, 8)
    else:
        writer.bits(15, 4)
        writer.bits(units - 15, 8)
        for _ in range(units - 1):
            writer.bits(0, 8)
    assert writer.length == 7 + 8 * units
    return writer._bits


def dse_replacement(bit_length: int) -> list[int] | None:
    """把一段 `DSE` 换成**等长**的填充元素;放不下就返回 None(调用方改为原地清零)。

    一个 `fill_element` 恒为 `7 + 8u` 比特,永远 ≡ 7 (mod 8),单个换不掉 `≡ 0 (mod 8)` 的
    `DSE`;**八个**加起来是 `56 + 8Σu`,可以凑出任何 `>= 56` 且 `≡ 0 (mod 8)` 的长度。
    元素连同它的字节一起没了,而样本长度一比特不差 —— 容器里的 `stsz` 因此不用动。
    """
    if bit_length < MIN_REPLACEABLE_BITS or bit_length % 8:
        return None
    # 8 个填充元素 = 8×7 + 8×Σunits 比特;要等于 bit_length,Σunits = bit_length/8 - 7。
    budget = bit_length // 8 - 7
    if budget < 0:  # pragma: no cover - 上面已经挡掉了
        return None
    parts: list[int] = []
    remaining = budget
    # 八个填充元素平摊,每个都不超过上限。
    for _ in range(FILLS_PER_REPLACEMENT):
        take = min(remaining, MAX_FILL_UNITS)
        parts.append(take)
        remaining -= take
    if remaining:  # 单个 DSE 的载荷不可能这么大(最多 510 字节)
        return None
    out: list[int] = []
    for units in parts:
        out.extend(_emit_fil(units))
    if len(out) != bit_length:  # pragma: no cover - 凑错了当场炸
        raise AacError(f"replacement produced {len(out)} bits, wanted {bit_length}")
    return out


@dataclass
class Element:
    kind: int          # ID_DSE / ID_FIL / ID_PCE
    start: int         # 比特偏移(相对访问单元开头)
    end: int
    #: `DSE` 里那段自由字节;`FIL` 里那段填充字节。`PCE` 没有。
    payload_start: int = 0
    payload_end: int = 0
    #: `FIL` 的长度字段编码不合法时(转义越界)记一笔,报出去而不是猜。
    broken: bool = False

    @property
    def bit_length(self) -> int:
        return self.end - self.start


def _read_dse(reader: BitReader, start: int) -> Element:
    reader.bits(4)                      # element_instance_tag
    align = reader.bits(1)
    count = reader.bits(8)
    if count == 255:
        count += reader.bits(8)
    if align:
        reader.align()
    payload_start = reader.pos
    reader.bits(8 * count)
    return Element(kind=ID_DSE, start=start, end=reader.pos, payload_start=payload_start, payload_end=reader.pos)


def _read_fil(reader: BitReader, start: int) -> Element:
    count = reader.bits(4)
    if count == 15:
        count += reader.bits(8) - 1
    payload_start = reader.pos
    reader.bits(8 * count)
    return Element(kind=ID_FIL, start=start, end=reader.pos, payload_start=payload_start, payload_end=reader.pos)


def _read_pce(reader: BitReader, start: int) -> Element:
    """`program_config_element()`:全长可算(没有 Huffman),所以能安全跳过。"""
    reader.bits(4)                      # element_instance_tag
    reader.bits(2)                      # object_type
    reader.bits(4)                      # sampling_frequency_index
    front = reader.bits(4)
    side = reader.bits(4)
    back = reader.bits(4)
    lfe = reader.bits(2)
    assoc = reader.bits(3)
    cc = reader.bits(4)
    if reader.bits(1):
        reader.bits(4)
    if reader.bits(1):
        reader.bits(4)
    if reader.bits(1):
        reader.bits(2)
        reader.bits(1)
    for count, is_cpe in ((front, True), (side, True), (back, True)):
        for _ in range(count):
            if is_cpe:
                reader.bits(1)
            reader.bits(4)
    for _ in range(lfe):
        reader.bits(4)
    for _ in range(assoc):
        reader.bits(4)
    for _ in range(cc):
        reader.bits(1)
        reader.bits(4)
    reader.align()
    comment = reader.bits(8)
    reader.bits(8 * comment)
    return Element(kind=ID_PCE, start=start, end=reader.pos)


def prefix_elements(au: bytes) -> list[Element]:
    """访问单元**帧首**那一段可自解析的元素。

    走到第一个音频元素(SCE/CPE/CCE/LFE)或 `ID_END` 就停 —— 再往后要完整解码器。
    看不懂就直接停:前缀为空也是一种诚实的答案。
    """
    reader = BitReader(au)
    out: list[Element] = []
    while reader.remaining >= 3:
        start = reader.pos
        kind = reader.bits(3)
        if kind == ID_END:
            break
        if kind not in SKIPPABLE:
            reader.pos = start
            break
        try:
            if kind == ID_DSE:
                element = _read_dse(reader, start)
            elif kind == ID_FIL:
                element = _read_fil(reader, start)
            else:
                element = _read_pce(reader, start)
        except AacError:
            reader.pos = start
            break
        if element.end > len(au) * 8:
            reader.pos = start
            break
        out.append(element)
    return out


@dataclass
class AacFinding:
    """一段访问单元里发现了什么。报对账文本和喂门禁都用它。"""

    frames: int = 0
    #: 摘掉的 `DSE`(换成等长填充元素,元素本身没了)。
    dse_count: int = 0
    #: 长度不够摘、只能原地清零的 `DSE`。
    dse_zeroed: int = 0
    dse_bytes: int = 0
    fil_count: int = 0
    fil_bytes: int = 0
    #: 启发式:帧首之外还像 `DSE` 的地方(见 `scan`)。
    elsewhere_hint: int = 0
    #: 清不掉的:转义越界之类看得见但读不通的元素。
    broken: int = 0


def scan(au: bytes) -> AacFinding:
    """看一段访问单元里有什么。**不改字节。**"""
    finding = AacFinding(frames=1)
    for element in prefix_elements(au):
        if element.kind == ID_DSE:
            finding.dse_count += 1
            finding.dse_bytes += (element.payload_end - element.payload_start) // 8
        elif element.kind == ID_FIL:
            payload = bits_of(au, element.payload_start, element.payload_end)
            if any(payload):
                finding.fil_count += 1
                finding.fil_bytes += (element.payload_end - element.payload_start) // 8
    finding.elsewhere_hint = _elsewhere_hint(au)
    return finding


def _elsewhere_hint(au: bytes) -> int:
    """帧首之外**看起来**像"字节对齐的 DSE 且载荷是文本"的地方。

    只是给报告用的一句话,不清除。字节对齐的 `DSE` 头长这样:`100t ttta` + 长度字节,
    而 `data_byte_align_flag=1` 时头一定落在字节边界上(头 16 比特、载荷按字节对齐)。
    再要求载荷至少 8 字节且九成以上是可打印 ASCII —— 真元数据几乎都是文本。**这是启发式**,
    会误报,所以报告里写明它是启发式。
    """
    hits = 0
    for pos in range(2, max(0, len(au) - 10)):
        head = au[pos - 2]
        if head & 0xE0 != 0x80 or head & 0x01 != 1:
            continue
        count = au[pos - 1]
        if count == 255 or count < 8:
            continue
        payload = au[pos:pos + count]
        if len(payload) < count:
            continue
        printable = sum(1 for byte in payload if 0x20 <= byte < 0x7F)
        if printable >= int(count * 0.9):
            hits += 1
    return hits


def clear(au: bytes) -> tuple[bytes, AacFinding]:
    """清掉帧首那一段里的 `DSE` 与"写过东西的填充字节",长度一比特不差。

    返回 `(新的访问单元, 发现了什么)`
    - `DSE` → 换成**等长**的填充元素(见 `dse_replacement`),元素连同它的字节一起没了;
      长度不够放下填充元素(载荷 ≤ 4 字节)时退化成**原地清零**并在报告里写明是"清零"不是"摘除"。
    - `FIL` 里非零的填充字节 → 按定义就是填充,清零。ffmpeg 的版本串就在这里。
    - `PCE` → 原样保留(它的 `comment_field_data` 是自由文本,但极少见);报告里点名。

    **所有改写都是等长的** —— 长度一比特不差是这个模块的全部承诺,也是 `gates.py` 里
    "音频载荷逐字节等于输入,只差点名清掉的那几段"这条能立住的前提。
    """
    elements = prefix_elements(au)
    if not elements:
        finding = AacFinding(frames=1, elsewhere_hint=_elsewhere_hint(au))
        return au, finding

    writer = BitWriter()
    cursor = 0
    finding = AacFinding(frames=1)
    for element in elements:
        writer.raw(bits_of(au, cursor, element.start))
        if element.kind == ID_DSE:
            replacement = dse_replacement(element.bit_length)
            if replacement is None:
                # 太短,放不下填充元素:原地清零,元素形状留着 —— 报告里会说清是"清零"。
                writer.raw(bits_of(au, element.start, element.payload_start))
                writer.raw([0] * (element.payload_end - element.payload_start))
                finding.dse_zeroed += 1
            else:
                writer.raw(replacement)
                finding.dse_count += 1
            finding.dse_bytes += (element.payload_end - element.payload_start) // 8
        elif element.kind == ID_FIL:
            payload = bits_of(au, element.payload_start, element.payload_end)
            writer.raw(bits_of(au, element.start, element.payload_start))
            if any(payload):
                writer.raw([0] * len(payload))
                finding.fil_count += 1
                finding.fil_bytes += len(payload) // 8
            else:
                writer.raw(payload)
        else:
            writer.raw(bits_of(au, element.start, element.end))
        cursor = element.end
    writer.raw(bits_of(au, cursor, len(au) * 8))
    finding.elsewhere_hint = _elsewhere_hint(au)
    if writer.length != len(au) * 8:  # pragma: no cover - 等长是本模块的全部承诺
        raise AacError(f"rewrite changed the access unit length: {writer.length} != {len(au) * 8}")
    return writer.to_bytes(), finding


def total(findings: list[AacFinding]) -> AacFinding:
    out = AacFinding()
    for finding in findings:
        out.frames += finding.frames
        out.dse_count += finding.dse_count
        out.dse_zeroed += finding.dse_zeroed
        out.dse_bytes += finding.dse_bytes
        out.fil_count += finding.fil_count
        out.fil_bytes += finding.fil_bytes
        out.elsewhere_hint += finding.elsewhere_hint
        out.broken += finding.broken
    return out
