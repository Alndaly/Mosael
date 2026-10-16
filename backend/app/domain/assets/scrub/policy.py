"""清除元数据的**政策**:默认剥什么、provenance 为什么另一个开关、支持到哪一步。

这张表是这一笔的"拍板结果",别处(引擎、门禁、对账文本、节点文案、ADR 0062)都从这里读,
免得四份说法各自漂移。领域之外的人问"到底去掉了什么",答案就是 `DEFAULT_STRIP`。

**默认剥的只有"你的隐私"**:拍摄地点、设备、软件、账号/ID、封面、以及数据轨(遥测 / 时间码)。
**AI 生成标记(C2PA)不在里面** —— 那是"这段是生成的"的声明,不是你的隐私,属于另一件事,
见 `PROVENANCE`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 默认剥掉的容器键(对账文本按这几类点名)。名单取的是**实际会出现的**那批:
#: QuickTime/iTunes 的 `©xxx`、3GPP 的 `loci`、Windows 的 `Xtra`、Matroska 的自由标签。
DEFAULT_STRIP_KEYS: dict[str, tuple[str, ...]] = {
    # 「拍摄地点」—— 维护者的原话第一条。
    "gps": (
        "location", "location-eng", "©xyz", "loci", "com.apple.quicktime.location.ISO6709",
        "com.apple.quicktime.location.accuracy.horizontal", "com.apple.quicktime.location.body",
        "com.apple.quicktime.location.date", "com.apple.quicktime.location.name",
        "GPS", "GPSLatitude", "GPSLongitude", "GPSAltitude", "GPSPosition",
    ),
    # 「设备、软件」—— 相机/手机型号、固件、录制 App、编码器版本。
    "device": (
        "make", "model", "©mak", "©mod", "©swr", "com.apple.quicktime.make",
        "com.apple.quicktime.model", "com.apple.quicktime.software", "com.apple.quicktime.creationdate",
        "encoder", "©too", "Lavf", "Lavc", "libx264", "x264", "GoPro", "handler_name",
        "ENCODER", "ENCODER_SETTINGS", "WritingApp", "com.android.version",
    ),
    # 「账号 / ID」—— 作者、版权人、序列号、内容凭据。
    "account": (
        "artist", "©ART", "©aut", "©cpy", "author", "com.apple.quicktime.author",
        "comment", "©cmt", "description", "©des", "desc", "©grp", "album_artist",
        "title", "©nam", "album", "©alb", "genre", "©gen", "date", "©day",
        "copyright", "cprt", "performer", "©prf", "serial", "serial_number",
        "com.apple.iTunes", "iTunSMPB", "iTunes", "ID3",
    ),
    # 「封面」—— 附带的图像轨 / `covr` 盒子:和画面本身无关,却常常带着别人看不到的东西。
    "cover": ("covr", "attached_pic", "cover", "coverart", "cover_art"),
}

#: 默认**不剥**的:它们在容器里,但属于播放/渲染必需的技术信息,不是隐私。
KEPT_KEYS: tuple[str, ...] = ("major_brand", "minor_version", "compatible_brands", "creation_time", "duration")

#: 默认剥掉的**轨**种类(handler)。只留 `vide` / `soun`。
#: GoPro 的 GPMF(`gpmd`)、时间码(`tmcd`)、3GPP 定时元数据(`meta`)、字幕、附件全在这里。
DATA_TRACK_HANDLERS: tuple[str, ...] = ("meta", "tmcd", "text", "sbtl", "subt", "clcp", "camm", "mett", "urim", "hint", "auxv")

#: 默认剥掉的**码流层**元素。`ffprobe` 一个都看不见 —— 这是这一笔真正的价值。
BITSTREAM_STRIP: tuple[str, ...] = (
    "h264_sei_user_data_unregistered",   # x264 命令行、Lavf/Lavc 版本、固件串、序列号
    "h265_sei_user_data_unregistered",
    "aac_data_stream_element",           # 设备把账号/序列号塞这儿
    "aac_fill_element_payload",          # ffmpeg 自己的 AAC 编码器版本串实测就在这儿
    "compressorname",                    # stsd/VisualSampleEntry:ffmpeg 会写 "Lavc… libx264"
)

#: 默认**保留**的 SEI:它们是画面的一部分,不是元数据。
KEPT_SEI: dict[int, str] = {
    4: "user_data_registered_itu_t_t35(HDR10+ / 隐藏字幕)",
    1: "pic_timing",
    137: "mastering_display_colour_volume(HDR)",
    144: "content_light_level_info(HDR)",
    47: "alternative_transfer_characteristics(HDR)",
    6: "recovery_point",
    45: "frame_packing_arrangement",
}

PROVENANCE: dict[str, object] = {
    #: 开关的默认值:**关** —— 即"不清 AI 生成标记"。默认那一趟只动你的隐私。
    "default": False,
    #: 认这几处:顶层/`moov` 里的 `uuid` 盒子(C2PA 的 JUMBF 清单)与视频 SEI 里的同名 UUID。
    "where": ("mp4:uuid-box", "h264:sei-user-data-unregistered", "h265:sei-user-data-unregistered"),
    #: 打开之后会发生什么 —— 这一段会被拼进节点文案和对账文本,**后果必须写在用户看得见的地方**。
    "consequence_zh": (
        "打开会把 AI 生成标记(C2PA 清单)一并抹掉,输出看起来和一段从未被 AI 碰过的素材一样。"
        "那不是「去掉你的隐私」,是**抹掉「这段是 AI 生成的」这个声明** —— 在要求标注 AI 生成的"
        "平台或地区,这可能让发布违规。关掉时这些标记原样保留。"
    ),
    "consequence_en": (
        "On, this also erases the AI-generation marking (the C2PA manifest), so the file looks like "
        "footage no AI ever touched. That is not removing your own privacy: it is removing the "
        "statement that this was AI-generated, which can break the rules of platforms or regions "
        "that require that disclosure. Off, the marking is preserved as-is."
    ),
}

#: 编解码支持矩阵 —— **实测**(见 `tests/test_media_scrub.py`),不是照抄文档。
CODEC_SUPPORT: dict[str, str] = {
    "h264": "full",     # 容器层 + SEI 层 + AAC 层
    "hevc": "full",
    "av1": "container",  # 容器层照做;OBU 里的 metadata 不做,报告里点名
    "vp9": "container",
    "vp8": "container",
    "mpeg4": "container",
    "prores": "container",
}
#: 输入容器:任意 ffmpeg 读得动的都收,**输出一律 MP4**(见 ADR 0062 §支持的容器)。
OUTPUT_CONTAINER = "mp4"
#: 拒收的条件。
REFUSE = {
    "encrypted": "采样描述是加密入口(encv/enca):载荷读不出画面,谈不上「画面逐字节相同」",
    "no_video": "没有视频轨:这一笔只处理视频素材",
}


@dataclass
class StripPlan:
    """这一次要做什么。引擎照着它走,对账文本照着它说。"""

    provenance: bool = bool(PROVENANCE["default"])
    #: 这份素材的编码(ffprobe 给的 `codec_name`)。
    codec: str = ""
    #: 码流层能不能做 —— 只有 H.264 / H.265 能按字节重写 NAL。
    bitstream: bool = False
    #: 数据轨剥不剥(永远剥,列在这儿是为了报告能逐条说)。
    drop_data_tracks: bool = True
    #: 走不下去的原因(有值就直接拒,不产出半成品)。
    refuse: str = ""
    notes: list[str] = field(default_factory=list)

    @classmethod
    def for_codec(cls, codec: str, *, provenance: bool = False) -> "StripPlan":
        return cls(provenance=provenance, codec=codec, bitstream=codec in ("h264", "hevc"))


def default_strip_list() -> dict[str, tuple[str, ...]]:
    """给文档/界面用:默认剥掉的确切清单(按类别)。"""
    return dict(DEFAULT_STRIP_KEYS)
