"""中间产物:某道工序**逐条**做出来、只为拼成它的最终产物的那些素材。

逐句配音一条字幕配一段音频,一千句就是一千份「zh-TW-HsiaoChenNeural · 配音」—— 它们是配音这道工序的零件:
时间线、配音轨要用,人在素材库里找东西时不需要。素材行上的 `Asset.intermediate` 记着它是不是、是哪一种:

- 空串:素材库里的正常素材(导入的、生成的、导出的成片……);
- 下面这几种:素材库、挑素材的弹窗、智能体的 list_assets **默认不列**;时间线和工序照常按 id 用它,
  素材页「显示」里切过去看得到。

**谁做零件,谁在登记时说**(register_file_asset 的 `intermediate`、合成任务的 `start_synthesis(intermediate=…)`),
不靠名字或 media_info 里的标记事后去猜。加一种中间产物 = 在这里加一个取值 + 前端「显示」里的名字和说明。
"""

from __future__ import annotations

#: 逐句配音的一句:字幕配音给每条字幕合成的那一段;长稿分段配音拼进一段(或补过静音)之前的那一句。
DUB_LINE = "dub_line"
#: 对口型的一块:切出来交给改口型的原片块、配音块,和改好口型、还没接回整段的那一块。
LIPSYNC_CHUNK = "lipsync_chunk"

INTERMEDIATE_KINDS: tuple[str, ...] = (DUB_LINE, LIPSYNC_CHUNK)
