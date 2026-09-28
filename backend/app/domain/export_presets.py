"""导出的几档取值:剪辑页的导出对话框、工作流的「导出时间线」节点、画板时间线格的导出读的是这同一张表。

单独成一个不依赖任何人的模块:工作流的节点声明要列出这些取值,而导出本身(domain/render)很重。
"""

from __future__ import annotations

#: resolution 是目标短边档位,只降不升。
RESOLUTION_PRESETS = {"1080p": 1080, "720p": 720, "480p": 480}
#: quality 映射 (CRF, x264 preset)。
QUALITY_PRESETS = {"high": (18, "medium"), "standard": (20, "veryfast"), "compact": (26, "veryfast")}

#: 可选的分辨率:原样,或降到某一档。
EXPORT_RESOLUTIONS = ("original", *RESOLUTION_PRESETS)
EXPORT_QUALITIES = tuple(QUALITY_PRESETS)
