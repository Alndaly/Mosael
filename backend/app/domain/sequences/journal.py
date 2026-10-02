"""片段级编辑的改动日志:一次编辑对时间线做了什么,逐条记下来;撤销倒着回放,重做顺着回放。

为什么不是每种操作各写一对「怎么撤销 / 怎么重做」:覆盖、修剪夹边、链接片段跟着动、跨轨波纹……
一次编辑的副作用会散到好几条轨、十几个片段上。每种操作手写一份还原,总有一处没还原干净 ——
被覆盖切掉的那一截、链接音频跟着挪的那一下、波纹左移的第七个片段。改动日志让「做了什么」和
「怎么撤」是**同一份数据**:编辑经由它改片段,撤销就不可能漏掉它改过的东西。

日志只有四种条目,都能原样倒放:

  - `create`:建了一个片段(记下它的全部字段,重做时按原 id 重建);
  - `delete`:删了一个片段(同上,撤销时按原 id 重建);
  - `update`:改了一个片段的几个字段(记下改之前和改之后);
  - `create_track`:为了放下片段新建了一条轨(分离音频时没有空的音频轨)。

**它不提交、不记账** —— 收尾仍是 `_record_operation`,日志作为 payload 的 `changes` 存进去;
倒放住在 undo/journal.py(撤销那一侧只认数据,不 import 编辑算子)。
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, Track
from app.domain.sequences._timeline import _clip_payload


class Journal:
    """一次编辑的改动日志。所有改片段的写入都经过它,它就是撤销要的全部信息。"""

    def __init__(self, db: Session, sequence: Sequence) -> None:
        self.db = db
        self.sequence = sequence
        self.entries: list[dict[str, Any]] = []

    def create(self, clip: Clip) -> Clip:
        self.db.add(clip)
        # flush:要 id 进日志;同一次编辑里接下来的查询(覆盖、波纹)也要看得到它。
        self.db.flush()
        self.entries.append({"op": "create", "clip": _clip_payload(clip)})
        return clip

    def delete(self, clip: Clip) -> None:
        self.entries.append({"op": "delete", "clip": _clip_payload(clip)})
        self.db.delete(clip)
        self.db.flush()

    def update(self, clip: Clip, **fields: Any) -> None:
        """改几个字段;没真变的不记(一条「从 3 改成 3」的条目只会让日志难读)。"""
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for name, value in fields.items():
            current = getattr(clip, name)
            if current == value:
                continue
            # JSON 列(transform / effects)存的是 dict:深拷贝,免得之后谁原地改了它、连带改了日志。
            before[name] = copy.deepcopy(current)
            after[name] = copy.deepcopy(value)
            setattr(clip, name, value)
        if after:
            self.entries.append({"op": "update", "clip_id": clip.id, "before": before, "after": after})

    def create_track(self, track: Track) -> Track:
        self.db.add(track)
        self.db.flush()
        self.entries.append(
            {
                "op": "create_track",
                "track": {
                    "id": track.id,
                    "kind": track.kind,
                    "name": track.name,
                    "position": track.position,
                    "role": track.role or "",
                },
            }
        )
        return track
