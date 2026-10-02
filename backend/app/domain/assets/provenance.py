"""哪些素材是 AI 生成的 —— 时间线上的「AI」角标、导出对话框的「AI 生成」标识开关看的是同一份答案。

**不能只看 Asset.source。** `generated` 这个来源被导出成片、转 GIF、截帧、画板裁剪也用着,它们不是 AI 生成的;
而 AI 生成的东西经过降噪、拆图、裁剪之后,来源变成了别的,内容却还是 AI 生成的。所以按三条认:

1. 生成记录里有它(GeneratedAsset:图像 / 视频 / 音乐 / 数字人……每一份产出都登记了一行);
2. 来源本身就是合成:配音(tts)、播客(podcast)、数字人片段拼接(digital_human);
3. 它是从上面两种派生出来的(media_info.derived_from_asset_id 往上找,最多几层)。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, GeneratedAsset

#: 来源本身就是合成的。数字人拼接的来源名和 render.DIGITAL_HUMAN_SOURCE 是同一个。
AI_SOURCES = frozenset({"tts", "podcast", "digital_human"})
#: 派生链最多往上找几层(降噪了的、拆过的、裁过的 —— 真实链条很少超过两三层)。
_MAX_DEPTH = 5


def ai_generated_asset_ids(db: Session, asset_ids: Iterable[str]) -> set[str]:
    """这几份素材里哪些是 AI 生成的(见模块说明)。"""
    wanted = {one for one in asset_ids if one}
    if not wanted:
        return set()
    #: 每份素材 → 它的「祖先链」上出现过的素材(含自己)。
    lineage: dict[str, set[str]] = {one: {one} for one in wanted}
    frontier: dict[str, set[str]] = {one: {one} for one in wanted}
    ai: set[str] = set()
    for _ in range(_MAX_DEPTH):
        ids = set().union(*frontier.values()) if frontier else set()
        if not ids:
            break
        rows = {row.id: row for row in db.scalars(select(Asset).where(Asset.id.in_(ids)))}
        ai |= {asset_id for asset_id, row in rows.items() if row.source in AI_SOURCES}
        ai |= set(db.scalars(select(GeneratedAsset.asset_id).where(GeneratedAsset.asset_id.in_(ids))))
        next_frontier: dict[str, set[str]] = {}
        for origin, current in frontier.items():
            parents = {
                str(parent)
                for one in current
                if (row := rows.get(one)) is not None
                and (parent := (row.media_info or {}).get("derived_from_asset_id"))
                and str(parent) not in lineage[origin]
            }
            if parents:
                lineage[origin] |= parents
                next_frontier[origin] = parents
        frontier = next_frontier
    return {origin for origin, chain in lineage.items() if chain & ai}
