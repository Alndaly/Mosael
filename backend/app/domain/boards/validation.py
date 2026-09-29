"""画布上指向别处的东西(3D 场景、时间线、资产、文档、素材)在不在、对不对。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.boards.errors import BoardDomainError
from app.domain.boards.shape import _MEDIA_KINDS, normalize_canvas


#: 一种格子的 `asset_id` 必须是哪种素材(见 _validate_asset_references)。
#: 不在表里的种类只问「是不是这个工作区的」。
#: 文档格引用的素材得是文档(ADR 0031):一份 PDF / PPT 放上画板就是一格文档格,喂给下游的是解析出的全文。
_ASSET_KIND_OF_ITEM: dict[str, str] = {**{kind: kind for kind in _MEDIA_KINDS}, "document": "document"}


def _validate_references(
    db: Session, workspace_id: str, canvas: dict, existing: dict | None = None, *, assets: bool = True
) -> None:
    """画布上指向别处的东西在不在、对不对:3D 场景、文档,以及(`assets`)素材。

    `assets=False`:这一次写入是服务端自己落产出(回执)。那几份素材是产出者刚交回的,由回执那一侧
    按工作区查过(见 _asset_facts);在这里再拒一次的话,整封回执落不下,那一格就永远在转圈。
    """
    from app.db.models import Scene3D
    ids = {item['scene_id'] for item in canvas['items'] if item.get('scene_id')}
    if ids:
        owned = set(db.scalars(select(Scene3D.id).where(Scene3D.workspace_id == workspace_id, Scene3D.id.in_(ids))))
        if owned != ids:
            raise BoardDomainError("boardErr_sceneNotInWorkspace")

    # 时间线格引用的时间线:只查新引入的(同下面的资产格)—— 时间线在剪辑页被删了,那一格照样能挪、能删。
    from app.db.models import Sequence
    retained_sequences = {item.get("sequence_id") for item in (existing or {}).get("items", []) if item["kind"] == "sequence"}
    fresh_sequences = {item["sequence_id"] for item in canvas["items"]
                       if item["kind"] == "sequence" and item["sequence_id"] not in retained_sequences}
    if fresh_sequences:
        owned_sequences = set(db.scalars(select(Sequence.id).where(
            Sequence.workspace_id == workspace_id, Sequence.id.in_(fresh_sequences))))
        if owned_sequences != fresh_sequences:
            raise BoardDomainError("boardErr_sequenceNotInWorkspace")

    # 资产格引用的资产:**只查新引入的**,和文档、素材同一条 —— 资产删了之后那一格照样能挪、能删、能复制。
    from app.db.models import Entity
    retained_entities = {item.get("entity_id") for item in (existing or {}).get("items", []) if item["kind"] == "entity"}
    fresh_entities = {item["entity_id"] for item in canvas["items"]
                      if item["kind"] == "entity" and item["entity_id"] not in retained_entities}
    if fresh_entities:
        owned_entities = set(db.scalars(select(Entity.id).where(
            Entity.workspace_id == workspace_id, Entity.id.in_(fresh_entities))))
        if owned_entities != fresh_entities:
            raise BoardDomainError("boardErr_entityNotInWorkspace")

    from app.domain.notes import NoteDomainError, read_reference
    # 板上已经有的引用不再重新校验:源文档删掉之后,坏掉的引用照样能挪、能删、能复制。
    # **按「引用的是哪篇的哪一版」认,不按格子的 id 认** —— 画布上复制出来的那一格、副本里的
    # 那一格,和原来那格是同一份引用;按 id 认的话它们被当成新引用去校验,整张板存不下、复制不出。
    retained = {(item.get("note_id"), item.get("note_revision"))
                for item in (existing or {}).get("items", []) if item["kind"] == "document"}
    for item in canvas["items"]:
        if item["kind"] != "document" or not item.get("note_id"):
            continue
        if (item["note_id"], item["note_revision"]) in retained:
            continue
        try:
            ref = read_reference(db, workspace_id, item["note_id"], item["note_revision"])
            item["text"] = ref["title"]
        except NoteDomainError as exc:
            # 领域到领域的翻译:引用的文档有问题,对调用方来说是"这块画板存不下"。
            raise BoardDomainError(str(exc)) from exc

    if assets:
        _validate_asset_references(db, workspace_id, canvas, existing)


def _validate_asset_references(db: Session, workspace_id: str, canvas: dict, existing: dict | None) -> None:
    """一格的 `asset_id` 指着这个工作区里的一份素材,而且种类对得上格子(图片格放图片 —— 一段音频放进
    图片格,存得下、画出来却是一张裂图,生成时还会被当成参考图发出去)。

    **只查新引入的**,和文档同一条:板上已经有的「这种格子放这份素材」不再重新校验 —— 素材从库里删掉之后,
    那一格照样能挪、能删、能复制。按「哪种格子放哪份素材」认,不按格子的 id 认(复制出来的那一格是同一份引用)。
    """
    from app.db.models import Asset

    retained = {(item.get("kind"), item.get("asset_id"))
                for item in (existing or {}).get("items", []) if item.get("asset_id")}
    fresh = [item for item in canvas["items"]
             if item.get("asset_id") and (item["kind"], item["asset_id"]) not in retained]
    if not fresh:
        return
    ids = {item["asset_id"] for item in fresh}
    rows = db.execute(select(Asset.id, Asset.kind).where(Asset.workspace_id == workspace_id, Asset.id.in_(ids)))
    kinds = {str(asset_id): str(kind) for asset_id, kind in rows}
    for item in fresh:
        asset_kind = kinds.get(item["asset_id"])
        if asset_kind is None:
            raise BoardDomainError("boardErr_itemAssetNotInWorkspace", item_id=item["id"], asset_id=item["asset_id"])
        wanted = _ASSET_KIND_OF_ITEM.get(item["kind"])
        if wanted is not None and asset_kind != wanted:
            raise BoardDomainError("boardErr_itemAssetKindMismatch", item_id=item["id"], asset_id=item["asset_id"],
                                   kind=item["kind"], asset_kind=asset_kind)


def check_canvas(db: Session, workspace_id: str, raw: Any, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """一份画布存不存得下:形状(normalize_canvas)+ 引用(文档在不在、3D 场景和素材是不是这个工作区的、
    素材的种类对不对得上格子)。

    **落库和干跑共用这一道。** 智能体改画板时开卡前先干跑一遍,为的是写坏的算子在批准之前就失败;
    干跑只过形状的话,引用坏了要等用户点了同意才报错。`existing` 是这张板现在的样子(见
    _validate_references 里「已知引用」那一条)。
    """
    canvas = normalize_canvas(raw)
    _validate_references(db, workspace_id, canvas, existing)
    return canvas
