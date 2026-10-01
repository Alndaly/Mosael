"""`asset.media_info` 的**局部写**:只改自己那几个键,别人此刻写进去的键原样留着。

`media_info` 是一整列 JSON。读出来、改一个键、整份写回 —— 这一套在「只有我在写」时没问题,而一份素材
登记好之后,往往**同时**有好几方在补写:代理转码线程(proxy_status / proxy_key)、对口型记块
(dub_lipsync_chunk)、配音记音色(voice_id)…… 转码一跑几十秒,它在开头读出的那份 media_info 早就旧了,
整份写回就把这期间别人写的键抹掉。表现是「改口型的块缓存从来不命中」:块的标记写进去了,几秒后被代理任务
用转码前的旧值盖掉 —— 每次重跑都把钱再花一遍,而单独看哪一方的代码都没错。

所以补写一律走这里:一条 `UPDATE … SET media_info = json_set(media_info, …)`,改动在数据库里就地合并,
读和写之间没有缝。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.db.models import Asset


def _path(key: str) -> str:
    return '$."' + key.replace('"', '\\"') + '"'


def patch_media_info(db: Session, asset_id: str, values: dict[str, Any] | None = None, *, drop: Iterable[str] = ()) -> None:
    """把 `values` 里的键写进这份素材的 media_info、去掉 `drop` 里的键;其余键以库里**此刻**的为准。

    同一会话里已经加载的那个 Asset 对象,它的 media_info 会被标成过期,下次读到的是合并后的值。
    """
    #: 本会话里还没写下去的改动先写下去,免得它们稍后 flush 时拿旧的整份覆盖这次合并。
    db.flush()
    merged: Any = Asset.media_info
    for key, value in (values or {}).items():
        merged = func.json_set(merged, _path(key), func.json(json.dumps(value, ensure_ascii=False)))
    for key in drop:
        merged = func.json_remove(merged, _path(key))
    db.execute(
        update(Asset).where(Asset.id == asset_id).values(media_info=merged)
        .execution_options(synchronize_session="fetch"),
    )
