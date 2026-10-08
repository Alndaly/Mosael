"""界面上缓存着、会因为一次操作而过期的那几种数据(ADR 0053)。

一次操作改了什么,由**做这件事的那一方**声明:任务做完按 `job_catalog.JobKind.affects`,需要确认的工具批完按
`confirmable.ConfirmableTool.writes`。两边用的是同一套词;前端在 `frontend/src/api/resourceKeys.ts` 里把每一种换成
自己的缓存键 —— 后端不知道 React Query,词在这里,键在那边。

加一种:在这里加一个词,再在前端那张表里给它缓存键(漏了,前端的类型检查和 resourceKeys.test.ts 都会红)。
"""

from __future__ import annotations

from typing import Literal, get_args

Resource = Literal[
    "assets", "sequences", "transcripts", "workflows", "publish_tasks", "generations", "boards", "entities", "voices",
    "projects", "notes", "skills",
]

RESOURCES: tuple[str, ...] = get_args(Resource)

__all__ = ["RESOURCES", "Resource"]
