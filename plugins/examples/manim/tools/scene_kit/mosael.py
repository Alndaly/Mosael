"""自定义动画里拿调用方传进来的数据:`from mosael import DATA`。

工具调用时给的 `data`(一个对象)写在同目录的 data.json 里。代码写一次,数据从工作流上游换着喂 ——
同一个动画模板,换一组数字、一句标题就是另一段视频。
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    DATA: dict = json.loads((Path(__file__).with_name("data.json")).read_text(encoding="utf-8"))
except (OSError, ValueError):
    DATA = {}
