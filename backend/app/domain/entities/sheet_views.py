"""拼版参考图 → 单张视图:人物三视图拆成正面 / 侧面 / 背面,场景设计稿拆成俯视 / 反打 / 两张细节,挂回同一个资产。

**为什么要拆。** 三视图是一张图里横排三个人,设计稿是一张图 2×2 四格。交给出图模型当参考时,编辑类模型(FLUX.3、
Qwen-Image、MOSS,连 MiniMax H3 Image 也偶尔)会把**版式**一起照搬:关键帧被切成三格、四格,甚至六格(《长明灯》
第 2 场第 16 镜)。同一镜、同一模型、三个种子对照:交拼版图三张全是拼图,拆成单图再交三张全是一整张。信息一样多
(正侧背都在,不是只交正面),只是模型手里没有一个可以照搬的版式。

**拆法由角色定,不猜。** 三视图、设计稿都是 Mosael 自己按固定版式画的(templates/asset_prompts:三视图「三个全身像
并排」,设计稿「2×2,左上俯视、右上反方向平视、左下墙面门窗、右下地面道具」),所以按角色等分切;切出来的格子去掉
四周的分隔线(assets.image_grid 的 trim)。

**拆过一次就不再拆**:按来源认 —— 这张拼版图切出来、已经挂在这个资产上的那几张就是它的单张视图。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Entity
from app.domain.assets.image_grid import split_image_grid
from app.domain.assets.lineage import GRID_SPLIT, made_from
from app.domain.entities.library import add_reference, references_of

#: 拼版图的角色 → (等分切法, 切出来的每一格按阅读顺序标成什么角色)。
SHEET_VIEWS: dict[str, tuple[str, tuple[str, ...]]] = {
    "turnaround": ("1x3", ("front", "side", "back")),
    "design_sheet": ("2x2", ("overhead", "reverse", "detail", "detail")),
}

#: 每一种资产交给出图模型的单张视图,按先后(整片 / 漫剧逐镜画首尾帧时按这个取)。
VIEW_ROLES: dict[str, tuple[str, ...]] = {
    "character": ("front", "side", "back"),
    "location": ("overhead", "reverse", "detail"),
}


def attach_sheet_views(db: Session, entity: Entity) -> list[str]:
    """把这个资产上还没拆过的拼版图拆成单张视图挂回来,交回它该交给出图模型的参考图(见 `model_references`)。"""
    refs = references_of(db, entity.id)
    attached = {asset.id for _ref, asset in refs}
    for ref, sheet in refs:
        layout = SHEET_VIEWS.get(ref.role)
        if layout is None or sheet.kind != "image":
            continue
        grid, roles = layout
        split_before = db.scalars(select(Asset.id).where(made_from(sheet.id, GRID_SPLIT))).all()
        if any(asset_id in attached for asset_id in split_before):
            continue
        for piece, role in zip(split_image_grid(db, sheet, grid=grid, gutter=True), roles, strict=True):
            entity = add_reference(db, entity, piece.id, role)
    return model_references(db, entity)


def model_references(db: Session, entity: Entity) -> list[str]:
    """交给出图模型的参考图:**只有单张图**,拼版图(三视图、设计稿)一张都不交 —— 交了就会被照搬成几宫格。

    排序:先单张视图,按 VIEW_ROLES 的先后(人物正 → 侧 → 背,场景俯视 → 反打 → 细节),同一种按挂的先后;再是
    其它单张图(全身照、全景、概念图……),按挂的先后。一张单张图都没有时交回空列表,由调用方决定这算不算错
    (拆视图节点报错,见 workflows.executors.entities.entity_sheet_views)—— 这里不拿拼版图顶上。
    """
    images = [(position, ref.role, asset.id) for position, (ref, asset) in enumerate(references_of(db, entity.id))
              if asset.kind == "image" and ref.role not in SHEET_VIEWS]
    rank = {role: index for index, role in enumerate(VIEW_ROLES.get(entity.kind, ()))}
    others = len(rank)
    return [asset_id for _rank, _position, asset_id in
            sorted((rank.get(role, others), position, asset_id) for position, role, asset_id in images)]
