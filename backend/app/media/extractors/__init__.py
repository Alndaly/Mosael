"""自定义站点适配器:交给 yt-dlp 的 InfoExtractor 子类。

**为什么要有这一份集合。** 站点适配器最终要回答的是「这个 URL 归谁解析」。yt-dlp 自己的注册表
是它的一份快照,而我们的适配器不在里面 —— 所以「工厂」和「URL 支持判定」都得从同一份集合出发,
而且**两边顺序相同**:工厂里排在前面的 extractor,就是 `matching_extractor` 里先被问到的那个。
顺序一旦分叉,`/api/assets/url-support` 说的支持与真正下载时走到的解析器就会不是同一家。

`CUSTOM_EXTRACTORS` 的顺序就是被问的顺序,**自定义排在 yt-dlp 默认之前**(见 `media/ytdlp`):
同一个站点两边都认时,我们自己的适配器先拿到它。

**只登记能真的解析出媒体地址的适配器。** MissAV 的页面解析已经写完(见 `missav.py`),所以它在这里;
骨架阶段(只认领、没有解析)的适配器仍不登记 —— 那会让 `/url-support` 说「支持」而导入只能报
「还没支持这个站」。`SiteAdapterPending` 因此保留:别的适配器以后还会先认领、后写解析。
"""
from __future__ import annotations

from typing import Any

from app.media.extractors.missav import MissAVIE

#: 自定义 extractor 类,**顺序 = 被问的顺序**。工厂与 `matching_extractor` 都读这一份。
CUSTOM_EXTRACTORS: tuple[type[Any], ...] = (MissAVIE,)

__all__ = [
    "CUSTOM_EXTRACTORS",
]
