"""素材从哪来(来源链),以及「这份素材里有没有 AI 生成 / 合成的内容」。

**为什么要记。** 导出时要认出成片里用了 AI 生成的内容(《人工智能生成合成内容标识办法》,见 ADR 0028 §5),
而 AI 生成的素材常常不是原样进时间线的:截一段、切宫格、转 GIF、降噪、分离人声、导出成片再拿去剪……
每一步都登记成一份新素材。此前这些派生素材不记出处(有几处把出处塞在 media_info 里,各写各的),
只认生成记录的导出看到的是一份「普通的素材」,AI 标识就漏了。

**形状。** `Asset.derived_from` 是 `[{asset_id, op}]`:这份素材是从哪几份、经过什么操作做出来的,按出处的
先后排。一份对一份(截取、转 GIF)就一项;拼起来的(导出成片、拼接)就多项,各自带同一个 op。父素材自己也有
`derived_from`,一级一级往上就是整条来源链。

**「含 AI」在登记时就定下、写进素材**(`Asset.ai_generated`),不在导出时顺着来源链递归查库:
- 自己就是 AI 做的 —— 生成任务的产出、合成的配音 / 播客 / 数字人整段 —— 登记的人说一声(`ai_generated=True`);
- 否则任一出处含 AI,它就含 AI(继承)。

父素材总是先于子素材登记,所以登记那一刻读到的父素材标记就是最终的。写进素材还有一个递归查不到的好处:
**出处被删了,标记还在** —— 一段 AI 视频截出来、原片删掉,截出来的那段照样是 AI 内容。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.db.models import Asset

# 派生操作。界面按它显示「来自:xxx(截取)」(前端 assetLineage 的文案表),所以这是一张封闭的表。
TRIM = "trim"  # 截取一段(画板剪一段、对口型切块)
FRAME = "frame"  # 取一帧(素材取帧、时间线取当前帧)
GRID_SPLIT = "grid_split"  # 宫格切成单图
GIF = "gif"  # 视频转 GIF
DENOISE = "denoise"  # 降噪
SEPARATE = "separate"  # 分离人声 / 背景音
EXPORT = "export"  # 时间线导出成片:出处是成片里用到的每一份素材
CONCAT = "concat"  # 几段首尾相接成一段
PAD = "pad"  # 补静音补到某个时长
MIX = "mix"  # 几段混成一段(对口型的配音)
EXTRACT = "extract"  # 从文档里取出的插图
PLUGIN = "plugin"  # 插件拿这几份做出来的

OPS = frozenset({TRIM, FRAME, GRID_SPLIT, GIF, DENOISE, SEPARATE, EXPORT, CONCAT, PAD, MIX, EXTRACT, PLUGIN})

#: 来源链往上追几级、最多交回多少个节点(界面上的来源链)。导出成片的出处可以有几十份,再往上一级就是几百。
LINEAGE_DEPTH = 6
LINEAGE_NODES = 120


@dataclass(frozen=True)
class Derivation:
    """一项出处:从 `asset_id` 经过 `op` 做出来。"""

    asset_id: str
    op: str

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"unknown derivation op: {self.op}")

    def as_json(self) -> dict[str, str]:
        return {"asset_id": self.asset_id, "op": self.op}


def derived(op: str, *parents: str | None) -> tuple[Derivation, ...]:
    """`op` 做出来的,出处是这几份(去重、保持先后,空的跳过)。"""
    return tuple(Derivation(asset_id=parent, op=op) for parent in dict.fromkeys(parents) if parent)


def made_from(asset_id: str, op: str) -> ColumnElement[bool]:
    """SQL 条件:**一份对一份**、从 `asset_id` 经 `op` 做出来的素材(截取、转 GIF、降噪、分离……)。
    「这份素材之前拆过没有」这类缓存按它找,不再各自去 media_info 里翻一个自己约定的键。"""
    return and_(
        func.json_array_length(Asset.derived_from) == 1,
        func.json_extract(Asset.derived_from, "$[0].asset_id") == asset_id,
        func.json_extract(Asset.derived_from, "$[0].op") == op,
    )


def made_by(asset: Asset, op: str) -> bool:
    """这份素材是不是经 `op` 做出来的(比如分离出来的人声 / 背景音)。"""
    return any(isinstance(one, dict) and one.get("op") == op for one in asset.derived_from or [])


def inherits_ai(db: Session, derived_from: Iterable[Derivation]) -> bool:
    """出处里有没有含 AI 的。"""
    ids = {one.asset_id for one in derived_from}
    if not ids:
        return False
    return db.scalar(select(Asset.id).where(Asset.id.in_(ids), Asset.ai_generated.is_(True)).limit(1)) is not None


def ai_generated_assets(db: Session, asset_ids: Iterable[str]) -> set[str]:
    """这几份素材里哪些含 AI 生成 / 合成的内容 —— 成片里有它们,导出就加标识。

    读的是登记时定下、继承下来的标记(见模块说明),一次查询,不顺着来源链递归。"""
    ids = {one for one in asset_ids if one}
    if not ids:
        return set()
    return set(db.scalars(select(Asset.id).where(Asset.id.in_(ids), Asset.ai_generated.is_(True))))


def lineage_tree(db: Session, asset: Asset) -> list[dict]:
    """这份素材的来源链:每一项出处带名字、种类、含不含 AI,以及它自己的出处(往上至多 LINEAGE_DEPTH 级)。

    出处已经被删的,`name` / `kind` 是 None —— 界面写「已删除的素材」,而不是让这一项凭空消失。
    只认同一个工作区里的素材(派生素材总和出处在一个工作区;别的一律当找不到)。"""
    budget = [LINEAGE_NODES]

    def parents_of(row: Asset, depth: int, seen: frozenset[str]) -> list[dict]:
        entries = [one for one in row.derived_from or [] if isinstance(one, dict) and one.get("asset_id")]
        found = {
            one.id: one
            for one in db.scalars(select(Asset).where(
                Asset.id.in_([str(entry["asset_id"]) for entry in entries]), Asset.workspace_id == asset.workspace_id,
            ))
        } if entries else {}
        nodes: list[dict] = []
        for entry in entries:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            parent_id = str(entry["asset_id"])
            parent = found.get(parent_id)
            # 来源链不会成环(出处总是先登记的),seen 只是防一份坏数据把这里拖进死循环。
            deeper = parent is not None and depth + 1 < LINEAGE_DEPTH and parent_id not in seen
            nodes.append({
                "asset_id": parent_id,
                "op": str(entry.get("op") or ""),
                "name": parent.name if parent else None,
                "kind": parent.kind if parent else None,
                "ai_generated": bool(parent.ai_generated) if parent else None,
                "parents": parents_of(parent, depth + 1, seen | {parent_id}) if deeper else [],
            })
        return nodes

    return parents_of(asset, 0, frozenset({asset.id}))


__all__ = [
    "CONCAT",
    "DENOISE",
    "Derivation",
    "EXPORT",
    "EXTRACT",
    "FRAME",
    "GIF",
    "GRID_SPLIT",
    "LINEAGE_DEPTH",
    "LINEAGE_NODES",
    "MIX",
    "OPS",
    "PAD",
    "PLUGIN",
    "SEPARATE",
    "TRIM",
    "ai_generated_assets",
    "derived",
    "inherits_ai",
    "lineage_tree",
    "made_by",
    "made_from",
]
