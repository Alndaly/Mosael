"""清除元数据的引擎:**重封装容器 → 原地改码流 → 逐字节对账**。

三步,顺序不能换:

1. **重封装**(`ffmpeg -c copy`):画面和声音的样本**原样搬过去**,去掉容器层的标签、GPS、
   设备/软件、封面,丢掉数据轨(GPMF 遥测 / 时间码 / 定时元数据),`-fflags +bitexact` 让
   muxer 不再自己写 `Lavf…` / `encoder` 这类字样(不写就会漏,实测)。输出一律 MP4。
2. **原地改码流**:在输出文件的 mdat 里**等长**改写 —— SEI NAL 换成填充 NAL、AAC 的
   `DSE` 换成等长填充元素(放不下就原地清零)、写过东西的填充字节清零、`compressorname`
   清零、不该留的 `uuid` 盒子改成 `free`。长度全都不变,所以 `stsz` / `stco` 一字节不动,
   而"画面载荷逐字节等于输入"这条验收才立得住。
3. **对账与门禁**:`gates.py` 逐条扫字节(不看 `ffprobe`),`report.py` 出一份人读的清账。

两件必须说清的事:

- **`ffmpeg` 会把所有顶层 `uuid` 盒子丢掉**,C2PA 的清单就在那儿。所以打开"清 AI 标记"时
  我们不去管它(它已经没了);关着时(`provenance=False`,默认)**把 C2PA 的盒子原样追加回
  文件尾** —— 默认那一趟只动你的隐私,不动"这段是 AI 生成的"这个声明。
- **AAC 那半会自证**:改完之后把音轨解一遍,和**基准**比 PCM 的 MD5。不一样就把音轨的改动
  **整体回滚**(原始字节在手里),并在报告里写清"没敢动"。宁可少清,不可错清。

还有一件:**碎片化输入(moof)的源当不了"输入"** —— moov 的 `stbl` 是空的,样本在 `moof` 里,
读出来 0 个。重封装那一趟(第 1 步)照旧把源收成正片;门禁和音轨自证改用**同一套重封装参数
收出来的规范输入**当基准,见 `canonical`。十道门的条数与含义一个字没改。
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.core.i18n import LocalizedError
from app.media.scratch import scratch_dir
from app.domain.assets.scrub import aac as aac_mod
from app.domain.assets.scrub import canonical as canonical_mod
from app.domain.assets.scrub import findings as findings_mod
from app.domain.assets.scrub import mp4 as mp4_mod
from app.domain.assets.scrub import nal as nal_mod
from app.domain.assets.scrub.findings import MediaFacts
from app.domain.assets.scrub.mp4 import Mp4Error, Reader
from app.domain.assets.scrub.verify import frame_md5, pcm_md5

logger = logging.getLogger(__name__)

#: 对账文本落在源文件旁边,以源素材的 stem 打头。`GET /assets/{id}/scrub-report` 读的就是它。
REMOVED_REPORT_SUFFIX = ".scrub-report.md"


class ScrubError(LocalizedError, ValueError):
    """这次清除做不下去。带文案 key(`scrubErr_*`),按请求方的语言翻(和 gifErr / shotsErr 同一形状)。"""


@dataclass
class AacEdit:
    """音频样本里被改过的字节范围(**样本内**偏移)。门禁照着它比对"只差这几段"。"""

    sample: int
    offset: int
    length: int


@dataclass
class ScrubOutcome:
    source: Path
    target: Path
    provenance: bool
    before: MediaFacts
    after: MediaFacts
    #: 被整条换成填充 NAL 的 SEI。
    sei_nals_replaced: int = 0
    #: 段数(按 SEI 载荷算):清掉的、保留的。
    sei_payloads_removed: int = 0
    sei_payloads_kept: int = 0
    #: 同一个 NAL 里既留又清、只能按内容抹字节的段数;以及定位不到没敢动的段数。
    sei_payloads_zeroed: int = 0
    sei_payloads_unlocated: int = 0
    #: AI 生成标记的 SEI 段数:保留了多少、清了多少。
    sei_provenance_kept: int = 0
    sei_provenance_removed: int = 0
    #: AAC:摘掉的 DSE / 原地清零的 DSE / 清零的填充元素 / 清掉的字节。
    aac_dse_removed: int = 0
    aac_dse_zeroed: int = 0
    aac_fil_zeroed: int = 0
    aac_bytes_zeroed: int = 0
    #: 音轨改动有没有通过"解码后 PCM 一致"的自证;没过就整体回滚。
    aac_verified: bool = True
    aac_rolled_back: bool = False
    aac_edits: list[AacEdit] = field(default_factory=list)
    #: `uuid` 盒子:改成 `free` 的、按默认开关收留的、重新追加回输出的。
    uuid_dropped: int = 0
    uuid_preserved: int = 0
    compressorname_cleared: int = 0
    #: 就地改成 `free` 的 `udta` 盒子数(ffmpeg 会写一个空的 Apple 元数据容器)。
    udta_neutralized: int = 0
    #: 这次清除里最大的单次读取(证"没有整份读进内存")。
    max_read: int = 0
    #: 输入是碎片化 MP4(moof),源当不了逐样本比对的基准 —— 门禁比的是同一套重封装参数收出来的
    #: **规范输入**(见 `canonical`)。对账文本要写明这件事,不然"输入 0 个样本"读着像我们的错。
    canonical_baseline: bool = False
    warnings: list[str] = field(default_factory=list)


# ---------------- uuid 盒子(AI 生成标记) ----------------


def _uuid_boxes(media: mp4_mod.Mp4File) -> list[tuple[bytes, bytes, bool]]:
    """[(usertype, 整个盒子的原始字节, 是不是 AI 生成标记)]。"""
    out: list[tuple[bytes, bytes, bool]] = []
    for box in media.all_boxes():
        if box.typ != "uuid":
            continue
        payload = mp4_mod.read_at(media.path, box.start + box.head, min(box.size - box.head, 4096))
        raw = mp4_mod.read_at(media.path, box.start, box.size)
        out.append((box.usertype, raw, nal_mod.is_provenance_box(box.usertype, payload)))
    return out


def _restore_provenance(staged: Path, boxes: list[tuple[bytes, bytes, bool]], outcome: ScrubOutcome) -> None:
    """`ffmpeg` 会把顶层 `uuid` 盒子全丢掉。默认开关关着时,把 C2PA 的原样追加回文件尾。

    追加在**文件尾**是刻意的:顶层盒子顺序没有约束,而放在前面会把 mdat 往后推、`stco` 里
    每一个 chunk 偏移就都错了。放后面一位偏移都不用动。
    """
    if not boxes:
        return
    keep = [(usertype, raw) for usertype, raw, provenance in boxes if provenance and not outcome.provenance]
    with staged.open("ab") as handle:
        for _, raw in keep:
            handle.write(raw)
    outcome.uuid_preserved = len(keep)
    outcome.uuid_dropped = len(boxes) - len(keep)


# ---------------- 码流层的原地改写 ----------------


@dataclass
class _SeiSplit:
    """一段 SEI NAL 里的载荷分成三堆。"""

    remove: list[bytes] = field(default_factory=list)
    #: 要清的里面有几段是 AI 生成标记(开关打开时它们才走到这里)。
    remove_provenance: int = 0
    #: AI 生成标记,这一次按开关保留。
    keep_provenance: int = 0
    #: 技术的(时间信息、HDR、隐藏字幕),本来就该原样不动。
    keep_technical: int = 0

    @property
    def has_keep(self) -> bool:
        return bool(self.keep_provenance or self.keep_technical)


def _classify_sei(nal, sample: bytes, codec: str, *, provenance: bool) -> _SeiSplit:
    """把一段 SEI NAL 的载荷分成"要清"和"要留"两堆。"""
    split = _SeiSplit()
    for payload_type, payload in nal_mod.sei_payloads(nal.raw(sample), nal.type, codec):
        is_user_data = payload_type == nal_mod.SEI_USER_DATA_UNREGISTERED
        is_provenance = is_user_data and nal_mod.is_provenance_sei(payload_type, payload)
        if is_provenance and not provenance:
            split.keep_provenance += 1
            continue
        if not is_user_data:
            split.keep_technical += 1
            continue
        if is_provenance:
            split.remove_provenance += 1
        split.remove.append(payload)
    return split


def _patch_video(media: mp4_mod.Mp4File, outcome: ScrubOutcome, reader: Reader) -> None:
    """视频样本里的 user-data SEI → 等长填充 NAL(段里还有要留的就只抹要清的那几段)。"""
    for track in media.tracks:
        if track.handler != "vide":
            continue
        codec = nal_mod.NAL_CODECS.get(track.codec)
        if codec is None or not track.nal_length_size:
            outcome.warnings.append(f"视频轨 {track.codec} 不支持按字节重写 SEI,这一层没做")
            continue
        for _, offset, size in track.iter_samples():
            sample = reader.read(offset, size)
            outcome.max_read = max(outcome.max_read, size)
            try:
                nals = nal_mod.split_sample(sample, codec, track.nal_length_size)
            except nal_mod.NalError as exc:
                outcome.warnings.append(f"样本 NAL 长度对不上({exc}),SEI 层未做")
                return
            patched = bytearray(sample)
            changed = False
            for nal in nals:
                if nal.type not in (6, 39, 40):
                    continue
                split = _classify_sei(nal, sample, codec, provenance=outcome.provenance)
                outcome.sei_provenance_kept += split.keep_provenance
                outcome.sei_provenance_removed += split.remove_provenance
                outcome.sei_payloads_kept += split.keep_provenance + split.keep_technical
                if not split.remove:
                    continue
                if split.has_keep:
                    # 同一段 NAL 里既留又清:整条换成填充会把要留的一起丢掉,只能按内容抹字节。
                    zeroed = _zero_payloads(patched, sample, nal, split.remove)
                    outcome.sei_payloads_zeroed += zeroed
                    outcome.sei_payloads_unlocated += len(split.remove) - zeroed
                    outcome.sei_payloads_removed += zeroed
                else:
                    patched[nal.nal_start:nal.end] = nal_mod.filler_nal(nal.size, codec)
                    outcome.sei_nals_replaced += 1
                    outcome.sei_payloads_removed += len(split.remove)
                changed = True
            if changed:
                mp4_mod.write_at(media.path, offset, bytes(patched))


def _zero_payloads(patched: bytearray, sample: bytes, nal, payloads: list[bytes]) -> int:
    """按内容在 NAL 里找到这几段载荷,原地抹成 0。返回定位到的段数。

    SEI 载荷是**原样**存的(只可能被防竞争字节插过 `0x03`,而可见文本里不会出现
    `00 00`,所以不会)。按内容找得到就抹,找不到就不动 —— 找不到的会记进 `sei_payloads_unlocated`
    并在对账文本里点名,不假装清掉了。
    """
    done = 0
    body = sample[nal.nal_start:nal.end]
    for payload in payloads:
        if len(payload) < 8:
            continue
        at = body.find(payload, nal.header)
        if at < 0:
            continue
        start = nal.nal_start + at
        if patched[start:start + len(payload)] == b"\x00" * len(payload):
            done += 1
            continue
        patched[start:start + len(payload)] = b"\x00" * len(payload)
        done += 1
    return done


def _patch_audio(media: mp4_mod.Mp4File, outcome: ScrubOutcome, reader: Reader) -> list[tuple[int, bytes]]:
    """AAC 帧首的 `DSE` 换成等长填充元素、写过东西的填充字节清零。返回可回滚的原始字节。"""
    undo: list[tuple[int, bytes]] = []
    for track in media.tracks:
        if track.handler != "soun" or track.codec != "mp4a":
            continue
        for index, offset, size in track.iter_samples():
            au = reader.read(offset, size)
            outcome.max_read = max(outcome.max_read, size)
            patched, finding = aac_mod.clear(au)
            if patched == au:
                continue
            outcome.aac_dse_removed += finding.dse_count
            outcome.aac_dse_zeroed += finding.dse_zeroed
            outcome.aac_fil_zeroed += finding.fil_count
            outcome.aac_bytes_zeroed += finding.fil_bytes
            _record_edits(outcome.aac_edits, index, au, patched)
            undo.append((offset, au))
            mp4_mod.write_at(media.path, offset, patched)
    return undo


def _record_edits(edits: list[AacEdit], sample: int, before: bytes, after: bytes) -> None:
    """把"哪些字节变了"记成一段段区间 —— 门禁照着它比对输出。"""
    idx = 0
    total = len(before)
    while idx < total:
        if before[idx] == after[idx]:
            idx += 1
            continue
        start = idx
        while idx < total and before[idx] != after[idx]:
            idx += 1
        length = idx - start
        if edits and edits[-1].sample == sample and edits[-1].offset + edits[-1].length == start:
            last = edits[-1]
            edits[-1] = AacEdit(sample=sample, offset=last.offset, length=last.length + length)
        else:
            edits.append(AacEdit(sample=sample, offset=start, length=length))


def _patch_container(media: mp4_mod.Mp4File, outcome: ScrubOutcome) -> None:
    """`compressorname` 清零;留在输出里的 `uuid` 盒子改成 `free`。"""
    for track in media.tracks:
        at = track.compressorname_at
        if not at:
            continue
        raw = mp4_mod.read_at(media.path, at, 32)
        if any(raw):
            mp4_mod.write_at(media.path, at, b"\x00" * 32)
            outcome.compressorname_cleared += 1
    #: `ffmpeg` 重封装后仍会写一个**空的** Apple `udta/meta/ilst`(handler `mdirappl`)。
    #: 里面确实什么都没有,但"什么都没有的元数据容器"留在输出里,等于给下一个往里面塞东西的
    #: 程序留了个位置,而且门禁(扫字节找 `udta`)会红。把盒子的类型改成 `free`、内容清零 ——
    #: 等长、不动任何偏移,读的人按填充跳过。
    for box in list(media.all_boxes()):
        if box.typ != "udta":
            continue
        mp4_mod.write_at(media.path, box.start + 4, b"free")
        if box.size - 8 > 0:
            mp4_mod.write_at(media.path, box.start + 8, b"\x00" * (box.size - 8))
        outcome.udta_neutralized += 1
    for box in list(media.all_boxes()):
        if box.typ != "uuid":
            continue
        payload = mp4_mod.read_at(media.path, box.start + box.head, min(box.size - box.head, 4096))
        if nal_mod.is_provenance_box(box.usertype, payload) and not outcome.provenance:
            continue
        #: 类型改成 `free`,内容清零 —— 长度不变,偏移不动,读的人当填充跳过。
        mp4_mod.write_at(media.path, box.start + 4, b"free")
        if box.size - 8 > 0:
            mp4_mod.write_at(media.path, box.start + 8, b"\x00" * (box.size - 8))
        outcome.uuid_dropped += 1


# ---------------- 主流程 ----------------


def scrub_file(
    source: Path,
    target: Path,
    *,
    provenance: bool = False,
    workdir: Path | None = None,
) -> ScrubOutcome:
    """把 `source` 清一遍写到 `target`。**输入一个字节都不动。**

    `provenance=True` 时连 AI 生成标记(C2PA)一起清 —— 那是另一个开关,默认关,后果见
    `policy.PROVENANCE`。
    """
    source, target = Path(source), Path(target)
    if not source.is_file():
        raise ScrubError("scrubErr_sourceMissing")
    before = findings_mod.inspect(source)
    outcome = ScrubOutcome(source=source, target=target, provenance=provenance, before=before, after=before)
    if not before.container.is_mp4:
        outcome.warnings.append("输入不是 MP4 / QuickTime:上游有哪些容器键读不出来,只能保证输出去掉了")

    #: 暂存目录必须落在数据目录下(`media.scratch`):系统临时目录里的、靠调用方 finally 删的目录,
    #: 进程中途没了就没人收。`workdir` 给了就用调用方的(它自己负责收)。
    holder = Path(workdir) if workdir else scratch_dir("scrub")
    holder.mkdir(parents=True, exist_ok=True)
    staged = holder / (target.stem + ".scrub.mp4")
    try:
        source_boxes: list[tuple[bytes, bytes, bool]] = []
        source_media: mp4_mod.Mp4File | None = None
        if before.container.is_mp4:
            try:
                source_media = mp4_mod.open_mp4(source)
                source_boxes = _uuid_boxes(source_media)
            except (Mp4Error, OSError):
                source_boxes = []
        #: 碎片化输入(moof)的样本表在 moof 里,moov 的 stbl 是空的 —— 源既当不了逐样本比对的
        #: 基准,也当不了音轨自证的基准(容器的 edts/elst 两种写法解出来的 PCM 天生差几百个采样)。
        #: 这里只记一个事实,真正的规范输入由 `gates` 与 `_verify_audio` 各自按需产出(见 `canonical`)。
        outcome.canonical_baseline = canonical_mod.needs_baseline(source_media)
        if outcome.canonical_baseline:
            outcome.warnings.append(
                "输入是碎片化 MP4(样本表在 moof 里,moov 的 stbl 是空的):"
                "上面「清除前发现了什么」里码流层那几项读不出来;逐样本比对的 G6/G7/G8 与 G9 "
                "改用**同一套重封装参数收出来的规范输入**当基准(重封装是 stream copy,VCL 载荷逐字节不变)。"
            )
        canonical_mod.remux(source, staged)
        _restore_provenance(staged, source_boxes, outcome)
        media = mp4_mod.open_mp4(staged)
        if media.encrypted:
            raise ScrubError("scrubErr_encrypted")
        with Reader(staged) as reader:
            _patch_video(media, outcome, reader)
            _patch_container(media, outcome)
            #: 音轨自证的基准:能拿源比就拿源(顺带证明重封装没动声音);碎片化输入拿**改之前那一份
            #: staged** 的 PCM —— 同一个容器、同一批样本,只差我们下面要改的那几个字节。
            #: 拿源直接比在碎片化输入上必然不等(见 `canonical`),那会把每一次 AAC 清理都误判成
            #: "改坏了声音"而整体回滚。
            pristine_pcm = pcm_md5(staged) if outcome.canonical_baseline else None
            undo = _patch_audio(media, outcome, reader)
        if undo:
            _verify_audio(source, staged, undo, outcome, pristine_pcm=pristine_pcm)

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        shutil.move(str(staged), str(target))
        outcome.after = findings_mod.inspect(target)
        return outcome
    finally:
        if workdir is None:
            shutil.rmtree(holder, ignore_errors=True)


def _verify_audio(
    source: Path,
    staged: Path,
    undo: list[tuple[int, bytes]],
    outcome: ScrubOutcome,
    *,
    pristine_pcm: str | None = None,
) -> None:
    """改完音轨解一遍,和**基准**比 PCM。不一样就整体回滚 —— 宁可少清,不可错清。

    基准通常是源;碎片化输入时是"改之前那一份 staged"的 PCM(`pristine_pcm`),理由见 `canonical`。
    """
    try:
        same = (pristine_pcm if pristine_pcm is not None else pcm_md5(source)) == pcm_md5(staged)
    except Exception as exc:
        same = False
        outcome.warnings.append(f"核对音轨失败({exc})")
    if same:
        outcome.aac_verified = True
        return
    for offset, original in undo:
        mp4_mod.write_at(staged, offset, original)
    outcome.aac_verified = False
    outcome.aac_rolled_back = True
    outcome.aac_edits = []
    outcome.aac_dse_removed = outcome.aac_dse_zeroed = outcome.aac_fil_zeroed = outcome.aac_bytes_zeroed = 0
    outcome.warnings.append("清 AAC 帧内元素后解码结果与输入不一致,音轨改动已整体回滚")


def gate_report(outcome: ScrubOutcome) -> list[dict[str, object]]:
    """跑门禁(见 `gates.py`)。放在这里是为了让 job / 节点只 import 一个口。"""
    from app.domain.assets.scrub import gates

    return gates.run_all(outcome)


def render_report(outcome: ScrubOutcome, gates: list[dict[str, object]], *, lang: str = "zh") -> str:
    from app.domain.assets.scrub import report

    return report.render(outcome, gates, lang=lang)


def jsonable(gates: list[dict[str, object]]) -> str:
    return json.dumps(gates, ensure_ascii=False)


__all__ = [
    "AacEdit", "ScrubError", "ScrubOutcome", "frame_md5", "gate_report", "jsonable",
    "render_report", "scrub_file",
]
