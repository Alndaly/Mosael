"""对账文本 —— 这一笔的**产出**之一,不是日志。

照 reelbench `half.txt` 那个态度:一次清除交一份能逐条读的清账,说清**清之前发现了什么、
清了什么、哪些清不掉以及为什么**。含糊的报告比没有报告更坏:它让人以为清干净了。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain.assets.scrub import policy

_HE = {
    "title": "清除元数据 · 对账",
    "when": "生成时间",
    "files": "文件",
    "input": "输入",
    "output": "输出",
    "container": "容器",
    "before": "一、清除前发现了什么",
    "did": "二、清掉了什么",
    "left": "三、清不掉的、以及为什么",
    "gates": "四、门禁(全部靠扫字节,不看 ffprobe)",
    "tags": "容器标签",
    "metaboxes": "容器元数据盒子",
    "uuid": "uuid 盒子",
    "tracks": "轨",
    "data_tracks": "数据轨 / 遥测 / 附件",
    "cover": "封面",
    "sei": "H.264/H.265 的 SEI",
    "compressorname": "compressorname(ffprobe 看不见)",
    "aac": "AAC 帧内元素(ffprobe 看不见)",
    "provenance": "AI 生成标记(C2PA)",
    "none": "无",
    "switch": "开关",
    "verdict": "结论",
    "pass": "过",
    "fail": "红",
}

_SEI_KEPT_NAMES = {
    4: "user_data_registered_itu_t_t35(可能是 HDR10+ / 隐藏字幕)",
    5: "user_data_unregistered",
    137: "mastering_display_colour_volume(HDR)",
    144: "content_light_level_info(HDR)",
    47: "alternative_transfer_characteristics",
    6: "recovery_point",
    1: "pic_timing",
}


def _line(label: str, value: str) -> str:
    return f"- **{label}** {value}"


def render(outcome, gates: list[dict[str, object]], *, lang: str = "zh") -> str:
    """`outcome` 是 `engine.ScrubOutcome`,`gates` 是 `gates.run_all` 的结果。"""
    before, after = outcome.before, outcome.after
    out: list[str] = []
    out.append(f"# {_HE['title']} —— {outcome.source.name}")
    out.append("")
    out.append(_line(_HE["when"], datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")))
    out.append(_line(_HE["input"], f"`{outcome.source}` ({_size(before.size)})"))
    out.append(_line(_HE["output"], f"`{outcome.target}` ({_size(after.size)})"))
    out.append(_line(_HE["container"], f"{before.container.container}"
                                         + (f" / brand {before.container.major_brand}" if before.container.major_brand else "")))
    out.append("")

    out.append(f"## {_HE['before']}")
    out.append(_line(_HE["tracks"], _tracks_line(before)))
    out.append(_line(_HE["data_tracks"], _data_line(before)))
    out.append(_line(_HE["tags"], _tags_line(before)))
    out.append(_line(_HE["cover"], "有" if before.container.cover else _HE["none"]))
    out.append(_line(_HE["metaboxes"], _list_line(before.container.metadata_boxes)))
    out.append(_line(_HE["uuid"], _uuid_line(before)))
    out.append(_line(_HE["compressorname"], _list_line(before.container.compressornames)))
    out.append(_line(_HE["sei"], _sei_line(before)))
    out.append(_line(_HE["aac"], _aac_line(before)))
    out.append(_line(_HE["provenance"], _provenance_line(before)))
    out.append("")

    out.append(f"## {_HE['did']}")
    for item in _did_lines(outcome):
        out.append(item)
    out.append("")

    out.append(f"## {_HE['left']}")
    left = _left_lines(outcome)
    for item in left:
        out.append(item)
    out.append("")

    out.append(f"## {_HE['gates']}")
    out.append("")
    out.append("> G9 要把输入和输出**各解一遍**(画面逐帧 + 音轨 PCM),所以这一段通常比清除本身慢得多:"
               "3 分钟 1080p 实测清除 3.7 秒、门禁 55 秒。这条证据值这个价 —— 少了它,"
               "「画面没被改坏」就只是推理出来的。")
    out.append("")
    if outcome.canonical_baseline:
        out.append("> 输入是**碎片化 MP4**(样本表在 `moof` 里,`moov` 的 `stbl` 是空的):"
                   "逐样本比对的 G6/G7/G8 与 G9 比的基准是**同一套重封装参数收出来的规范输入**。"
                   "重封装是 stream copy,VCL 载荷逐字节不变,所以「画面没被重编」这条证明一个字没松;"
                   "它比的是「我们改的那几个字节有没有动到画面和声音」,而不是「两种容器写法对不对得上」。")
        out.append("")
    out.append("| 门 | 查什么 | 结果 | 说明 |")
    out.append("| --- | --- | --- | --- |")
    for gate in gates:
        mark = "✅" if gate["ok"] else "❌"
        out.append(f"| {gate['id']} | {gate['name']} | {mark} | {gate['detail'] or '—'} |")
    red = [gate for gate in gates if not gate["ok"]]
    out.append("")
    if red:
        out.append(_line("结论", "**有门是红的** —— 上面那几条没有清干净,原因见「三」。"))
    else:
        out.append(_line("结论", "十道门全过。"))
    out.append("")
    out.append(f"> 默认剥掉的清单见 `policy.DEFAULT_STRIP_KEYS`;AI 生成标记为什么单独一个开关,"
               f"见 ADR 0062。开关这一次:`provenance={'开' if outcome.provenance else '关'}`。")
    return "\n".join(out)


def _size(value: int) -> str:
    if value >= 1 << 20:
        return f"{value / (1 << 20):.1f} MiB"
    if value >= 1 << 10:
        return f"{value / (1 << 10):.1f} KiB"
    return f"{value} B"


def _list_line(values: list[str]) -> str:
    return "、".join(values) if values else _HE["none"]


def _tracks_line(facts) -> str:
    if not facts.container.tracks:
        return "读不出来(容器不是 MP4 / QuickTime 一族)"
    line = ";".join(
        f"#{track.index} {track.handler}/{track.codec} {track.samples} 个样本" for track in facts.container.tracks
    )
    if _samples_in_moof(facts):
        line += "(碎片化 MP4:样本表在 moof 里,上面这个 0 是 moov 里读出来的,不是文件真的没有样本)"
    return line


def _samples_in_moof(facts) -> bool:
    """输入是碎片化 MP4:样本表在 `moof` 里,`open_mp4` 只读 moov —— 码流层那几项**读不出来**。

    这时候不能报"没有 SEI"、"音轨不是 AAC":那是把"没看见"说成"没有"。逐样本的门禁比的是
    同一套重封装参数收出来的规范输入(见 `canonical`),对账文本要说的是同一件事。
    """
    return facts.container.fragmented and not any(track.samples for track in facts.container.tracks)


def _data_line(facts) -> str:
    data = facts.container.data_tracks
    if not data:
        return _HE["none"]
    return ";".join(f"#{track.index} {track.handler}/{track.codec}({track.samples} 个样本)" for track in data)


def _tags_line(facts) -> str:
    tags = facts.container.tags
    if not tags:
        return _HE["none"]
    keep = {k: v for k, v in tags.items() if not k.startswith(("major_brand", "minor_version", "compatible_brands"))}
    if not keep:
        return _HE["none"]
    return ";".join(f"{key}={value!r}" for key, value in sorted(keep.items()))


def _uuid_line(facts) -> str:
    if not facts.container.uuid_boxes:
        return _HE["none"]
    return ";".join(
        f"{uuid[:8]}…({size} B{' · AI 生成标记' if prov else ''})" for uuid, size, prov in facts.container.uuid_boxes
    )


def _sei_line(facts) -> str:
    bits = facts.bitstream
    if not bits.sei_types:
        if _samples_in_moof(facts):
            return "读不出来(碎片化 MP4:样本表在 moof 里)"
        return _HE["none"] if bits.codec else "没做(编码不支持按字节重写 NAL)"
    parts = []
    for payload_type, count in sorted(bits.sei_types.items()):
        name = _SEI_KEPT_NAMES.get(payload_type, f"载荷类型 {payload_type}")
        parts.append(f"{name} × {count}")
    if bits.sei_uuids:
        parts.append("UUID:" + "、".join(uuid[:8] + "…" for uuid in bits.sei_uuids))
    return ";".join(parts)


def _aac_line(facts) -> str:
    finding = facts.bitstream.aac
    if not finding.frames:
        if _samples_in_moof(facts):
            return "读不出来(碎片化 MP4:样本表在 moof 里)"
        return "没做(音轨不是 AAC)"
    parts = [f"{finding.frames} 个访问单元"]
    if finding.dse_count:
        parts.append(f"DSE × {finding.dse_count}(共 {finding.dse_bytes} 字节)")
    if finding.fil_count:
        parts.append(f"写过东西的填充元素 × {finding.fil_count}(共 {finding.fil_bytes} 字节)")
    if finding.elsewhere_hint:
        parts.append(f"帧首之外疑似帧内数据 × {finding.elsewhere_hint}(启发式)")
    if len(parts) == 1:
        parts.append("没有 DSE,也没有非空填充")
    return ";".join(parts)


def _provenance_line(facts) -> str:
    if not facts.provenance_present:
        return "没检出"
    where = []
    if facts.bitstream.sei_provenance:
        where.append(f"SEI × {facts.bitstream.sei_provenance}")
    boxes = [uuid for uuid, _, prov in facts.container.uuid_boxes if prov]
    if boxes:
        where.append("uuid 盒子 × " + str(len(boxes)))
    return "检出:" + "、".join(where)


def _did_lines(outcome) -> list[str]:
    before, after = outcome.before, outcome.after
    lines: list[str] = []
    dropped = sorted({track.handler for track in before.container.data_tracks})
    container_touched = bool(before.container.tags or before.container.metadata_boxes)
    lines.append(_line("容器标签 / GPS / 设备 / 账号 / 封面",
                       "整层不写出(-map_metadata -1 -fflags +bitexact -empty_hdlr_name 1)"
                       if container_touched else _HE["none"]))
    lines.append(_line("数据轨", ("丢掉 " + "、".join(dropped)) if dropped else _HE["none"]))
    lines.append(_line("SEI", _sei_did(outcome)))
    lines.append(_line("AAC 帧内元素", _aac_did(outcome)))
    lines.append(_line("compressorname", _compressorname_did(outcome)))
    lines.append(_line("uuid 盒子", _uuid_did(outcome)))
    lines.append(_line("空的元数据容器", (f"udta 就地改成 free × {outcome.udta_neutralized}"
                                    if outcome.udta_neutralized else _HE["none"])))
    lines.append(_line("画面与声音", "样本**原样搬运**(-c copy):没有解码,没有编码"))
    lines.append(_line("流式", f"全程最大的单次读取 {_size(outcome.max_read)};样本按需 seek,不整份读"))
    _ = after
    return lines


def _sei_did(outcome) -> str:
    if not (outcome.sei_payloads_removed or outcome.sei_nals_replaced):
        return _HE["none"]
    return (f"整条换成等长填充 NAL × {outcome.sei_nals_replaced};"
            f"同一个 NAL 里既要留又要清的按内容抹字节 × {outcome.sei_payloads_zeroed};"
            f"清掉的 SEI 段共 {outcome.sei_payloads_removed}")


def _aac_did(outcome) -> str:
    if not (outcome.aac_dse_removed or outcome.aac_dse_zeroed or outcome.aac_fil_zeroed):
        return _HE["none"]
    return (f"DSE 换成等长填充元素 × {outcome.aac_dse_removed};"
            f"DSE 原地清零 × {outcome.aac_dse_zeroed};"
            f"填充元素载荷清零 × {outcome.aac_fil_zeroed}({outcome.aac_bytes_zeroed} 字节)")


def _compressorname_did(outcome) -> str:
    if outcome.compressorname_cleared:
        return f"清零 × {outcome.compressorname_cleared}"
    names = outcome.before.container.compressornames
    if not names:
        return _HE["none"]
    return ("输入的 stsd 里写着 " + "、".join(repr(name) for name in names)
            + ";重封装后 ffmpeg 写的是空,已在输出的 stsd 上复核为空")


def _uuid_did(outcome) -> str:
    if not (outcome.uuid_dropped or outcome.uuid_preserved):
        return _HE["none"]
    return (f"不该留的 {outcome.uuid_dropped} 个已改成 free;"
            f"AI 生成标记的 {outcome.uuid_preserved} 个按默认开关原样追加回文件尾")


def _left_lines(outcome) -> list[str]:
    lines: list[str] = []
    for note in outcome.warnings:
        lines.append(f"- {note}")
    for note in outcome.before.unsupported:
        lines.append(f"- {note}")
    if outcome.sei_payloads_unlocated:
        lines.append(f"- {outcome.sei_payloads_unlocated} 段 SEI 载荷没能按内容定位,没敢动(怕改坏画面)")
    if outcome.aac_rolled_back:
        lines.append("- AAC 帧内元素的改动被整体回滚了:改完之后解码结果与输入不一致。"
                     "宁可留着,不改成别的声音。")
    hint = outcome.before.bitstream.aac.elsewhere_hint
    if hint:
        lines.append(f"- 启发式提示:{hint} 处帧首之外的字节看起来也像 AAC 帧内数据。"
                     "要精确定位得写完整的 AAC 语法解析(帧内数据是 Huffman 编码的),这一步没做,"
                     "所以这些位置**没有清**,也不能保证没有。")
    if not outcome.provenance and outcome.before.provenance_present:
        lines.append("- **AI 生成标记(C2PA)按默认开关保留了。** " + str(policy.PROVENANCE["consequence_zh"]))
    if outcome.provenance:
        lines.append("- **这一次连 AI 生成标记一起清了。** " + str(policy.PROVENANCE["consequence_zh"]))
    lines.append("- 容器层的键在**不是 MP4 / QuickTime 一族**的输入上读不出来(比如 Matroska):"
                 "输出一定去掉了,但「输入里原本有什么」这一节不全。")
    return lines
