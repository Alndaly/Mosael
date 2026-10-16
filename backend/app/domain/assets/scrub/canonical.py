"""**规范基准**:门禁逐样本比对时当"输入"的那一份 MP4,以及唯一的一套重封装参数。

## 为什么需要它

碎片化 MP4(顶层有 `moof`)把样本表放在 `moof` 的 `traf/trun` 里,`moov` 的 `stbl` 是空的
(`empty_moov`)。`mp4.open_mp4` 只读 moov,于是对碎片化输入**读到 0 个样本**;而输出是重封装
之后的正片,读得出 180 个。逐样本比对的 G6(逐样本比 VCL NAL)与 G8(样本数 / 长度 / 时间基)
于是必然红:

    样本数不同:0 vs 180

G6 是硬门 —— 一红整条清除任务失败、产出丢弃。维护者库里的 B 站视频大量是碎片化的,所以这条
能力对多数真素材 **100% 失败**。ADR 0062 §6 写的是"碎片化输入由重封装收成正片",**门禁这一层
当时没算进去**。

## 做法

把源按**输出那一趟同一套重封装参数**收成一份规范 MP4(`remux` —— `engine` 的重封装用的就是
它,参数只有这一份),再拿它的样本表与 VCL 字节和输出逐样本比。重封装是 `-c copy`:**VCL 载荷
逐字节不变**,于是"画面没被重编"这条证明依然成立(测试
`test_源与规范输入的画面载荷逐字节相同` 钉着),而样本表两边都读得出来。

**这不是放松门。** 十道门的条数与含义一个字没改,改的只是"拿哪一份字节当基准":

- G6 仍然逐样本比 VCL NAL 的字节;
- G8 仍然要求样本数 / 每个样本长度 / 时间基逐项相同;
- 一段**故意重编过**的输出照样被 G6 抓红(测试
  `test_故意重编过的输出在碎片化输入上照样被G6抓红`)。

## 音轨那一半

碎片化输入的 `moov` 里**没有 `edts/elst`**,而重封装出来的正片有 —— 两种容器写法解码出来的
PCM **天生差几百个采样**(实测:10 秒的单声道 AAC 差 344 个)。所以:

- 引擎的音轨自证(`engine._verify_audio`)在碎片化输入上不能拿源当基准,否则每一次 AAC 帧内
  元素的清理都会被误判成"改坏了声音"而整体回滚(G5 因此红);
- G9 的"解码后一致"同理。

这两处也用规范基准:比的才是"我们改的那几个字节有没有动到声音",而不是"两种容器写法对不对得上"。
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.domain.assets.scrub import findings as findings_mod
from app.domain.assets.scrub import mp4 as mp4_mod
from app.domain.assets.scrub.verify import run_ffmpeg
from app.media.scratch import scratch_dir

#: 归一化出来的那份规范 MP4 落在哪个暂存目录下(`media.scratch`)。用完就整个删掉;
#: 进程中途没了的,下次启动由 `clear_scratch` 收。
PURPOSE = "scrub-canonical"


def remux(source: Path, target: Path) -> None:
    """无损重封装到干净的 MP4:只搬画面和声音,不搬任何标签和其余轨。

    **这是唯一一份重封装参数表。** 输出那一趟(`engine`)和规范基准(`baseline`)都用它 ——
    两边必须是同一个 muxer、同一组 flags,否则样本表对不上,门禁会红得莫名其妙。
    """
    codec = ""
    try:
        facts = findings_mod.read_container(source)
        codec = facts.tracks[0].codec if facts.tracks else ""
    except Exception:  # pragma: no cover - 探不出就让 ffmpeg 自己认
        codec = ""
    tag = ["-tag:v", "hvc1"] if codec in ("hvc1", "hev1") else []
    run_ffmpeg([
        "-y", "-v", "error",
        "-i", str(source),
        #: 大写 `V` **不含** attached_pic(封面图那条视频轨);`a?` 里的 `?` 是"没有也别报错"。
        "-map", "0:V?", "-map", "0:a?",
        "-c", "copy",
        "-map_metadata", "-1", "-map_chapters", "-1",
        #: 没有这两句,muxer 会自己写 `encoder=Lavf63.1.102`(实测)。
        "-fflags", "+bitexact", "-flags", "+bitexact",
        #: `hdlr` 里默认写 "VideoHandler";摄像机会在这儿留机型,空着最省事。
        "-empty_hdlr_name", "1",
        "-movflags", "+faststart",
        *tag,
        str(target),
    ], what="清除元数据:重封装")


def needs_baseline(media: mp4_mod.Mp4File | None) -> bool:
    """源能不能**直接**当逐样本比对的基准。

    不能的两种情形:

    - 顶层有 `moof`(或者 `mvex`):样本在碎片里,`moov` 的 `stbl` 要么是空的、要么只是开头一段;
    - 画面 / 声音轨的样本表读出来是空的 —— 读不出样本就谈不上"样本数与输入相同"。
    """
    if media is None:
        return False
    if media.fragmented:
        return True
    return any(track.sample_count == 0 for track in media.tracks if track.handler in ("vide", "soun"))


@contextmanager
def baseline(source: Path, media: mp4_mod.Mp4File | None) -> Iterator[Path]:
    """产出"当输入的那一份":读得出来就是源自己,读不出来就先收一份规范输入。

    `media` 是调用方已经打开的那一份(`None` = 不是认得的 MP4:`open_mp4` 读不开的东西谈不上
    逐样本比对,原样交给 G9 的去解码兜底)。中间的规范 MP4 在这段 `with` 里有效,出去(包括
    中途抛错)整个删掉。**只重封装,不改源。**
    """
    source = Path(source)
    if not needs_baseline(media):
        yield source
        return
    holder = scratch_dir(PURPOSE)
    try:
        normalized = holder / (source.stem + ".canonical.mp4")
        remux(source, normalized)
        yield normalized
    finally:
        shutil.rmtree(holder, ignore_errors=True)


__all__ = ["PURPOSE", "baseline", "needs_baseline", "remux"]
