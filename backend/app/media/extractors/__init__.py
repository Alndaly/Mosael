"""自定义站点适配器:交给 yt-dlp 的 InfoExtractor 子类。

**为什么要有这一份集合。** 站点适配器最终要回答的是「这个 URL 归谁解析」。yt-dlp 自己的注册表
是它的一份快照,而我们的适配器不在里面 —— 所以「工厂」和「URL 支持判定」都得从同一份集合出发,
而且**两边顺序相同**:工厂里排在前面的 extractor,就是 `matching_extractor` 里先被问到的那个。
顺序一旦分叉,`/api/assets/url-support` 说的支持与真正下载时走到的解析器就会不是同一家。

`CUSTOM_EXTRACTORS` 的顺序就是被问的顺序,**自定义排在 yt-dlp 默认之前**(见 `media/ytdlp`):
同一个站点两边都认时,我们自己的适配器先拿到它。

**现在这一份是空的。** MissAV 的骨架在 `missav.py`,但它的页面解析还没有接入 —— 在解析能真的
给出媒体地址之前把它登记进来,只会让 `/api/assets/url-support` 说「支持」、而导入只能报
「还没支持这个站」。等第二阶段把解析写完,再把它加进这里(一行)。
"""
from __future__ import annotations

from typing import Any

#: 自定义 extractor 类,**顺序 = 被问的顺序**。工厂与 `matching_extractor` 都读这一份。
#:
#: 这里只放**能真的解析出媒体地址**的适配器。还在骨架阶段的(只有认领、没有解析)不进这里 ——
#: 认领与拒绝的逻辑可以直接测,不必先让它接管真实导入。
CUSTOM_EXTRACTORS: tuple[type[Any], ...] = ()


class SiteAdapterPending(RuntimeError):
    """站点认领了,但页面解析还没接入。

    适配器层只表达「哪一步没做」,**不 import `media/ytdlp`** —— 那会把 `extractors` 和
    `ytdlp` 卷进包级循环依赖(见 `tests/test_import_layering.py`)。翻成给用户看的那句话
    在 `ytdlp.classify`:它把这里带上来的站点名变成一个带 key 的 `YtdlpError`。
    """

    def __init__(self, site: str) -> None:
        self.site = site
        super().__init__(f"{site}: page parsing is not implemented yet")
