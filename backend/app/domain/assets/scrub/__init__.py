"""清除元数据(ADR 0062):画面与声音逐字节不动的一份「干净」副本,外加一份对账。

模块分工:

- `policy` —— 默认剥什么、provenance 为什么另一个开关、支持到哪一步。**拍板结果都在这里。**
- `mp4` —— MP4/QuickTime 的盒子与样本表;只做**等长**的原地改写。
- `canonical` —— 重封装那一套参数,以及碎片化输入(moof)的**规范基准**(门禁比的那一份"输入")。
- `nal` —— H.264/H.265 的 NAL 与 SEI:x264 的编码设置、Lavf/Lavc 版本就藏在这儿。
- `aac` —— AAC 帧里的 `DSE` 与填充元素:有设备把账号塞这儿。
- `engine` —— 三步:重封装 → 原地改码流 → 自证。入口 `scrub_file`。
- `gates` —— 十道门,全部靠扫字节。
- `report` —— 对账文本。
- `findings` —— 清除前后的事实(对账和门禁读同一份)。
- `task` —— 领域编排:产出登记成派生素材、对账文本落盘、后台任务。
"""

from __future__ import annotations

from app.domain.assets.scrub.engine import ScrubError, ScrubOutcome, scrub_file
from app.domain.assets.scrub.findings import MediaFacts, inspect
from app.domain.assets.scrub.gates import check, run_all
from app.domain.assets.scrub.policy import DEFAULT_STRIP_KEYS, PROVENANCE, StripPlan, default_strip_list
from app.domain.assets.scrub.report import render
from app.domain.assets.scrub.verify import frame_md5, pcm_md5
from app.domain.assets.scrub.task import (
    DERIVED_SUFFIX,
    JOB_KIND,
    ScrubResult,
    removed_counts,
    report_path_for,
    require_video,
    scrub_asset,
    start_scrub_job,
)

__all__ = [
    "DEFAULT_STRIP_KEYS", "DERIVED_SUFFIX", "JOB_KIND", "MediaFacts", "PROVENANCE", "ScrubError",
    "ScrubOutcome", "ScrubResult", "StripPlan", "check", "default_strip_list", "inspect",
    "frame_md5", "pcm_md5", "removed_counts", "render", "report_path_for", "require_video",
    "run_all", "scrub_asset",
    "scrub_file", "start_scrub_job",
]
