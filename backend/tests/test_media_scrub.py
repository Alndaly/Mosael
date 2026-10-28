"""清除元数据的验收(ADR 0062):**先红后绿,而且全靠扫字节**。

这套测试的态度来自 reelbench 的 video-scrub:难的从来不是"跑个 ffmpeg",是 `ffprobe`
**看不见**的那三层 —— x264 的 SEI(编码设置)、AAC 帧里的 DSE(有设备把账号塞这儿)、
`compressorname`。所以这里的每一条断言都在字节上找证据,没有一条信 `ffprobe`:

- 输出里**再也扫不到**那些签名(容器键 / SEI / DSE / compressorname / 具体的那几串文本);
- 画面与声音的载荷**逐字节等于输入**(证明没有重编码);
- 门禁**留一处脏数据就会红**(`test_..._goes_red...` 那一组)。

样本是现场造的:ffmpeg 编一段短片,再往里塞进容器标签、GPS、封面、一个数据轨、
一个自定义的 `compressorname`、一个 C2PA `uuid` 盒子、以及手工构造的 AAC `DSE`。
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.domain.assets.scrub import findings
from app.domain.assets.scrub import aac as aac_mod
from app.domain.assets.scrub import canonical as canonical_mod
from app.domain.assets.scrub import gates as gates_mod
from app.domain.assets.scrub import mp4 as mp4_mod
from app.domain.assets.scrub import nal as nal_mod
from app.domain.assets.scrub.engine import scrub_file
from tests.util import fresh_client, wait_status

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

SECRET_TAG = "TRIP-TO-REYKJAVIK-2026"
SECRET_GPS = "+64.1466-21.9426/"
SECRET_CN = "Adobe Premiere Pro 2024"
#: 12 字节 —— 正好塞得进一个 `FIL` 换出来的 `DSE`(见 `_fil_to_dse`)。
SECRET_DSE = b"SN4821ACCT09"

C2PA_UUID = bytes.fromhex("6332706100110010800000aa00389b71")
XMP_UUID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")


# ---------------- 造样本 ----------------


def _encode(path: Path, *, seconds: int = 1, codec: str = "libx264", size: str = "320x240",
            rate: int = 15, tags: bool = True, cover: bool = True, fragmented: bool = False) -> None:
    """现场编一段:画面 + 声音(+ 一张封面图)。标签按需带上。

    `fragmented=True` 编成**碎片化 MP4**:顶层有 `moof`、`moov` 的 `stbl` 是空的(样本表进了
    `moof` 的 `traf/trun`)。维护者库里的 B 站视频大量是这个形状。
    """
    args = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
    ]
    if cover:
        args += ["-f", "lavfi", "-i", f"color=red:size=64x64:duration={seconds}"]
    args += ["-map", "0:v", "-map", "1:a"]
    if cover:
        args += ["-map", "2:v"]
    args += ["-c:v", codec, "-preset", "ultrafast"]
    if cover:
        #: 顺序要紧:先给所有视频流定编码器,再单独给封面那条盖上 mjpeg。
        args += ["-c:v:1", "mjpeg", "-disposition:v:1", "attached_pic"]
    args += ["-c:a", "aac", "-b:a", "96k"]
    if tags:
        args += [
            "-metadata", f"title={SECRET_TAG}", "-metadata", "artist=Jane Doe",
            "-metadata", "comment=private", "-metadata", "encoder=SomeCamera",
            "-metadata", f"location={SECRET_GPS}", "-metadata", "make=GoPro",
            "-metadata", "model=HERO12 Black",
        ]
    args += [
        "-movflags",
        #: `+empty_moov` 是"moov 里不放样本表"的关键,`+default_base_moof` 让样本偏移相对 moof 算 ——
        #: 真素材(以及 B 站那些)也这么写。
        "+frag_keyframe+empty_moov+default_base_moof" if fragmented else "+faststart",
        str(path),
    ]
    subprocess.run(args, check=True, capture_output=True, timeout=300)


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _u32(value: int) -> bytes:
    return struct.pack(">I", value)


def _inject_compressorname(path: Path) -> bool:
    """在 stsd 的图像样本入口里写一个厂家 compressorname(`ffprobe` 看不见它)。"""
    media = mp4_mod.open_mp4(path)
    for track in media.tracks:
        if track.compressorname_at:
            name = SECRET_CN.encode("latin-1")[:31]
            field = bytes([len(name)]) + name + b"\x00" * (31 - len(name))
            mp4_mod.write_at(path, track.compressorname_at, field)
            return True
    return False


def _append_uuid_boxes(path: Path) -> None:
    """C2PA(AI 生成标记)与 Adobe XMP 各一个 `uuid` 盒子,**追加在文件尾**(不动任何 stco 偏移)。"""
    c2pa = _box(b"uuid", C2PA_UUID + b"jumb" + _u32(12) + b"jumd" + b"\x00\x11c2pa manifest")
    xmp = _box(b"uuid", XMP_UUID + b"<x:xmpmeta xmlns:x=\"adobe:ns:meta/\" author=\"Jane Doe\"/>")
    with path.open("ab") as handle:
        handle.write(c2pa + xmp)


def _relabel_track_as_data(path: Path) -> bool:
    """把音轨的 handler 改成 `meta`、样本入口改成 `gpmd` —— 造一条 GoPro 那样的数据轨。

    ffmpeg 的 mp4 muxer 写不出通用数据轨(它只认白名单里的编码),所以按 GoPro 的真实排布
    **原地改 4 个字节**:`hdlr` 的 handler_type 和 `stsd` 的样本入口 fourcc。长度不变。
    """
    media = mp4_mod.open_mp4(path)
    audio = next((track for track in media.tracks if track.handler == "soun"), None)
    if audio is None:
        return False
    changed = False
    for box in media.all_boxes():
        if not (audio.box_start <= box.start < audio.box_end):
            continue
        if box.typ == "hdlr" and mp4_mod.read_at(path, box.start + 16, 4) == b"soun":
            mp4_mod.write_at(path, box.start + 16, b"meta")
            changed = True
        if box.typ == "mp4a":
            mp4_mod.write_at(path, box.start + 4, b"gpmd")
            changed = True
    return changed


def _fil_to_dse(au: bytes, secret: bytes) -> bytes | None:
    """把访问单元**帧首**那个填充元素换成等长的 `DSE`,载荷写 `secret`。

    这是 `aac.clear` 的逆操作,而且**长度不变**:`FIL` 恒为 `7 + 8u` 比特(≡7 mod 8),
    `DSE` 恒为 `16 + 8n` 比特(≡0 mod 8),于是 `DSE` 只要取 `L - 7` 比特,多出来的 7 比特
    正好落回末尾的 `byte_alignment` 里,样本字节数一个不差、容器不用动。
    """
    elements = aac_mod.prefix_elements(au)
    if not elements or elements[0].kind != aac_mod.ID_FIL:
        return None
    length = elements[0].bit_length
    if (length - 23) % 8:
        return None
    count = (length - 23) // 8
    if count < len(secret):
        return None
    payload = (secret + bytes(count - len(secret)))[:count]
    head = aac_mod.BitWriter()
    head.bits(aac_mod.ID_DSE, 3)
    head.bits(0, 4)          # element_instance_tag
    head.bit(1)              # data_byte_align_flag
    head.bits(count, 8)
    for byte in payload:
        head.bits(byte, 8)
    tail = aac_mod.bits_of(au, length, len(au) * 8)
    total = head._bits + tail + [0] * 7
    if len(total) != len(au) * 8:
        return None
    out = aac_mod.BitWriter()
    out.raw(total)
    return out.to_bytes()


def _inject_dse(path: Path) -> int:
    """给音频轨每个能塞的访问单元塞一个 `DSE`(原地,长度不变)。返回塞了几个。"""
    media = mp4_mod.open_mp4(path)
    audio = next((track for track in media.tracks if track.handler == "soun"), None)
    if audio is None:
        return 0
    done = 0
    for _, offset, size in audio.iter_samples():
        au = mp4_mod.read_at(path, offset, size)
        patched = _fil_to_dse(au, SECRET_DSE)
        if patched is None or patched == au:
            continue
        mp4_mod.write_at(path, offset, patched)
        done += 1
    return done


def _dirty_video(path: Path, *, seconds: int = 1, codec: str = "libx264", size: str = "320x240") -> Path:
    """一份"什么脏东西都有"的样本:标签 + GPS + 封面 + compressorname + 两个 uuid 盒子 + SEI + DSE。"""
    _encode(path, seconds=seconds, codec=codec, size=size)
    assert _inject_compressorname(path)
    _append_uuid_boxes(path)
    assert _inject_dse(path) > 0
    return path


# ---------------- 扫字节的帮手 ----------------


def _video_vcl(path: Path) -> list[bytes]:
    media = mp4_mod.open_mp4(path)
    track = next(track for track in media.tracks if track.handler == "vide")
    codec = nal_mod.NAL_CODECS[track.codec]
    out: list[bytes] = []
    for _, offset, size in track.iter_samples():
        sample = mp4_mod.read_at(path, offset, size)
        out.extend(nal_mod.vcl_units(sample, codec, track.nal_length_size))
    return out


def _video_sei(path: Path) -> list[tuple[int, bytes]]:
    """输出里还剩哪些 SEI(载荷类型, 载荷)。"""
    media = mp4_mod.open_mp4(path)
    track = next(track for track in media.tracks if track.handler == "vide")
    codec = nal_mod.NAL_CODECS[track.codec]
    out: list[tuple[int, bytes]] = []
    for _, offset, size in track.iter_samples():
        sample = mp4_mod.read_at(path, offset, size)
        for nal in nal_mod.split_sample(sample, codec, track.nal_length_size):
            if nal.type in (6, 39, 40):
                out.extend(nal_mod.sei_payloads(nal.raw(sample), nal.type, codec))
    return out


def _audio_bytes(path: Path) -> list[bytes]:
    media = mp4_mod.open_mp4(path)
    track = next(track for track in media.tracks if track.handler == "soun")
    return [mp4_mod.read_at(path, offset, size) for _, offset, size in track.iter_samples()]


def findings_scan(path: Path, needles: list[bytes]) -> dict[bytes, int]:
    from app.domain.assets.scrub.findings import scan_needles

    return scan_needles(path, needles)


def _gate(gates: list, gate_id: str) -> dict:
    """门既可能是 `Gate` 数据类(`check`),也可能是它的字典(`run_all`)。"""
    gate = next(gate for gate in gates if (gate["id"] if isinstance(gate, dict) else gate.id) == gate_id)
    return gate if isinstance(gate, dict) else gate.as_dict()


# ---------------- 十道门:主线 ----------------


def test_a_dirty_video_comes_out_clean_and_every_gate_passes(tmp_path: Path) -> None:
    """主线:一份什么脏东西都有的样本 → 清完十道门全过。"""
    source = _dirty_video(tmp_path / "dirty.mp4")
    target = tmp_path / "clean.mp4"
    outcome = scrub_file(source, target, provenance=False)
    gates = gates_mod.run_all(outcome)
    assert all(gate["ok"] for gate in gates), [gate for gate in gates if not gate["ok"]]
    assert [gate["id"] for gate in gates] == [f"G{i}" for i in range(1, 11)]


def test_the_layers_ffprobe_cannot_see_are_gone_from_the_bytes(tmp_path: Path) -> None:
    """`ffprobe` 看不见的那三层:SEI、AAC 帧内元素、compressorname —— 一律在字节上验。"""
    source = _dirty_video(tmp_path / "dirty.mp4")
    assert any(b"x264 - core" in payload for _, payload in _video_sei(source)), "样本里本来就该有 x264 的 SEI"

    target = tmp_path / "clean.mp4"
    scrub_file(source, target, provenance=False)

    # 一、视频 SEI:一段非空的 user-data 都不许剩
    leftovers = [(kind, payload) for kind, payload in _video_sei(target)
                 if kind == nal_mod.SEI_USER_DATA_UNREGISTERED and any(payload)]
    assert leftovers == []

    # 二、AAC 帧内元素:没有 DSE,也没有写过东西的填充字节
    finding = aac_mod.total([aac_mod.scan(au) for au in _audio_bytes(target)])
    assert (finding.dse_count, finding.dse_zeroed, finding.fil_count) == (0, 0, 0)

    # 三、compressorname:stsd 里那 32 字节全零
    media = mp4_mod.open_mp4(target)
    for track in media.tracks:
        if track.compressorname_at:
            assert mp4_mod.read_at(target, track.compressorname_at, 32) == b"\x00" * 32

    # 四、具体的那几串文本,在整个文件里一次都不该再出现
    hits = findings_scan(target, [
        b"x264 - core", b"Lavc", SECRET_CN.encode(), SECRET_DSE, SECRET_TAG.encode(), SECRET_GPS.encode(),
    ])
    assert hits == {needle: 0 for needle in hits}


def test_picture_and_sound_payloads_are_byte_identical(tmp_path: Path) -> None:
    """最重要的一条:**画面和声音的载荷逐字节等于输入** —— 证明没有重编码。"""
    source = _dirty_video(tmp_path / "dirty.mp4")
    target = tmp_path / "clean.mp4"
    scrub_file(source, target, provenance=False)

    assert _video_vcl(source) == _video_vcl(target), "画面 NAL 变了 = 重编码了"

    before, after = _audio_bytes(source), _audio_bytes(target)
    assert len(before) == len(after)
    assert [len(au) for au in before] == [len(au) for au in after]
    # 音轨只有"帧首那个元素被换成了等长填充",其余字节一模一样。
    for index, (au_a, au_b) in enumerate(zip(before, after)):
        assert len(au_a) == len(au_b), f"第 {index} 个访问单元长度变了"
        # 帧首那一段的**比特数**相同(DSE 换成等长的填充),之后一个比特都没动 ——
        # 所以从帧首之后的第一个字节边界起,两边必须逐字节相同。
        first_b = aac_mod.prefix_elements(au_b)
        head = (first_b[-1].end + 7) // 8 if first_b else 0
        assert au_a[head:] == au_b[head:], f"第 {index} 个访问单元在帧首之后被动过"


def test_decode_result_is_unchanged(tmp_path: Path) -> None:
    """解码之后画面逐帧一致、音轨 PCM 一致 —— 不是"看起来还行",是同一条码流。"""
    from app.domain.assets.scrub.verify import frame_md5, pcm_md5

    source = _dirty_video(tmp_path / "dirty.mp4")
    target = tmp_path / "clean.mp4"
    scrub_file(source, target, provenance=False)
    assert frame_md5(source) == frame_md5(target)
    assert pcm_md5(source) == pcm_md5(target)


# ---------------- 门:留一处脏数据就会红 ----------------


def _clean_pair(tmp_path: Path) -> tuple[Path, Path, object]:
    source = _dirty_video(tmp_path / "dirty.mp4")
    target = tmp_path / "clean.mp4"
    outcome = scrub_file(source, target, provenance=False)
    return source, target, outcome


def test_g3_goes_red_when_one_sei_is_left_behind(tmp_path: Path) -> None:
    """把输入里那条 SEI 原样写回输出的同一个样本(填充 NAL 与它等长)→ G3 必须红。"""
    source, target, outcome = _clean_pair(tmp_path)
    src_media = mp4_mod.open_mp4(source)
    dst_media = mp4_mod.open_mp4(target)
    src_track = next(track for track in src_media.tracks if track.handler == "vide")
    dst_track = next(track for track in dst_media.tracks if track.handler == "vide")
    src_spans, dst_spans = src_track.sample_spans(), dst_track.sample_spans()
    for (off_a, size_a), (off_b, _size_b) in zip(src_spans, dst_spans):
        sample_a = mp4_mod.read_at(source, off_a, size_a)
        codec = nal_mod.NAL_CODECS[src_track.codec]
        for nal in nal_mod.split_sample(sample_a, codec, src_track.nal_length_size):
            if nal.type == 6:
                mp4_mod.write_at(target, off_b + nal.nal_start, nal.raw(sample_a))
                break
        else:
            continue
        break

    gates = gates_mod.check(source, target, provenance=False, edits=outcome.aac_edits)
    assert _gate(gates, "G3")["ok"] is False
    assert _gate(gates, "G3")["detail"]
    # 画面载荷本身没被这处"脏数据"影响 —— 红的是 SEI 那一层,不是画面。
    assert _gate(gates, "G6")["ok"] is True


def test_g4_goes_red_when_compressorname_is_left_behind(tmp_path: Path) -> None:
    source, target, outcome = _clean_pair(tmp_path)
    media = mp4_mod.open_mp4(target)
    track = next(track for track in media.tracks if track.compressorname_at)
    name = SECRET_CN.encode("latin-1")
    mp4_mod.write_at(target, track.compressorname_at, bytes([len(name)]) + name + b"\x00" * (31 - len(name)))
    gates = gates_mod.check(source, target, provenance=False, edits=outcome.aac_edits)
    assert _gate(gates, "G4")["ok"] is False


def test_g5_goes_red_when_the_aac_element_is_left_behind(tmp_path: Path) -> None:
    source, target, outcome = _clean_pair(tmp_path)
    before = _audio_bytes(source)
    media = mp4_mod.open_mp4(target)
    track = next(track for track in media.tracks if track.handler == "soun")
    for au, (_, offset, _size) in zip(before, track.iter_samples()):
        mp4_mod.write_at(target, offset, au)
    # 音轨改回了原样 → 也就不该再有"被清掉的几段"这个说法。
    gates = gates_mod.check(source, target, provenance=False, edits=[])
    assert _gate(gates, "G5")["ok"] is False
    assert _gate(gates, "G7")["ok"] is True  # 声音载荷确实与输入相同,红的只是"没清"


def test_g1_goes_red_when_container_metadata_is_left_behind(tmp_path: Path) -> None:
    """不经我们的重封装、保留标签的另一份产出 → G1 必须红。"""
    source, target, outcome = _clean_pair(tmp_path)
    dirty_target = tmp_path / "kept-tags.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-map", "0:V?", "-map", "0:a?", "-c", "copy",
         str(dirty_target)],
        check=True, capture_output=True, timeout=180,
    )
    gates = gates_mod.check(source, dirty_target, provenance=False, edits=[])
    assert _gate(gates, "G1")["ok"] is False
    assert SECRET_TAG in _gate(gates, "G1")["detail"] or "moov" in _gate(gates, "G1")["detail"]


def test_g6_goes_red_when_the_picture_was_re_encoded(tmp_path: Path) -> None:
    """把画面真的重编码一遍 → G6 必须红(这条门红就意味着"这不是同一幅画")。"""
    source, _target, outcome = _clean_pair(tmp_path)
    reencoded = tmp_path / "reencoded.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-c:v", "libx264", "-preset", "ultrafast",
         "-crf", "30", "-c:a", "copy", str(reencoded)],
        check=True, capture_output=True, timeout=300,
    )
    gates = gates_mod.check(source, reencoded, provenance=False, edits=[])
    assert _gate(gates, "G6")["ok"] is False


# ---------------- AAC 的 DSE ----------------


def test_aac_dse_is_replaced_with_an_equal_length_fill(tmp_path: Path) -> None:
    """`DSE` 换成等长填充元素:元素没了、字节数不变、声音不变。"""
    source = tmp_path / "dse.mp4"
    _encode(source, tags=False, cover=False)
    assert _inject_dse(source) > 0
    before = _audio_bytes(source)
    assert any(aac_mod.scan(au).dse_count for au in before), "样本里本来就该有 DSE"

    target = tmp_path / "clean.mp4"
    outcome = scrub_file(source, target, provenance=False)
    assert outcome.aac_dse_removed > 0
    assert outcome.aac_verified and not outcome.aac_rolled_back

    after = _audio_bytes(target)
    assert [len(au) for au in before] == [len(au) for au in after]
    for au in after:
        finding = aac_mod.scan(au)
        assert (finding.dse_count, finding.dse_zeroed) == (0, 0)
    assert SECRET_DSE not in target.read_bytes()

    from app.domain.assets.scrub.verify import pcm_md5

    assert pcm_md5(source) == pcm_md5(target)


# ---------------- provenance:单独一个开关 ----------------


def test_the_ai_marking_survives_by_default_and_is_removed_when_asked(tmp_path: Path) -> None:
    """默认关:AI 生成标记原样留着;点名打开才清。两件事不许混在一个开关里。"""
    source = _dirty_video(tmp_path / "dirty.mp4")
    kept = tmp_path / "kept.mp4"
    scrub_file(source, kept, provenance=False)
    assert C2PA_UUID in kept.read_bytes(), "默认那一趟不该动 AI 生成标记"
    assert XMP_UUID not in kept.read_bytes(), "XMP 不是 AI 标记,该清"

    removed = tmp_path / "removed.mp4"
    outcome = scrub_file(source, removed, provenance=True)
    assert C2PA_UUID not in removed.read_bytes()
    assert outcome.uuid_preserved == 0
    # 默认那一趟照样清干净自己的隐私
    assert SECRET_TAG.encode() not in removed.read_bytes()


def test_the_switches_stay_separate(tmp_path: Path) -> None:
    """两个开关各管各的:关着时隐私清了、AI 标记留着;开着时两样都清。"""
    source = _dirty_video(tmp_path / "dirty.mp4")
    kept = tmp_path / "kept.mp4"
    scrub_file(source, kept, provenance=False)
    assert C2PA_UUID in kept.read_bytes()
    assert b"Lavc" not in kept.read_bytes() and SECRET_CN.encode() not in kept.read_bytes()


# ---------------- 数据轨 / 容器 ----------------


def test_a_data_track_is_dropped(tmp_path: Path) -> None:
    """GoPro 那样的数据轨(这里按真实排布把音轨改标成 `meta`/`gpmd`)不进输出。"""
    source = tmp_path / "with-data-track.mp4"
    _encode(source, tags=False, cover=False)
    assert _relabel_track_as_data(source)
    before = findings.inspect(source)
    assert [track.handler for track in before.container.data_tracks] == ["meta"]

    target = tmp_path / "clean.mp4"
    outcome = scrub_file(source, target, provenance=False)
    after = findings.inspect(target)
    assert after.container.data_tracks == []
    assert [track.handler for track in after.container.tracks] == ["vide"]
    assert not [gate for gate in gates_mod.run_all(outcome) if not gate["ok"]]


def test_hevc_sei_is_stripped_too(tmp_path: Path) -> None:
    """H.265 走同一条路(前缀 SEI 是 39、后缀是 40)。"""
    if subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
                      ).stdout.find("libx265") < 0:
        pytest.skip("libx265 not available")
    source = tmp_path / "dirty-hevc.mp4"
    _encode(source, codec="libx265", size="192x144", tags=False, cover=False)
    before_sei = _video_sei(source)
    target = tmp_path / "clean.mp4"
    outcome = scrub_file(source, target, provenance=False)
    leftovers = [payload for kind, payload in _video_sei(target)
                 if kind == nal_mod.SEI_USER_DATA_UNREGISTERED and any(payload)]
    assert leftovers == []
    assert _video_vcl(source) == _video_vcl(target)
    assert not [gate for gate in gates_mod.run_all(outcome) if not gate["ok"]]
    _ = before_sei


# ---------------- 流式:不整份读进内存 ----------------


def test_a_large_file_is_never_read_whole(tmp_path: Path) -> None:
    """几分钟的片子:样本按需 seek,单次读取远小于文件本身。"""
    source = tmp_path / "long.mp4"
    _encode(source, seconds=60, size="640x360", rate=30, tags=False, cover=False)
    size = source.stat().st_size
    target = tmp_path / "clean.mp4"
    outcome = scrub_file(source, target, provenance=False)
    assert outcome.max_read < size // 8, f"单次读了 {outcome.max_read} 字节,文件才 {size} 字节"
    assert not [gate for gate in gates_mod.run_all(outcome) if not gate["ok"]]


# ---------------- 碎片化 MP4(moof):门禁比的是规范输入 ----------------

#: 碎片化 MP4 是**真素材的形状**(B 站那些都是),而它的样本表在 `moof` 里、`moov` 的 `stbl`
#: 是空的。修复之前:`open_mp4(源)` 读到 **0 个样本**、输出读得出全部样本,于是 G6(硬门)报
#: `样本数不同:0 vs N`(前端那笔真素材上是 `0 vs 180`)—— 整条清除任务失败、产出丢弃。
#: 这一组钉三件事:①碎片化输入现在跑得通、十道门全绿;②门没被放松(故意重编过的输出照样被
#: G6 抓红);③"规范输入"这条路凭什么是合法的(重封装是 stream copy,VCL 载荷逐字节不变)。


def _fragmented_video(path: Path, *, seconds: int = 1, size: str = "320x240") -> Path:
    _encode(path, seconds=seconds, size=size, tags=True, cover=False, fragmented=True)
    return path


def _annexb_vcl(path: Path) -> list[bytes]:
    """把视频抽成 Annex-B 基本流再切出 VCL NAL —— **碎片化源也能走这条路**。

    `open_mp4` 读不出碎片化输入的样本表,所以想证明"源本身的画面字节 == 规范输入的"时,
    得有另一个入口:ffmpeg 解容器(它会读 `moof`)之后把 NAL 原样倒出来。
    """
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy",
         "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-"],
        check=True, capture_output=True, timeout=300,
    )
    data = proc.stdout
    starts: list[int] = []
    at = data.find(b"\x00\x00\x01")
    while at >= 0:
        starts.append(at + 3)
        at = data.find(b"\x00\x00\x01", at + 3)
    out: list[bytes] = []
    for index, start in enumerate(starts):
        end = (starts[index + 1] - 3) if index + 1 < len(starts) else len(data)
        while end > start and data[end - 1] == 0x00:   # 4 字节起始码多出来的那个 0
            end -= 1
        nal = data[start:end]
        if nal and (nal[0] & 0x1F) in (1, 2, 3, 4, 5):
            out.append(nal)
    return out


def test_碎片化输入跑得通十道门全绿(tmp_path: Path) -> None:
    """**先红后绿的那一条**:修复前 G6 报 `样本数不同:0 vs N`(实测),现在全绿。"""
    source = _fragmented_video(tmp_path / "fragmented.mp4")
    src = mp4_mod.open_mp4(source)
    assert [box.typ for box in src.boxes].count("moof") > 0, "样本本身就该是碎片化的"
    assert src.fragmented is True
    #: 这条钉子就是那个 bug 的根因:源的样本表读出来是 0(样本在 moof 里,open_mp4 只读 moov)。
    assert all(track.sample_count == 0 for track in src.tracks), "碎片化源的样本表本来就该是空的"

    target = tmp_path / "clean.mp4"
    outcome = scrub_file(source, target, provenance=False)
    assert outcome.canonical_baseline is True, "碎片化输入要按规范输入比"
    assert any("碎片化" in note for note in outcome.warnings)

    gates = gates_mod.run_all(outcome)
    assert all(gate["ok"] for gate in gates), [gate for gate in gates if not gate["ok"]]
    assert [gate["id"] for gate in gates] == [f"G{i}" for i in range(1, 11)]
    #: 逐样本的那几道门要能自证比的是哪一份输入(对账文本里"输入 0 个样本"读着像我们的错)。
    for gate_id in ("G6", "G7", "G8", "G9"):
        assert _gate(gates, gate_id)["evidence"]["baseline"] == "canonical", gate_id

    #: 重封装把碎片收成了正片:输出读得出样本,而且容器层的隐私照样清了。
    dst = mp4_mod.open_mp4(target)
    assert next(track for track in dst.tracks if track.handler == "vide").sample_count > 0
    assert SECRET_TAG.encode() not in target.read_bytes()
    #: 引擎的音轨自证也没被容器的编辑列表差异冤枉(修复前它会整体回滚,G5 因此红)。
    assert outcome.aac_verified and not outcome.aac_rolled_back


def test_源与规范输入的画面载荷逐字节相同(tmp_path: Path) -> None:
    """规范基准凭什么能替源:**重封装是 stream copy,VCL 载荷逐字节不变。**

    这是"画面没被重编"那条证明的信任锚 —— 门禁拿规范输入当基准,靠的就是它。
    """
    source = _fragmented_video(tmp_path / "fragmented.mp4")
    with canonical_mod.baseline(source, mp4_mod.open_mp4(source)) as base:
        assert base != source, "碎片化输入应当被归一化"
        raw_vcl = _annexb_vcl(source)
        assert raw_vcl, "这个入口得真读到 NAL,不然下面那句比的是两个空表"
        assert raw_vcl == _video_vcl(base), "重封装改了画面比特 = 这条修法不成立"


def test_故意重编过的输出在碎片化输入上照样被G6抓红(tmp_path: Path) -> None:
    """**门没被放松**:输入是碎片化的,产出被真重编过一遍 → G6 必须红。

    拿规范输入当基准只改"比哪一份字节",不改"比什么" —— 重编过的画面 VCL 与 stream copy
    出来的那份不可能一样。
    """
    source = _fragmented_video(tmp_path / "fragmented.mp4")
    reencoded = tmp_path / "reencoded.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-c:v", "libx264", "-preset", "ultrafast",
         "-crf", "30", "-c:a", "copy", str(reencoded)],
        check=True, capture_output=True, timeout=300,
    )
    gates = gates_mod.check(source, reencoded, provenance=False, edits=[])
    assert _gate(gates, "G6")["ok"] is False
    assert _gate(gates, "G6")["evidence"]["baseline"] == "canonical"


def test_非碎片化输入仍然拿源自己当基准(tmp_path: Path) -> None:
    """既有那条路一个字没动:源读得出样本表就用源自己,不做多余的归一化。"""
    source = _dirty_video(tmp_path / "dirty.mp4")
    outcome = scrub_file(source, tmp_path / "clean.mp4", provenance=False)
    assert outcome.canonical_baseline is False
    assert not any("碎片化" in note for note in outcome.warnings)
    gates = gates_mod.run_all(outcome)
    for gate_id in ("G6", "G7", "G8", "G9"):
        assert _gate(gates, gate_id)["evidence"]["baseline"] == "source", gate_id


# ---------------- HTTP / 任务那一半 ----------------


def _import_video(client, path: Path) -> dict:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    return client.post(
        "/api/assets/import",
        data={"workspace_id": workspace["id"]},
        files={"file": (path.name, path.read_bytes(), "video/mp4")},
    ).json()


def test_the_route_registers_a_derived_asset_and_writes_a_report(tmp_path: Path) -> None:
    """`POST /assets/{id}/scrub` → 一份新素材 + 一份读得回来的对账文本;原素材一个字节不动。"""
    source = _dirty_video(tmp_path / "dirty.mp4")
    client = fresh_client()
    asset = _import_video(client, source)
    original_bytes = (settings.data_dir / asset["file_key"]).read_bytes()

    job = client.post(f"/api/assets/{asset['id']}/scrub", json={"provenance": False}).json()
    assert job["kind"] == "scrub_metadata"
    assert wait_status(client, job["id"]) == "succeeded"

    detail = client.get(f"/api/jobs/{job['id']}").json()
    result = detail["result"]
    assert result["gates_ok"] is True
    assert result["asset_id"] and result["asset_id"] != asset["id"]
    assert "清除元数据 · 对账" in result["report"]
    assert "门禁" in result["report"]

    made = client.get(f"/api/assets/{result['asset_id']}").json()
    assert made["name"].endswith("已清除元数据")
    clean_bytes = (settings.data_dir / made["file_key"]).read_bytes()
    assert SECRET_TAG.encode() not in clean_bytes
    assert C2PA_UUID in clean_bytes  # 默认开关关:AI 生成标记保留

    # 原素材一个字节不动
    assert (settings.data_dir / asset["file_key"]).read_bytes() == original_bytes

    # 对账文本读得回来,而且没清过的素材是 status=none 而不是 404
    assert client.get(f"/api/assets/{asset['id']}/scrub-report").json()["status"] == "ready"
    other = _import_video(client, _encode(tmp_path / "plain.mp4") or tmp_path / "plain.mp4")
    assert client.get(f"/api/assets/{other['id']}/scrub-report").json()["status"] == "none"


def test_a_non_video_asset_is_refused(tmp_path: Path) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": workspace["id"]},
        files={"file": ("note.txt", b"hello there", "text/plain")},
    ).json()
    assert asset["kind"] == "document"
    response = client.post(f"/api/assets/{asset['id']}/scrub", json={"provenance": False})
    assert response.status_code == 422
    assert "视频" in response.json()["detail"]


# ---------------- 工作流节点 ----------------


def test_the_node_runs_and_returns_the_report(tmp_path: Path) -> None:
    """`scrub_metadata` 节点:素材进,干净素材 + 对账文本 + 门禁结果出。"""
    from app.db.models import Asset
    from app.core.db import SessionLocal
    from app.domain.workflows.executors.registry import get_executor

    source = _dirty_video(tmp_path / "dirty.mp4")
    client = fresh_client()
    asset = _import_video(client, source)

    class Scope:
        workspace_id = asset["workspace_id"]
        id = "run-1"
        name = "test"

    with SessionLocal() as db:
        handler = get_executor("scrub_metadata")
        out = handler(db, Scope(), {"asset_id": asset["id"], "provenance": "no"})
    assert out["asset_id"] and out["asset_id"] != asset["id"]
    assert out["gates_ok"] is True
    assert out["removed"]["sei_payloads"] >= 1
    assert "清除元数据 · 对账" in out["report"]
    with SessionLocal() as db:
        made = db.get(Asset, out["asset_id"])
        assert made is not None and made.derived_from[0]["op"] == "scrub"
        assert made.derived_from[0]["asset_id"] == asset["id"]
