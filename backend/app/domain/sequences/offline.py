"""脱机占位的那份快照长什么样 —— 一个只认识 Asset 的叶子模块。

两处要写它:删素材时把引用它的片段转成脱机(domain/assets/deletion),以及撤销 / 重做重建
一个片段时发现素材已经没了(undo/rows)。两处各拼一份的话,迟早一边多一个字段、一边少一个,
而界面上脱机占位显示什么全看这份东西。
"""

from __future__ import annotations

from typing import Any

from app.db.models import Asset


def offline_snapshot(asset: Asset) -> dict[str, Any]:
    """`{asset_id, name, kind, duration}` —— 素材没了以后,占位上还写得出它原来是谁、多长。"""
    return {
        "asset_id": asset.id,
        "name": asset.name,
        "kind": asset.kind,
        # 时长在 media_info 里,顶层没有这个字段(见 db/model_slices 的 Asset)。
        "duration": (asset.media_info or {}).get("duration"),
    }
