"""删掉一份素材,以及引用它的片段怎么办。

**这里是唯一的一处实现。** 删除有三个后果,少做任何一个都是静默的错:文件要从盘上清掉、
时间线上引用它的片段要转成脱机占位、受影响序列的版本号要推上去(序列的 JSON 响应按
`(id, revision)` 缓存,编辑器也靠轮询 revision 决定要不要重取 —— 不推的话时间线上那一段
会一直显示成原来的样子)。接口和智能体的确认卡走同一个函数,正是因为第三条最容易被漏掉。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip
from app.db.models import Sequence as SequenceModel
from app.media.paths import resolve_key


@dataclass(frozen=True)
class Deleted:
    """删掉了什么,以及顺带影响了多少段时间线。"""

    asset_id: str
    name: str
    #: 转成脱机占位的片段数。给调用方用来跟用户交代 —— 删完才发现少了一段,已经晚了。
    offline_clips: int


def delete_asset(db: Session, asset: Asset) -> Deleted:
    """删掉这份素材。**调用方负责鉴权**,这里只管后果。

    引用它的片段**不跟着删**:位置、时长、变换、关键帧全部留着,只是没有画面可放(达芬奇的
    「媒体脱机」)。此前接口在这里直接 422「请先从时间线移除」,而用户手上往往有十几条序列,
    想删一个素材得先自己一条条翻出每一段。

    不记成可撤销的时间线操作:素材文件已经删了,撤销只能还回一个指向空文件的片段。
    """
    snapshot = {
        "asset_id": asset.id,
        "name": asset.name,
        "kind": asset.kind,
        # 时长在 media_info 里,顶层没有这个字段(见 db/model_slices 的 Asset)。
        "duration": (asset.media_info or {}).get("duration"),
    }
    touched: set[str] = set()
    count = 0
    # asset_id 上的外键是 RESTRICT,所以要**先**把引用摘掉再删,而不是指望级联。
    for clip in db.scalars(select(Clip).where(Clip.asset_id == asset.id)):
        clip.offline_asset = dict(snapshot)
        clip.asset_id = None
        touched.add(clip.sequence_id)
        count += 1
    if touched:
        db.execute(
            update(SequenceModel).where(SequenceModel.id.in_(touched)).values(revision=SequenceModel.revision + 1)
        )
    db.flush()
    name = asset.name
    asset_id = asset.id
    file_dir = resolve_key(asset.file_key).parent if asset.file_key else None
    db.delete(asset)
    db.commit()
    # 文件在**提交之后**才清:反过来的话,一次提交失败会留下一条指向空文件的素材记录 ——
    # 界面上它还在,点开是坏的,而没有任何地方记得它为什么坏。
    if file_dir is not None and file_dir.is_dir():
        shutil.rmtree(file_dir, ignore_errors=True)
    return Deleted(asset_id=asset_id, name=name, offline_clips=count)
