"""一串 id 的两种写法:手填的逗号分隔串,和上游给的真列表。

两个都合法,因为两种写法都会真的到这里 —— 手填的配置给的是字符串,而 `{{查询.ids}}` 插值
出来的是 asset_query 交的那个列表。当成字符串(把列表 `str()` 了)会一个都匹配不上,而且
没有任何东西会报错。

**住在自己这个模块里,而不是某个执行器里**:绑定那一层也要用它 —— 「引用即发送」把提示词
引用到的素材并进「要模型看的图片」时,手动那一串和那份「不要自动带上」的排除清单都得按同一
条规矩解析(见 binding.with_referenced_assets)。放在 executors 下面的话 binding 就得回头
依赖执行器那一包,而执行器那一包要经引擎跑起来 —— 绑定是引擎的一部分,回头依赖执行器就绕成了环
(tests/test_import_layering 一个环都不许有)。执行器和绑定都直接从这里取(`id_list` 只有一个实现)。
"""

from __future__ import annotations

from typing import Any


def id_list(value: Any) -> list[str]:
    """逗号分隔的串(中文逗号也认)或真列表 → 去掉空项的一串字符串。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").replace("，", ",")
    return [part.strip() for part in text.split(",") if part.strip()]
