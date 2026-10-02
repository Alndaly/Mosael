"""一份素材能不能放上一条轨、放上去出点到哪 —— 放片段的唯一一套规矩。

单独一个叶子模块:剪辑页的插入(placement)、工作流的「接到时间线」、画板的连线(append)都要它,
而 append 回头要用 operations —— 规矩放在 append 里,placement 一引就成了环。(修剪夹到素材末尾和组员
同一套,在 placement.trim_clip 里。)
"""

from __future__ import annotations

from app.db.models import Asset, Track
from app.domain.sequences._timeline import too_short
from app.domain.sequences.errors import SequenceDomainError

#: 素材种类 → 该进哪种轨道。没列的(图片)按视频走 —— 图片在时间线上就是一段定格视频。
TRACK_FOR_ASSET = {"audio": "audio"}


def fit_asset_on_track(asset: Asset, track: Track, src_in: float, src_out: float) -> float:
    """这份素材的 [src_in, src_out) 能不能放上这条轨 —— 能就交回**实际的出点**。

    **放片段的唯一一套规矩。** 剪辑页的插入(placement.insert_clip)、工作流的「接到时间线」、画板的连线
    都过它;此前只有工作流那一份查了,剪辑页和智能体的插入两样都不查:

    · 轨道要对得上素材(TRACK_FOR_ASSET):视频 / 图片进视频轨,音频进音频轨,字幕轨不收素材。放错了的
      片段渲染时没有一条路径会读它 —— 视频进了音频轨就只剩声音、画面静默地没了。
    · 出点夹到素材末尾:超出去的那一截渲染时没有画面也没有声音,是一段空白。入点已经在末尾之后就
      整段都是空白,拒。图片没有「末尾」,定格多久由调用方说了算。
    """
    want = TRACK_FOR_ASSET.get(asset.kind, "video")
    if track.kind != want:
        raise SequenceDomainError("seqErr_trackKindMismatch", want=want, kind=track.kind)
    return clamp_to_source(asset, src_in, src_out)


def clamp_to_source(asset: Asset, src_in: float, src_out: float) -> float:
    """出点夹到素材末尾;入点已经在末尾之后就拒。没有时长的素材(图片)原样交回。"""
    probed = (asset.media_info or {}).get("duration")
    if asset.kind not in ("video", "audio") or not probed:
        return src_out
    end = float(probed)
    # 夹完还得够一个片段长(和切分、覆盖的最小余量同一个口径):入点离末尾不到那么点,夹出来的是一片碎屑。
    if too_short(end - src_in):
        raise SequenceDomainError("seqErr_clipStartsPastAssetEnd", src_in=round(src_in, 3), duration=round(end, 3))
    return min(src_out, end)
