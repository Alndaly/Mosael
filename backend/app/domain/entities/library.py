"""资产库的读写:资产本身、参考图、变体、封面,以及「在哪里用过」「属于哪些资产」。

**归工作区**(ADR 0027 §1):每个入口先按工作区取行,取不到和不属于这个工作区是同一个答案(404)。
授权(谁能读、谁能写)在调用方 —— 路由点名 `ensure_workspace_perm`,智能体的工具走同一组路由。

参考图是素材库里的素材,这里只存引用;素材删掉时由 `forget_asset` 摘掉引用并记一笔「少了哪一张」
(素材的删除在 domain/assets/deletion,它在删行之前调这里)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset, Board, Entity, EntityReference, GenerationJob, Workflow, now
from app.domain.entities.catalog import (
    DEFAULT_ROLE,
    KINDS,
    MAX_LOST,
    MAX_NAME_CHARS,
    MAX_REFERENCES,
    MAX_TAG_CHARS,
    MAX_TAGS,
    MAX_TEXT_CHARS,
    ROLES,
    VOICE_LIBRARY_ENGINE,
    AttributeProblem,
    normalize_attributes,
    parse_entity_ids,
)


class EntityDomainError(LocalizedError, ValueError):
    """资产库说不行。带文案 key(`entityErr_*`);`status` 由子类给,边界照着翻(见 main.py)。"""

    status = 422


class EntityNotFound(EntityDomainError):
    """不存在和不属于这个工作区是同一个答案 —— 分开答等于告诉外人这个 id 存在。"""

    status = 404


class EntityConflict(EntityDomainError):
    status = 409


# ---------------------------------------------------------------------------------------------
# 取行


def get_entity(db: Session, workspace_id: str, entity_id: str) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None or entity.workspace_id != workspace_id:
        raise EntityNotFound("entityErr_notFound")
    return entity


def entity_workspace(db: Session, entity_id: str) -> str:
    """一个资产在哪个工作区。路由先拿它去过闸,再按工作区取行。"""
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise EntityNotFound("entityErr_notFound")
    return entity.workspace_id


def references_of(db: Session, entity_id: str) -> list[tuple[EntityReference, Asset]]:
    """这个资产的参考图(连同素材行),按 position 排。"""
    rows = db.execute(
        select(EntityReference, Asset)
        .join(Asset, Asset.id == EntityReference.asset_id)
        .where(EntityReference.entity_id == entity_id)
        .order_by(EntityReference.position, EntityReference.created_at)
    ).all()
    return [(ref, asset) for ref, asset in rows]


def variants_of(db: Session, entity_id: str) -> list[Entity]:
    return list(db.scalars(select(Entity).where(Entity.parent_id == entity_id).order_by(Entity.created_at)))


def list_entities(
    db: Session,
    workspace_id: str,
    *,
    kind: str = "",
    tag: str = "",
    query: str = "",
    parent_id: str = "",
    include_variants: bool = False,
) -> list[Entity]:
    """列资产。缺省只列母体(变体在母体的详情里);点名 `parent_id` 就列它的变体。

    `query` 同时在名字、描述、提示词描述里找 —— 找「红围巾」的时候,名字里往往没有这三个字。
    """
    stmt = select(Entity).where(Entity.workspace_id == workspace_id)
    if kind:
        if kind not in KINDS:
            raise EntityDomainError("entityErr_kind", kinds=" / ".join(KINDS))
        stmt = stmt.where(Entity.kind == kind)
    if parent_id:
        stmt = stmt.where(Entity.parent_id == parent_id)
    elif not include_variants:
        stmt = stmt.where(Entity.parent_id.is_(None))
    needle = query.strip().lower()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            func.lower(Entity.name).like(like)
            | func.lower(Entity.description).like(like)
            | func.lower(Entity.prompt).like(like)
        )
    rows = list(db.scalars(stmt.order_by(Entity.updated_at.desc(), Entity.id)))
    wanted = tag.strip()
    if wanted:
        # 标签存在 JSON 列里,按行比对 —— 一个工作区的资产是几十到几百个,不是素材那种成千上万。
        rows = [row for row in rows if wanted in (row.tags or [])]
    return rows


def find_by_name(db: Session, workspace_id: str, kind: str, name: str) -> Entity | None:
    """按种类和名字找一个资产(母体;名字不分大小写、不计首尾空白)。同名的有几个时取最近改过的那个。

    「认已有的资产」靠它:一部片子的剧本里写着「林小满」,资产库里有这个人物,就用它的参考图,不再重画一遍。
    """
    if kind not in KINDS:
        raise EntityDomainError("entityErr_kind", kinds=" / ".join(KINDS))
    wanted = " ".join(str(name or "").split()).lower()
    if not wanted:
        return None
    stmt = (
        select(Entity)
        .where(Entity.workspace_id == workspace_id, Entity.kind == kind, Entity.parent_id.is_(None))
        .where(func.lower(func.trim(Entity.name)) == wanted)
        .order_by(Entity.updated_at.desc(), Entity.id)
    )
    return db.scalars(stmt).first()


def counts_for(db: Session, entity_ids: list[str]) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    """一批资产的参考图张数、变体个数、第一张参考图(没有封面时的封面)。列表页一次查齐,不逐个问。"""
    if not entity_ids:
        return {}, {}, {}
    refs: dict[str, int] = {}
    first: dict[str, str] = {}
    for entity_id, asset_id, _position in db.execute(
        select(EntityReference.entity_id, EntityReference.asset_id, EntityReference.position)
        .join(Asset, Asset.id == EntityReference.asset_id)
        .where(EntityReference.entity_id.in_(entity_ids), Asset.kind == "image")
        .order_by(EntityReference.entity_id, EntityReference.position, EntityReference.created_at)
    ):
        refs[entity_id] = refs.get(entity_id, 0) + 1
        first.setdefault(entity_id, asset_id)
    variants = {
        parent: count
        for parent, count in db.execute(
            select(Entity.parent_id, func.count()).where(Entity.parent_id.in_(entity_ids)).group_by(Entity.parent_id)
        )
    }
    return refs, variants, first


def cover_of(entity: Entity, first_reference: str | None) -> str | None:
    """封面:设过就用设的那张;没设(或那张素材删了)就是第一张参考图。"""
    return entity.cover_asset_id or first_reference


# ---------------------------------------------------------------------------------------------
# 写


def _name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise EntityDomainError("entityErr_nameRequired")
    if len(name) > MAX_NAME_CHARS:
        raise EntityDomainError("entityErr_nameTooLong", limit=MAX_NAME_CHARS)
    return name


def _long_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_TEXT_CHARS:
        raise EntityDomainError("entityErr_textTooLong", field=field, limit=MAX_TEXT_CHARS)
    return text


def _tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EntityDomainError("entityErr_tagsNotList")
    cleaned: list[str] = []
    for tag in value:
        text = str(tag).strip()[:MAX_TAG_CHARS]
        if text and text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > MAX_TAGS:
        raise EntityDomainError("entityErr_tooManyTags", limit=MAX_TAGS)
    return cleaned


def _attributes(db: Session, workspace_id: str, kind: str, raw: Any, stored: dict[str, Any] | None,
                actor_id: str | None) -> dict[str, Any]:
    try:
        attributes = normalize_attributes(kind, raw, stored, actor_id=actor_id)
    except AttributeProblem as exc:
        raise EntityDomainError(exc.key, **exc.params) from exc
    _check_attribute_targets(db, workspace_id, attributes)
    return attributes


def _check_attribute_targets(db: Session, workspace_id: str, attributes: dict[str, Any]) -> None:
    """专有字段指着的东西得在:音色库里的嗓子、3D 场景、3D 模型要在这个工作区(别处的 id 当场拒,不存一个
    死链接);别的配音引擎要是认得的那几个(嗓子是引擎自己的目录里的,不在这里逐个去问)。"""
    from app.db.models import Scene3D, Scene3DModel, Voice
    from app.domain.voices.engine_catalog import PODCAST_ENGINE, describe_engines

    engine = attributes.get("voice_engine")
    if engine and engine != VOICE_LIBRARY_ENGINE:
        known = {str(one["id"]) for one in describe_engines(None)} - {PODCAST_ENGINE}
        if engine not in known:
            raise EntityDomainError("entityErr_voiceEngineUnknown", engine=engine)
    library_voice = ("voice_id", Voice) if engine == VOICE_LIBRARY_ENGINE else None
    for field, model in tuple(filter(None, (library_voice, ("scene_id", Scene3D), ("model_asset_id", Scene3DModel)))):
        target_id = attributes.get(field)
        if not target_id:
            continue
        row = db.get(model, target_id)
        if row is None or row.workspace_id != workspace_id:
            raise EntityDomainError("entityErr_attributeTargetGone", field=field)


def create_entity(
    db: Session,
    *,
    workspace_id: str,
    kind: str,
    name: str,
    description: str = "",
    prompt: str = "",
    attributes: Any = None,
    tags: Any = None,
    parent_id: str | None = None,
    actor_id: str | None = None,
) -> Entity:
    """建一个资产;给了 `parent_id` 就是那个资产的一个变体(种类跟着母体走,变体下面不再挂变体)。"""
    if parent_id:
        parent = get_entity(db, workspace_id, parent_id)
        if parent.parent_id:
            raise EntityDomainError("entityErr_variantOfVariant")
        if kind and kind != parent.kind:
            raise EntityDomainError("entityErr_variantKind")
        kind = parent.kind
    if kind not in KINDS:
        raise EntityDomainError("entityErr_kind", kinds=" / ".join(KINDS))
    entity = Entity(
        workspace_id=workspace_id,
        kind=kind,
        parent_id=parent_id or None,
        name=_name(name),
        description=_long_text(description, "description"),
        prompt=_long_text(prompt, "prompt"),
        attributes=_attributes(db, workspace_id, kind, attributes, None, actor_id),
        tags=_tags(tags),
        lost_references=[],
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


_UNSET: Any = object()


def update_entity(
    db: Session,
    entity: Entity,
    *,
    name: Any = _UNSET,
    description: Any = _UNSET,
    prompt: Any = _UNSET,
    attributes: Any = _UNSET,
    tags: Any = _UNSET,
    cover_asset_id: Any = _UNSET,
    actor_id: str | None = None,
) -> Entity:
    """改一个资产。没给的字段不动;`cover_asset_id` 给空串是「不要封面了」(退回第一张参考图)。"""
    if name is not _UNSET:
        entity.name = _name(name)
    if description is not _UNSET:
        entity.description = _long_text(description, "description")
    if prompt is not _UNSET:
        entity.prompt = _long_text(prompt, "prompt")
    if attributes is not _UNSET:
        entity.attributes = _attributes(db, entity.workspace_id, entity.kind, attributes, entity.attributes, actor_id)
    if tags is not _UNSET:
        entity.tags = _tags(tags)
    if cover_asset_id is not _UNSET:
        entity.cover_asset_id = _cover(db, entity, cover_asset_id)
    entity.updated_at = now()
    db.commit()
    db.refresh(entity)
    return entity


def _cover(db: Session, entity: Entity, asset_id: Any) -> str | None:
    """封面只能是**这个资产自己的一张参考图**,而且是图片 —— 卡片上画的是一张图。"""
    wanted = str(asset_id or "").strip()
    if not wanted:
        return None
    ref = db.get(EntityReference, (entity.id, wanted))
    asset = db.get(Asset, wanted)
    if ref is None or asset is None:
        raise EntityDomainError("entityErr_coverNotAReference")
    if asset.kind != "image":
        raise EntityDomainError("entityErr_coverNotImage")
    return wanted


def delete_entity(db: Session, entity: Entity, *, with_variants: bool = False) -> int:
    """删掉一个资产。**不删任何素材** —— 参考图还在素材库里。

    有变体的母体要调用方明说连变体一起删(界面在确认框里写清有几个变体)。不说就拒 ——
    一个「删除」顺手带走五个变体,而用户只看见了母体那一张卡。返回一共删了几个资产。
    """
    variants = variants_of(db, entity.id)
    if variants and not with_variants:
        raise EntityConflict("entityErr_hasVariants", count=len(variants))
    for variant in variants:
        db.delete(variant)
    # 先把变体删掉再删母体:同一批 DELETE 里母体的外键级联会抢先带走变体,ORM 就对不上行数。
    db.flush()
    db.delete(entity)
    db.commit()
    return 1 + len(variants)


def clear_lost_references(db: Session, entity: Entity) -> Entity:
    """「少了哪一张」那句提示看过了。"""
    entity.lost_references = []
    db.commit()
    db.refresh(entity)
    return entity


# ---------------------------------------------------------------------------------------------
# 参考图


def _role(value: Any, entity: Entity) -> str:
    role = str(value or "").strip() or DEFAULT_ROLE[entity.kind]
    if role not in ROLES:
        raise EntityDomainError("entityErr_role", roles=" / ".join(ROLES))
    return role


def add_reference(db: Session, entity: Entity, asset_id: str, role: Any = "", *, cover: bool = False) -> Entity:
    """挂一张参考图(排在最后)。同一份素材再挂一次 = 改它的角度,不重复挂。

    参考图可以是视频(一段转身的视频也是参考),但封面和生成时挂的参考图只认图片。
    """
    asset = db.get(Asset, str(asset_id or "").strip())
    if asset is None or asset.workspace_id != entity.workspace_id:
        raise EntityDomainError("entityErr_assetNotInWorkspace")
    if asset.kind not in ("image", "video"):
        raise EntityDomainError("entityErr_referenceKind")
    chosen = _role(role, entity)
    existing = db.get(EntityReference, (entity.id, asset.id))
    if existing is not None:
        existing.role = chosen
    else:
        count = db.scalar(select(func.count()).select_from(EntityReference).where(EntityReference.entity_id == entity.id))
        if (count or 0) >= MAX_REFERENCES:
            raise EntityDomainError("entityErr_tooManyReferences", limit=MAX_REFERENCES)
        last = db.scalar(select(func.max(EntityReference.position)).where(EntityReference.entity_id == entity.id))
        db.add(EntityReference(entity_id=entity.id, asset_id=asset.id, role=chosen, position=(last or 0) + 1))
    if cover:
        if asset.kind != "image":
            raise EntityDomainError("entityErr_coverNotImage")
        entity.cover_asset_id = asset.id
    entity.updated_at = now()
    db.commit()
    db.refresh(entity)
    return entity


def _reference(db: Session, entity: Entity, asset_id: str) -> EntityReference:
    ref = db.get(EntityReference, (entity.id, asset_id))
    if ref is None:
        raise EntityNotFound("entityErr_referenceNotFound")
    return ref


def set_reference_role(db: Session, entity: Entity, asset_id: str, role: Any) -> Entity:
    _reference(db, entity, asset_id).role = _role(role, entity)
    entity.updated_at = now()
    db.commit()
    db.refresh(entity)
    return entity


def remove_reference(db: Session, entity: Entity, asset_id: str) -> Entity:
    """摘掉一张参考图。素材本身不动;它若是封面,封面退回第一张参考图。"""
    db.delete(_reference(db, entity, asset_id))
    if entity.cover_asset_id == asset_id:
        entity.cover_asset_id = None
    entity.updated_at = now()
    db.commit()
    db.refresh(entity)
    return entity


def reorder_references(db: Session, entity: Entity, asset_ids: list[str]) -> Entity:
    """按给的顺序重排。**必须是这个资产现有参考图的一个排列** —— 少一张或多一张都拒:
    拖拽排序时另一个人刚挂了一张新的,按旧清单排会把那张挤到哪儿去说不清。"""
    refs = {ref.asset_id: ref for ref, _ in references_of(db, entity.id)}
    if sorted(asset_ids) != sorted(refs) or len(set(asset_ids)) != len(asset_ids):
        raise EntityConflict("entityErr_reorderMismatch")
    for position, asset_id in enumerate(asset_ids, start=1):
        refs[asset_id].position = position
    entity.updated_at = now()
    db.commit()
    db.refresh(entity)
    return entity


def forget_asset(db: Session, asset: Asset) -> int:
    """一份素材要删了:摘掉引用它的参考图,在那几个资产上记一笔「少了哪一张」。返回影响了几个资产。

    由 domain/assets/deletion 在删素材行**之前**调(同一个事务)。外键的 CASCADE 本来也会把引用行
    带走,但那样没人知道少了什么 —— 资产详情页上就是安安静静少一张,而那张可能正是封面。
    """
    rows = list(db.scalars(select(EntityReference).where(EntityReference.asset_id == asset.id)))
    if not rows:
        return 0
    stamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    for ref in rows:
        entity = db.get(Entity, ref.entity_id)
        if entity is None:
            continue
        lost = [*(entity.lost_references or []), {"name": asset.name, "role": ref.role, "at": stamp}]
        entity.lost_references = lost[-MAX_LOST:]
        if entity.cover_asset_id == asset.id:
            entity.cover_asset_id = None
        db.delete(ref)
    db.flush()
    return len(rows)


# ---------------------------------------------------------------------------------------------
# 反查


@dataclass(frozen=True)
class AssetMembership:
    entity: Entity
    role: str
    parent: Entity | None


def entities_of_asset(db: Session, asset: Asset) -> list[AssetMembership]:
    """这份素材是哪些资产的参考图(素材详情里的「属于哪些资产」)。"""
    rows = db.execute(
        select(EntityReference, Entity)
        .join(Entity, Entity.id == EntityReference.entity_id)
        .where(EntityReference.asset_id == asset.id, Entity.workspace_id == asset.workspace_id)
        .order_by(Entity.name)
    ).all()
    out: list[AssetMembership] = []
    for ref, entity in rows:
        parent = db.get(Entity, entity.parent_id) if entity.parent_id else None
        out.append(AssetMembership(entity=entity, role=ref.role, parent=parent))
    return out


@dataclass(frozen=True)
class Usage:
    #: `[(画板, 怎么用的)]`:`cell` 是板上有它的资产格,`mention` 是某一格的提示词里 @ 了它。
    boards: list[tuple[Board, str]]
    generations: list[GenerationJob]
    workflows: list[Workflow]


#: 「在哪里用过」里生成记录最多列几条(最新的在前)。
USAGE_GENERATION_LIMIT = 50


def board_uses(canvas: Any, entity_id: str) -> str | None:
    """一张画布怎么用到这个资产:有它的资产格(`cell`)、或提示词里 @ 了它(`mention`),都没有是 None。"""
    how: str | None = None
    for item in (canvas or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "entity" and item.get("entity_id") == entity_id:
            return "cell"
        form = item.get("form") if isinstance(item.get("form"), dict) else {}
        if entity_id in (form.get("mentioned_entity_ids") or []):
            how = "mention"
    return how


def entity_usage(db: Session, entity: Entity, *, visible_sessions: Any = None) -> Usage:
    """这个资产在哪里用过:画板(资产格 / 提示词里 @)、生成记录(请求里点名了它)、工作流(生成节点点名了它)。

    `visible_sessions`:调用方看得见的生成会话(一条 SQL 子查询)。私有会话里的记录不该在这里露出来 ——
    和生成记录列表同一个判据。

    都按 JSON 文本先粗筛、再逐行确认:一个工作区的画板 / 工作流是几十到几百张,生成记录只取最新的几十条。
    """
    needle = f"%{entity.id}%"
    boards: list[tuple[Board, str]] = []
    for board in db.scalars(
        select(Board).where(Board.workspace_id == entity.workspace_id, cast(Board.canvas, String).like(needle))
        .order_by(Board.updated_at.desc())
    ):
        how = board_uses(board.canvas, entity.id)
        if how:
            boards.append((board, how))
    stmt = select(GenerationJob).where(
        GenerationJob.workspace_id == entity.workspace_id, cast(GenerationJob.request, String).like(needle)
    )
    if visible_sessions is not None:
        stmt = stmt.where(GenerationJob.session_id.is_(None) | GenerationJob.session_id.in_(visible_sessions))
    generations = [
        one
        for one in db.scalars(stmt.order_by(GenerationJob.created_at.desc()).limit(USAGE_GENERATION_LIMIT * 2))
        if any(isinstance(row, dict) and row.get("id") == entity.id for row in (one.request or {}).get("entities") or [])
    ][:USAGE_GENERATION_LIMIT]
    workflows = [
        flow
        for flow in db.scalars(
            select(Workflow).where(Workflow.workspace_id == entity.workspace_id, cast(Workflow.graph, String).like(needle))
            .order_by(Workflow.updated_at.desc())
        )
        if any(
            entity.id in _entity_ids_in((node.get("config") or {}).get("entity_ids"))
            for node in (flow.graph or {}).get("nodes") or []
            if isinstance(node, dict)
        )
    ]
    return Usage(boards=boards, generations=generations, workflows=workflows)


def _entity_ids_in(value: Any) -> list[str]:
    """工作流节点里 `entity_ids` 的值:一串,或者逗号 / 换行分隔的一段字(可以是 `{{…}}` 引用)。"""
    return parse_entity_ids(value)
