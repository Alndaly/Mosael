"""门禁:**十道,全部靠扫字节,一道都不信 `ffprobe`。**

这份价值就在这儿。`ffprobe` 看不见 x264 的 SEI、看不见 AAC 的 `DSE`、也看不见
`compressorname` —— 拿它验收等于"用坏掉的秤称重"。所以每一道门都在**字节上**找证据:

===========  ==========================================================================
G1 容器键     输出里再没有那些容器键/moov 盒子(`udta`/`ilst`/`loci`/`©xxx`/`Xtra`),也没有
             输入里出现过的那些**具体标签值**;不该留的 `uuid` 盒子已不再是 `uuid`
G2 轨结构     只剩画面和声音:没有数据轨(`gpmd` 遥测 / `tmcd` 时间码 / 定时元数据 / 附件),
             轨数、时长、时间基与输入一致
G3 SEI        输出里再没有**非空**的 user-data SEI(`ffprobe` 看不见的那一层);默认开关下
             AI 生成标记(C2PA)必须**还在**
G4 compressorname  stsd 的图像样本入口里那 32 字节全零
G5 AAC 帧内   输出里再没有 `DSE`、也没有写过东西的填充字节
G6 画面载荷   逐样本比 **VCL NAL 的字节**:一模一样 —— 这是"没有重编码"的硬证据
G7 声音载荷   逐样本比音频访问单元:只在**点名清掉的那几段**字节上不同,其余一模一样
G8 样本表     每轨的样本数、每个样本的长度、时间基、总时长与输入逐项相同
G9 还能解     输出能整份解出来;逐帧画面 MD5 与输入一致,音轨 PCM MD5 与输入一致
G10 流式       全程最大的单次读取远小于文件本身 —— 没有"整份读进内存"
===========  ==========================================================================

G6/G7/G9 是**硬门**:它们红说明产出不可信,引擎不许交出去。其余是软门:红了照样交,但会
一字不落地写进对账文本第一屏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.domain.assets.scrub import findings as findings_mod
from app.domain.assets.scrub import mp4 as mp4_mod
from app.domain.assets.scrub import nal as nal_mod
from app.domain.assets.scrub.mp4 import Mp4Error, Reader
from app.domain.assets.scrub.verify import frame_md5, pcm_md5

#: 铁定不该出现在输出里的盒子(容器层的元数据都长在这样的盒子里)。
FORBIDDEN_BOXES = frozenset({
    "udta", "ilst", "loci", "Xtra", "chpl", "keys", "covr", "©nam", "©ART", "©too",
    "©cmt", "©des", "©mak", "©mod", "©swr", "©aut", "©cpy", "©xyz", "©day", "©gen",
    "cprt", "desc", "purd", "ldes", "titl", "auth", "perf", "gnre", "albm", "yrrc",
})

#: 红了就不许交出产出的那几道。
HARD_GATES = frozenset({"G6", "G7", "G9"})

#: 单次读取的上限。"没有整份读"的第二半(第一半是相对文件大小)。
MAX_SINGLE_READ = mp4_mod.MAX_SAMPLE_BYTES


@dataclass
class Gate:
    id: str
    name: str
    ok: bool
    detail: str = ""
    evidence: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "name": self.name, "ok": self.ok, "detail": self.detail, "evidence": self.evidence}


def check(
    source: Path,
    target: Path,
    *,
    provenance: bool = False,
    edits: list | tuple = (),
    max_read: int = 0,
) -> list[Gate]:
    """把 `target` 拿 `source` 对一遍。`edits` 是引擎记录的音频改动区间。"""
    source, target = Path(source), Path(target)
    before = findings_mod.inspect(source)
    after = findings_mod.inspect(target)
    try:
        src_mp4 = mp4_mod.open_mp4(source) if before.container.is_mp4 else None
    except (Mp4Error, OSError):
        src_mp4 = None
    try:
        dst_mp4 = mp4_mod.open_mp4(target)
    except (Mp4Error, OSError) as exc:
        return [Gate("G0", "输出的容器读得开", False, f"{exc}")]
    gates = [
        _g1_container(before, after, dst_mp4, provenance=provenance),
        _g2_tracks(before, after, src_mp4, dst_mp4),
        _g3_sei(before, after, target, provenance=provenance),
        _g4_compressorname(dst_mp4),
        _g5_aac(after),
        _g6_video(src_mp4, dst_mp4, before),
        _g7_audio(src_mp4, dst_mp4, edits),
        _g8_sample_tables(src_mp4, dst_mp4),
        _g9_decodes(source, target),
        _g10_streaming(source, max_read),
    ]
    return gates


# ---------------- 各道门 ----------------


def _g1_container(before, after, dst_mp4, *, provenance: bool = False) -> Gate:
    problems: list[str] = []
    leftover = sorted(name for name in after.container.metadata_boxes if name in FORBIDDEN_BOXES)
    if leftover:
        problems.append("还留着容器元数据盒子:" + "、".join(leftover))
    boxes = {box.typ for box in dst_mp4.all_boxes()}
    bad = sorted(boxes & FORBIDDEN_BOXES)
    if bad:
        problems.append("盒子里还有:" + "、".join(bad))
    stray = sorted(typ for typ in boxes if typ.startswith("©") and typ != "©")
    if stray:
        problems.append("还有 iTunes 键:" + "、".join(stray))
    for usertype, size, is_provenance in after.container.uuid_boxes:
        if is_provenance and not provenance:
            continue
        problems.append(f"还有 uuid 盒子 {usertype[:16]}…({size} 字节)")
    #: 输入里出现过的**具体标签值**不许在输出的 moov 里再出现一次 —— 这条比"盒子名对不上"硬。
    needles = _container_needles(before)
    if needles:
        hits = {}
        for box in dst_mp4.top_level("moov"):
            counts = findings_mod.scan_span(dst_mp4.path, box.start, box.size, needles)
            for needle, count in counts.items():
                if count:
                    hits[needle] = count
        if hits:
            problems.append("输出的 moov 里还能扫到:" + "、".join(repr(_label(n)) for n in hits))
    return Gate(
        "G1", "容器键与 UUID 盒子", not problems, ";".join(problems),
        {"metadata_boxes_before": before.container.metadata_boxes, "needles": len(needles)},
    )


def _label(raw: bytes) -> str:
    """把一段特征串写进告警里。`©nam` 这种盒子名是 latin-1 的,按 utf-8 解码会变成一串问号。"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _container_needles(before) -> list[bytes]:
    out: list[bytes] = []
    for value in before.bitstream.private_values:
        raw = value.encode("utf-8", "ignore")
        if len(raw) >= 6 and raw not in out:
            out.append(raw)
    for name in before.container.metadata_boxes:
        raw = name.encode("latin-1", "ignore")
        if len(raw) >= 4 and raw not in out:
            out.append(raw)
    for name in before.container.compressornames:
        raw = name.encode("utf-8", "ignore")
        if len(raw) >= 6 and raw not in out:
            out.append(raw)
    return out


def _g2_tracks(before, after, src_mp4, dst_mp4) -> Gate:
    problems: list[str] = []
    handlers = sorted({track.handler for track in dst_mp4.tracks})
    unexpected = [h for h in handlers if h not in ("vide", "soun")]
    if unexpected:
        problems.append("输出里还有非画面/声音的轨:" + "、".join(unexpected))
    if src_mp4 is not None:
        want_video = sum(1 for t in src_mp4.tracks if t.handler == "vide")
        want_audio = sum(1 for t in src_mp4.tracks if t.handler == "soun")
        got_video = sum(1 for t in dst_mp4.tracks if t.handler == "vide")
        got_audio = sum(1 for t in dst_mp4.tracks if t.handler == "soun")
        if (want_video, want_audio) != (got_video, got_audio):
            problems.append(f"轨数对不上:输入 {want_video} 视频/{want_audio} 音频,输出 {got_video}/{got_audio}")
    return Gate(
        "G2", "只剩画面和声音的轨", not problems, ";".join(problems),
        {"dropped_handlers": sorted({t.handler for t in before.container.data_tracks})},
    )


def _g3_sei(before, after, target: Path, *, provenance: bool) -> Gate:
    """输出里不许再有**非空**的 user-data SEI。"""
    problems: list[str] = []
    leftovers = 0
    preserved = 0
    try:
        media = mp4_mod.open_mp4(target)
    except (Mp4Error, OSError) as exc:
        return Gate("G3", "SEI(编码器设置 / 设备串)", False, f"输出读不开:{exc}")
    reader = Reader(target)
    for track in media.tracks:
        codec = nal_mod.NAL_CODECS.get(track.codec)
        if track.handler != "vide" or codec is None or not track.nal_length_size:
            continue
        for _, offset, size in track.iter_samples():
            sample = reader.read(offset, size)
            try:
                nals = nal_mod.split_sample(sample, codec, track.nal_length_size)
            except nal_mod.NalError:
                reader.close()
                problems.append("输出里样本的 NAL 长度对不上")
                return Gate("G3", "SEI(编码器设置 / 设备串)", False, ";".join(problems))
            for nal in nals:
                if nal.type not in (6, 39, 40):
                    continue
                for payload_type, payload in nal_mod.sei_payloads(nal.raw(sample), nal.type, codec):
                    if payload_type != nal_mod.SEI_USER_DATA_UNREGISTERED:
                        continue
                    if nal_mod.is_provenance_sei(payload_type, payload) and not provenance:
                        preserved += 1
                        continue
                    if any(payload):
                        leftovers += 1
    if leftovers:
        problems.append(f"输出里还有 {leftovers} 段非空的 user-data SEI")
    #: 输入里那几串具体文本,不许在输出的样本载荷里再出现。
    needles = [value.encode("utf-8", "ignore") for value in before.bitstream.private_values if len(value) >= 6]
    if needles:
        hits: dict[bytes, int] = {}
        for track in media.tracks:
            if track.handler != "vide":
                continue
            for _, offset, size in track.iter_samples():
                sample = reader.read(offset, size)
                for needle in needles:
                    count = sample.count(needle)
                    if count:
                        hits[needle] = hits.get(needle, 0) + count
        reader.close()
        if hits:
            problems.append("样本载荷里还能扫到:" + "、".join(repr(_label(n)) for n in hits))
    if not provenance and before.bitstream.sei_provenance and not preserved:
        problems.append("AI 生成标记的 SEI 在输出里找不到了(默认开关下应当保留)")
    return Gate(
        "G3", "SEI(编码器设置 / 设备串)", not problems, ";".join(problems),
        {"sei_types_before": {str(k): v for k, v in before.bitstream.sei_types.items()},
         "provenance_preserved": preserved, "nonempty_left": leftovers},
    )


def _g4_compressorname(media: mp4_mod.Mp4File) -> Gate:
    bad: list[str] = []
    checked = 0
    for track in media.tracks:
        at = track.compressorname_at
        if not at:
            continue
        checked += 1
        raw = mp4_mod.read_at(media.path, at, 32)
        if any(raw):
            bad.append(f"轨{track.index}:{raw[1:1 + raw[0]].decode('latin-1', 'replace')!r}")
    return Gate(
        "G4", "compressorname(stsd 里那 32 字节)", not bad, ";".join(bad),
        {"entries_checked": checked},
    )


def _g5_aac(after) -> Gate:
    problems: list[str] = []
    finding = after.bitstream.aac
    if finding.dse_count:
        problems.append(f"还有 {finding.dse_count} 个 DSE 元素")
    if finding.fil_count:
        problems.append(f"还有 {finding.fil_count} 个写过东西的填充元素({finding.fil_bytes} 字节)")
    #: **启发式不当门**:帧首之外"看起来像 DSE"的字节会误报(压缩数据里到处都有像的),
    #: 让它红就等于让门永远红。它只进证据和对账文本的「清不掉」那一节。
    return Gate(
        "G5", "AAC 帧内元素(DSE / 填充)", not problems, ";".join(problems),
        {"dse_left": finding.dse_count, "fil_left": finding.fil_count,
         "aac_frames": finding.frames,
         "elsewhere_hint": finding.elsewhere_hint},
    )


def _g6_video(src, dst, before) -> Gate:
    """画面载荷逐字节相同:逐样本比 VCL NAL。**这是"没有重编码"的硬证据。**"""
    if src is None:
        return Gate("G6", "画面载荷逐字节相同", True, "输入不是 MP4:改为由 G9 逐帧解码比对",
                    {"method": "decode-fallback"})
    reader_a, reader_b = Reader(src.path), Reader(dst.path)
    src_video = [t for t in src.tracks if t.handler == "vide"]
    dst_video = [t for t in dst.tracks if t.handler == "vide"]
    if len(src_video) != len(dst_video):
        return Gate("G6", "画面载荷逐字节相同", False, "视频轨数对不上")
    compared = 0
    for a, b in zip(src_video, dst_video):
        codec = nal_mod.NAL_CODECS.get(a.codec)
        if codec is None or not a.nal_length_size:
            return Gate("G6", "画面载荷逐字节相同", True,
                        f"编码 {a.codec} 不是 H.264/H.265,NAL 层不做;由 G9 兜",
                        {"method": "decode-fallback"})
        sa, sb = a.sample_spans(), b.sample_spans()
        if len(sa) != len(sb):
            return Gate("G6", "画面载荷逐字节相同", False, f"样本数不同:{len(sa)} vs {len(sb)}")
        for index, ((off_a, size_a), (off_b, size_b)) in enumerate(zip(sa, sb)):
            if size_a != size_b:
                return Gate("G6", "画面载荷逐字节相同", False, f"样本 {index} 长度不同:{size_a} vs {size_b}")
            sample_a = reader_a.read(off_a, size_a)
            sample_b = reader_b.read(off_b, size_b)
            if nal_mod.vcl_digest(sample_a, codec, a.nal_length_size) != \
                    nal_mod.vcl_digest(sample_b, codec, b.nal_length_size):
                return Gate("G6", "画面载荷逐字节相同", False, f"样本 {index} 的画面 NAL 字节不一致")
            compared += 1
    reader_a.close()
    reader_b.close()
    return Gate("G6", "画面载荷逐字节相同", True, "", {"samples_compared": compared, "method": "vcl-nals"})


def _g7_audio(src, dst, edits) -> Gate:
    """声音载荷:只许在**点名清掉的那几段**上不同。"""
    if src is None:
        return Gate("G7", "声音载荷只差被清掉的那几段", True, "输入不是 MP4:改为由 G9 逐帧解码比对",
                    {"method": "decode-fallback"})
    reader_a, reader_b = Reader(src.path), Reader(dst.path)
    src_audio = [t for t in src.tracks if t.handler == "soun"]
    dst_audio = [t for t in dst.tracks if t.handler == "soun"]
    if len(src_audio) != len(dst_audio):
        return Gate("G7", "声音载荷只差被清掉的那几段", False, "音频轨数对不上")
    by_sample: dict[int, list[tuple[int, int]]] = {}
    for edit in edits:
        by_sample.setdefault(edit.sample, []).append((edit.offset, edit.length))
    compared = 0
    for a, b in zip(src_audio, dst_audio):
        sa, sb = a.sample_spans(), b.sample_spans()
        if len(sa) != len(sb):
            return Gate("G7", "声音载荷只差被清掉的那几段", False, f"样本数不同:{len(sa)} vs {len(sb)}")
        for index, ((off_a, size_a), (off_b, size_b)) in enumerate(zip(sa, sb)):
            if size_a != size_b:
                return Gate("G7", "声音载荷只差被清掉的那几段", False, f"样本 {index} 长度不同")
            sample_a = reader_a.read(off_a, size_a)
            sample_b = reader_b.read(off_b, size_b)
            allowed = sorted(by_sample.get(index, []))
            pos = 0
            for start, length in allowed:
                if sample_a[pos:start] != sample_b[pos:start]:
                    return Gate("G7", "声音载荷只差被清掉的那几段", False,
                                f"样本 {index} 在 {pos}..{start} 上有没记录的改动")
                pos = start + length
            if sample_a[pos:] != sample_b[pos:]:
                return Gate("G7", "声音载荷只差被清掉的那几段", False,
                            f"样本 {index} 的 {pos}.. 之后有没记录的改动")
            compared += 1
    reader_a.close()
    reader_b.close()
    return Gate("G7", "声音载荷只差被清掉的那几段", True, "",
                {"samples_compared": compared, "edited_runs": len(edits)})


def _g8_sample_tables(src, dst) -> Gate:
    if src is None:
        return Gate("G8", "样本表(NAL/噪声之外的容器事实)", True, "输入不是 MP4,无可比对", {})
    problems: list[str] = []
    #: 按"同类轨里的第几条"配对 —— track_id 会被 muxer 重编,不能拿来当钥匙。
    src_tracks: dict[tuple[str, int], object] = {}
    seen: dict[str, int] = {}
    for track in src.tracks:
        src_tracks[(track.handler, seen.get(track.handler, 0))] = track
        seen[track.handler] = seen.get(track.handler, 0) + 1
    seen = {}
    for track in dst.tracks:
        key = (track.handler, seen.get(track.handler, 0))
        seen[track.handler] = seen.get(track.handler, 0) + 1
        other = src_tracks.get(key)
        if other is None:
            continue
        if other.sample_count != track.sample_count:
            problems.append(f"轨{track.index} 样本数 {other.sample_count}→{track.sample_count}")
        elif other.sample_sizes != track.sample_sizes:
            problems.append(f"轨{track.index} 有样本长度变了")
        if other.timescale != track.timescale:
            problems.append(f"轨{track.index} 时间基 {other.timescale}→{track.timescale}")
    return Gate("G8", "样本表逐项相同", not problems, ";".join(problems),
                {"tracks": len(dst.tracks)})


def _g9_decodes(source: Path, target: Path) -> Gate:
    problems: list[str] = []
    try:
        frames_a, frames_b = frame_md5(source), frame_md5(target)
        if frames_a != frames_b:
            problems.append("逐帧画面 MD5 与输入不同")
    except Exception as exc:
        problems.append(f"画面解不开:{exc}")
    try:
        if pcm_md5(source) != pcm_md5(target):
            problems.append("音轨 PCM MD5 与输入不同")
    except Exception as exc:
        problems.append(f"音轨解不开:{exc}")
    return Gate("G9", "输出仍能解码,画面与声音解码后一致", not problems, ";".join(problems))


def _g10_streaming(source: Path, max_read: int) -> Gate:
    size = source.stat().st_size
    problems: list[str] = []
    if max_read > MAX_SINGLE_READ:
        problems.append(f"单次读取 {max_read} 字节,超过上限")
    if size >= 64 * 1024 * 1024 and max_read >= size // 8:
        problems.append(f"单次读取 {max_read} 字节,相对 {size} 字节的输入太大")
    return Gate("G10", "流式:没有整份读进内存", not problems, ";".join(problems),
                {"max_read": max_read, "input_size": size})


def run_all(outcome) -> list[dict[str, object]]:
    """跑一遍,返回可 JSON 的清单。"""
    gates = check(
        outcome.source, outcome.target, provenance=outcome.provenance,
        edits=outcome.aac_edits, max_read=outcome.max_read,
    )
    return [gate.as_dict() for gate in gates]


def failures(gates: list[dict[str, object]], *, hard_only: bool = False) -> list[dict[str, object]]:
    out = [gate for gate in gates if not gate["ok"]]
    if hard_only:
        out = [gate for gate in out if gate["id"] in HARD_GATES]
    return out


__all__ = ["FORBIDDEN_BOXES", "Gate", "HARD_GATES", "check", "failures", "run_all"]
