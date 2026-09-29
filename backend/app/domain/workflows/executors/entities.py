"""资产库节点(ADR 0027 阶段 4):「取资产」把一个人物 / 场景 / 道具交给下游,「存成资产」把一套画好的图存回资产库。

两个节点合起来就是「先认已有的、新的存下来」:按名字取不到(`found = 0`)再去画,画完存成资产 ——
下一部片子里的同一个角色,是同一张脸。规矩都在 domain/entities:取出来的提示词描述和参考图先后和 `@资产`
同一份(`generation_profile`),存的时候校验和界面同一份(`create_entity` / `add_reference`)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.domain.jobs import current_actor
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.common import id_list, wait_for_job

#: 取资产时最多交出几张参考图(按挑图的先后)。
DEFAULT_REFERENCE_LIMIT = 8
#: 「存成资产」遇到同种类同名的资产怎么办:合并进去(补参考图、补空着的描述),还是另建一个。
IF_EXISTS = ("merge", "new")


def _text(value: Any) -> str:
    return str(value or "").strip()


@register("entity_get")
def entity_get(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """点名一个资产,或按「种类 + 名字」找一个。点名的找不到是错;按名字找不到不是错,`found` 给 0 ——
    那正是「这个角色还没有,先去画」的分支。"""
    from app.domain.entities import EntityDomainError, find_by_name, generation_profile, get_entity

    entity_id = _text(config.get("entity_id"))
    name = _text(config.get("name"))
    kind = _text(config.get("kind"))
    try:
        if entity_id:
            entity = get_entity(db, scope.workspace_id, entity_id)
        elif name and kind:
            entity = find_by_name(db, scope.workspace_id, kind, name)
        else:
            raise WorkflowDomainError("wfErr_entityGetNeedsTarget")
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    if entity is None:
        return {
            "entity_id": "", "found": 0, "name": name, "description": "", "prompt": "",
            "asset_ids": [], "asset_id": "", "voice_engine": "", "voice_id": "",
        }
    display, descriptor, images = generation_profile(db, entity)
    try:
        limit = int(config.get("limit") or DEFAULT_REFERENCE_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_REFERENCE_LIMIT
    picked = images[: max(1, limit)]
    attributes = entity.attributes or {}
    return {
        "entity_id": entity.id,
        "found": 1,
        "name": display,
        "description": entity.description,
        "prompt": descriptor,
        "asset_ids": picked,
        #: 封面:设过的那张,没设就是挑图顺序里的第一张。
        "asset_id": entity.cover_asset_id or (picked[0] if picked else ""),
        "voice_engine": str(attributes.get("voice_engine") or ""),
        "voice_id": str(attributes.get("voice_id") or ""),
    }


#: 「列资产」最多交出几个 —— 清单是给模型看的,太长了它挑不过来,提示词也吃不下。
DEFAULT_LIST_LIMIT = 30
MAX_LIST_LIMIT = 100


@register("entity_list")
def entity_list(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """列资产库里的人物 / 场景 / 道具(只列母体),按最近改过的排。

    `text` 是给模型读的清单(一行一个:名字 — 提示词描述),「从主题到完整视频」把它交给定角色的那一步:
    故事里要的人和库里某一个是同一个,就原名沿用 —— 下游「取资产」按名字认得出它,不再重画。
    """
    from app.domain.entities import EntityDomainError, list_entities

    kind = _text(config.get("kind"))
    try:
        limit = int(config.get("limit") or DEFAULT_LIST_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIST_LIMIT
    try:
        rows = list_entities(db, scope.workspace_id, kind=kind, tag=_text(config.get("tag")),
                             query=_text(config.get("query")))[: max(1, min(limit, MAX_LIST_LIMIT))]
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    entities = [
        {"id": row.id, "kind": row.kind, "name": row.name, "description": row.description, "prompt": row.prompt,
         "tags": list(row.tags or [])}
        for row in rows
    ]
    text = "\n".join(f"- {one['name']} — {one['prompt'] or one['description'] or '(无描述)'}" for one in entities)
    return {"entities": entities, "count": len(entities), "text": text}


@register("entity_save")
def entity_save(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一套图存成资产。同种类同名的已经有了,缺省**合并**:补上它还没挂的参考图,提示词描述 / 描述只在
    原来空着时填 —— 人手改过的不被一次运行覆盖。选「另建一个」就总是新建。"""
    from app.domain.entities import (
        EntityDomainError,
        add_reference,
        create_entity,
        find_by_name,
        references_of,
        update_entity,
    )

    kind = _text(config.get("kind"))
    name = _text(config.get("name"))
    if not name:
        raise WorkflowDomainError("wfErr_entitySaveNeedsName")
    mode = _text(config.get("if_exists")) or "merge"
    if mode not in IF_EXISTS:
        raise WorkflowDomainError("wfErr_entitySaveIfExists", params={"options": " / ".join(IF_EXISTS)})
    description = _text(config.get("description"))
    prompt = _text(config.get("prompt"))
    role = _text(config.get("role"))
    asset_ids = list(dict.fromkeys(id_list(config.get("asset_ids"))))
    actor = current_actor(db)
    try:
        existing = find_by_name(db, scope.workspace_id, kind, name) if mode == "merge" else None
        if existing is None:
            entity = create_entity(
                db,
                workspace_id=scope.workspace_id,
                kind=kind,
                name=name,
                description=description,
                prompt=prompt,
                tags=id_list(config.get("tags")),
                actor_id=actor,
            )
            created = True
        else:
            entity = existing
            fill: dict[str, Any] = {}
            if prompt and not entity.prompt.strip():
                fill["prompt"] = prompt
            if description and not entity.description.strip():
                fill["description"] = description
            tags = id_list(config.get("tags"))
            if tags and not set(tags) <= set(entity.tags or []):
                fill["tags"] = [*(entity.tags or []), *(tag for tag in tags if tag not in (entity.tags or []))]
            if fill:
                entity = update_entity(db, entity, actor_id=actor, **fill)
            created = False
        attached = {ref.asset_id for ref, _ in references_of(db, entity.id)}
        added = 0
        for asset_id in asset_ids:
            if asset_id in attached:
                continue
            entity = add_reference(db, entity, asset_id, role)
            attached.add(asset_id)
            added += 1
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    return {"entity_id": entity.id, "created": 1 if created else 0, "added": added, "name": entity.name}


# ── 资产格的能力:补全多角度、生成表情(ADR 0027 §3「画板」)────────────────────────────────
#
# 两个都是「拿这个资产现有的参考图,再画几张同一个人 / 同一件东西」:每一张是一次普通的生成,`@` 着这个资产
# (提示词描述和参考图照 `@资产` 那条路挂上,domain/entities/mentions),画完按角度挂回这个资产的参考图。
# 画板上它们是资产格的能力(产出新建在右边),工作流里是两个节点 —— 同一个执行器。

#: 每一种资产「多角度」画哪几张:(角度, 提示词)。人物和道具按正面 / 侧面 / 背面 / 三视图补;场景没有「正侧背」,
#: 它的角度是机位:全景、反打、俯视(catalog.ROLES_BY_KIND)。
#: 提示词用英文写:资产的提示词描述会原样拼在后面,各家图像模型认英文的最齐。
ANGLE_VIEWS: dict[str, tuple[tuple[str, str], ...]] = {
    "character": (
        ("front", "Front view of the same character, facing the camera, full body, standing straight, "
                  "plain light grey background."),
        ("side", "Side view of the same character, 90-degree profile facing left, full body, standing straight, "
                 "plain light grey background."),
        ("back", "Back view of the same character, seen from behind, full body, standing straight, "
                 "plain light grey background."),
        ("turnaround", "Character turnaround sheet of the same character: front, side and back views side by side, "
                       "full body, same scale, plain white background."),
    ),
    "prop": (
        ("front", "Front view of the same object, centered, plain light grey background, soft studio light."),
        ("side", "Side view of the same object, centered, plain light grey background, soft studio light."),
        ("back", "Back view of the same object, centered, plain light grey background, soft studio light."),
        ("turnaround", "Product turnaround sheet of the same object: front, side, back and top views side by side, "
                       "same scale, plain white background."),
    ),
    "location": (
        ("wide", "Wide establishing shot of the same place, eye level, showing the whole space."),
        ("reverse", "Reverse angle of the same place, the camera turned around to look the other way."),
        ("overhead", "High-angle view of the same place from above, showing its layout."),
    ),
}
#: 每一张都要守的那一句:和参考图是同一个,不要变样。
SAME_AS_REFERENCE = ("Keep it identical to the reference images: same face, hairstyle, outfit, materials and colors. "
                     "No text, no watermark.")
#: 「补全」只画还没有的角度(缺省),还是每个角度都重画一张。
ANGLE_SCOPES = ("missing", "all")

#: 「生成表情」没写几种时画这几种(拼进英文提示词,所以用英文写);写了的按逗号 / 顿号 / 换行分开,最多画这么多张。
DEFAULT_EXPRESSIONS = "smiling, laughing, surprised, angry, sad"
MAX_EXPRESSIONS = 8
EXPRESSION_PROMPT = ("Close-up portrait of the same character with a {expression} expression, head and shoulders, "
                     "plain light grey background.")


def takes_reference_images(option: dict[str, Any]) -> bool:
    """这个生成选项收不收参考图。不收的只看得到文字描述,画出来是另一个人 —— 「补全」「表情」就没意义了。
    模型下拉(选项来源 `reference_image_models`)和运行前的检查问的是这同一句。"""
    from app.domain.entities.mentions import REFERENCE_ROLE

    capabilities = option.get("capabilities") or {}
    return bool(option.get("adapter_available")) and REFERENCE_ROLE in (capabilities.get("parameter_keys") or ()) \
        and bool((capabilities.get("source_limits") or {}).get(REFERENCE_ROLE))


def _reference_model(db: Session, choice: str, actor_id: str | None) -> dict[str, Any]:
    """用哪个图片模型:点名的那一个(`reference_image_models` 的选项 id),没点名是这个人设的默认图片模型。"""
    from app.domain.generation.resolution import generation_options

    options = generation_options(db, "image", user_id=actor_id)
    picked = next((one for one in options if one["id"] == choice), None) if choice else \
        next((one for one in options if one["is_default"]), None)
    if picked is None:
        raise WorkflowDomainError("wfErr_entityModelMissing" if choice else "wfErr_entityModelNoDefault")
    if not takes_reference_images(picked):
        raise WorkflowDomainError("wfErr_entityModelNoReferences", params={"model": picked["label"]})
    return picked


def expression_list(value: Any) -> list[str]:
    """「微笑, 大笑、惊讶」→ 一种一张,去重,最多 MAX_EXPRESSIONS 种。"""
    import re

    parts = [part.strip() for part in re.split(r"[,,、;;\n]+", str(value or "")) if part.strip()]
    return list(dict.fromkeys(parts))[:MAX_EXPRESSIONS]


@dataclass(frozen=True)
class Drawing:
    """一次「补全多角度 / 生成表情」要画的东西:给哪个资产、每张(角度, 提示词)、用哪个模型(生成选项)。"""

    entity_id: str
    entity_name: str
    shots: tuple[tuple[str, str], ...]
    model: dict[str, Any]


def plan_drawing(db: Session, workspace_id: str, node_type: str, config: dict[str, Any],
                 actor_id: str | None) -> Drawing:
    """画之前的全部检查,**不花钱、不写任何东西**:资产在不在、有没有图片参考图、模型收不收参考图、
    要画哪几张(都有了就直说)。节点跑的时候先过它;资产详情页点「开始」时也先过它,说不通的当场说,
    不起一个注定失败的任务(见 domain/entities/drawing)。"""
    from app.domain.entities import EntityDomainError, generation_profile, get_entity, references_of

    entity_id = _text(config.get("entity_id"))
    if not entity_id:
        raise WorkflowDomainError("wfErr_entityNeedsTarget")
    try:
        entity = get_entity(db, workspace_id, entity_id)
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    if node_type == "entity_expressions":
        if entity.kind != "character":
            raise WorkflowDomainError("wfErr_entityExpressionsCharacterOnly", params={"name": entity.name})
        expressions = expression_list(config.get("expressions")) or expression_list(DEFAULT_EXPRESSIONS)
        shots = [("expression", EXPRESSION_PROMPT.format(expression=one)) for one in expressions]
    else:
        mode = _text(config.get("scope")) or "missing"
        if mode not in ANGLE_SCOPES:
            raise WorkflowDomainError("wfErr_entityAnglesScope", params={"options": " / ".join(ANGLE_SCOPES)})
        shots = list(ANGLE_VIEWS.get(entity.kind, ()))
        if mode == "missing":
            have = {ref.role for ref, _asset in references_of(db, entity.id)}
            shots = [shot for shot in shots if shot[0] not in have]
    _name, _descriptor, images = generation_profile(db, entity)
    if not images:
        raise WorkflowDomainError("wfErr_entityNeedsImage", params={"name": entity.name})
    if not shots:
        raise WorkflowDomainError("wfErr_entityAnglesComplete", params={"name": entity.name})
    model = _reference_model(db, _text(config.get("model")), actor_id)
    return Drawing(entity.id, entity.name, tuple(shots), model)


def draw_and_attach(db: Session, scope: RunScope, drawing: Drawing) -> dict[str, Any]:
    """按计划各画一张,`@` 着这个资产;画成的按角度挂回它的参考图。

    几张一起起、一起等(每张是一次独立的生成任务,挂在这一轮下面,取消这一轮就一并停)。有几张没画成的,
    画成的照样挂上,`failed` 说几张没成;一张都没成才算这一步失败(带着第一张的原因)。
    """
    from app.domain.entities import EntityDomainError, add_reference, get_entity
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.runner import start_generation_thread

    model = drawing.model
    started: list[tuple[str, str, str]] = []
    try:
        for role, prompt in drawing.shots:
            generation, child = create_generation_job(
                db,
                workspace_id=scope.workspace_id,
                session_id=None,
                project_id=None,
                created_by=current_actor(db),
                provider=model["provider"],
                provider_profile_id=model["provider_profile_id"],
                model=model["model"],
                kind="image",
                prompt=f"{prompt} {SAME_AS_REFERENCE}",
                negative_prompt="",
                parameters={},
                source_assets=[],
                entity_ids=[drawing.entity_id],
            )
            started.append((role, generation.id, child.id))
    except GenerationDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    db.commit()
    for _role, generation_id, _child in started:
        start_generation_thread(generation_id)

    drawn: list[tuple[str, str]] = []
    errors: list[WorkflowDomainError] = []
    for role, _generation, child_id in started:
        try:
            final = wait_for_job(child_id, release=db)
        except WorkflowDomainError as exc:
            #: 这一轮在停(取消)不是「这一张没画成」—— 照原样往外抛,别的几张由 wait 的收尾一并取消。
            if exc.key == "wfErr_cancelled":
                raise
            errors.append(exc)
            continue
        drawn.extend((role, str(one)) for one in (final.result or {}).get("asset_ids") or [] if one)
    if not drawn:
        raise errors[0] if errors else WorkflowDomainError("wfErr_entityNothingDrawn")
    try:
        entity = get_entity(db, scope.workspace_id, drawing.entity_id)
        for role, asset_id in drawn:
            entity = add_reference(db, entity, asset_id, role)
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    asset_ids = [asset_id for _role, asset_id in drawn]
    return {"asset_ids": asset_ids, "asset_id": asset_ids[0], "entity_id": drawing.entity_id,
            "added": len(asset_ids), "failed": len(errors)}


@register("entity_angles")
def entity_angles(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """补全多角度:人物、道具补上正面 / 侧面 / 背面 / 三视图里还没有的,场景补全景 / 反打 / 俯视(或者全部重画)。"""
    return draw_and_attach(db, scope, plan_drawing(db, scope.workspace_id, "entity_angles", config, current_actor(db)))


@register("entity_expressions")
def entity_expressions(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """生成表情:同一个人物的几种表情,一种一张,挂成「表情」参考图。只有人物有表情。"""
    return draw_and_attach(db, scope, plan_drawing(db, scope.workspace_id, "entity_expressions", config,
                                                   current_actor(db)))
