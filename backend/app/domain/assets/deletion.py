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

from app.core.i18n import LocalizedError
from app.core.unit_of_work import after_commit
from app.db.models import Asset, Clip, GeneratedAsset, GenerationJob, PublishAccount
from app.db.models import Sequence as SequenceModel
from app.domain.sequences.offline import offline_snapshot
from app.media.paths import resolve_key


class AssetBeingPublished(LocalizedError, ValueError):
    """这份素材还有没发完的发布任务。先等它发完,或先取消那条发布。"""

    status = 409


def ensure_not_being_published(db: Session, asset: Asset) -> None:
    """还在发的素材不让删。

    发布器认领任务之后要按 `asset_id` 读这份文件、上传到平台;中途把文件删了,平台那头是一次传了一半的失败,
    而这边任务已经没有素材可重试。发完了(成功 / 失败 / 已取消)就随便删 —— 发布记录留着(见 PublishTask.asset_id)。
    """
    from app.domain.publish import active_tasks_for_asset

    active = active_tasks_for_asset(db, asset.id)
    if active:
        account = db.get(PublishAccount, active[0].account_id)
        raise AssetBeingPublished(
            "assetErr_beingPublished", name=asset.name, account=account.name if account else "", count=len(active),
        )


@dataclass(frozen=True)
class Deleted:
    """删掉了什么,以及顺带影响了多少段时间线。"""

    asset_id: str
    name: str
    #: 转成脱机占位的片段数。给调用方用来跟用户交代 —— 删完才发现少了一段,已经晚了。
    offline_clips: int


def _mark_generations_result_deleted(db: Session, asset: Asset) -> None:
    """产出是这份素材的那些生成,记上「产出已被删除」的时间。

    两个外键替我们清引用:generation_jobs.result_asset_id 是 SET NULL、generated_assets 是 CASCADE ——
    都不留痕迹,于是这条生成和「还在排队」长得一模一样(没结果、没失败、任务行也没了),界面说
    「排队中」还摆着一个按了也没用的「停止」。记上这一笔,界面才说得出「这份产出已被删除」。
    必须在 db.delete(asset) **之前**,同一个事务里 —— 之后那两个键已经空了。
    """
    refs = set(
        db.scalars(select(GenerationJob.id).where(GenerationJob.result_asset_id == asset.id))
    )
    refs |= set(
        db.scalars(
            select(GenerationJob.id).where(
                GenerationJob.job_id.in_(select(GeneratedAsset.job_id).where(GeneratedAsset.asset_id == asset.id))
            )
        )
    )
    if refs:
        from app.db.model_base import now

        db.execute(update(GenerationJob).where(GenerationJob.id.in_(refs)).values(result_deleted_at=now()))


def delete_asset(db: Session, asset: Asset) -> Deleted:
    """删掉这份素材。**调用方负责鉴权**,这里只管后果。

    引用它的片段**不跟着删**:位置、时长、变换、关键帧全部留着,只是没有画面可放(达芬奇的
    「媒体脱机」)。此前接口在这里直接 422「请先从时间线移除」,而用户手上往往有十几条序列,
    想删一个素材得先自己一条条翻出每一段。

    不记成可撤销的时间线操作:素材文件已经删了,撤销只能还回一个指向空文件的片段。

    **还在发布的不删**(见 ensure_not_being_published);发完的照删,发布记录留着、`asset_id` 置空。
    """
    ensure_not_being_published(db, asset)
    _mark_generations_result_deleted(db, asset)
    snapshot = offline_snapshot(asset)
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
    # 它若是哪个资产的参考图(ADR 0027),那张参考图随之摘掉,资产上记一笔「少了哪一张」。
    # 资产本身不动 —— 删素材不删资产。
    from app.domain.entities import forget_asset

    forget_asset(db, asset)
    db.flush()
    name = asset.name
    asset_id = asset.id
    file_dir = resolve_key(asset.file_key).parent if asset.file_key else None
    db.delete(asset)
    # **不在这里提交**(见 core/unit_of_work):一次删一批时要么全删、要么全不删。
    # 文件在**提交之后**才清:反过来的话,一次提交失败会留下一条指向空文件的素材记录 ——
    # 界面上它还在,点开是坏的,而没有任何地方记得它为什么坏。回滚了就不清。
    if file_dir is not None:
        after_commit(db, lambda: shutil.rmtree(file_dir, ignore_errors=True) if file_dir.is_dir() else None)
    return Deleted(asset_id=asset_id, name=name, offline_clips=count)
