"""生成里的 `@资产`(ADR 0027 §3):点名一个资产 = 把它的提示词描述拼进提示词,再从它的参考图里挑几张挂上。

五个入口(AI 工作台、画板、工作流的生成节点、智能体、定时任务)都汇到 `create_generation_job`,
它在校验之前调这里一次 —— 所以「挂几张、挂哪几张、挂不下怎么说」只在这一个函数里决定,
测试钉在 tests/test_entity_mentions.py。

## 挑哪几张

- 只挂**图片**,角色是参考图(`reference_image`)。先后按种类(catalog.ATTACH_PRIORITY):人物三视图 > 正面 > 全身,
  道具三视图 > 正面,场景全景 > 设定图;其余照资产里排的顺序。
- 能挂几张**只听描述符**(`source_limits.reference_image`),已经手动挂上的参考图先占名额。描述符查不到、
  没声明这个角色、没写上限、或者和已经挂上的首尾帧互斥(`exclusive_source_groups`),一张都不挂 —— 不猜。
- 点名了几个资产时轮流挑(甲一张、乙一张、甲第二张……),不让第一个把名额吃光:一镜里有两个人,
  两个人都要像。
- 挂不下的照实记进回执(`request.entities[].dropped` + `notes`),界面据此说「挂了哪几张、哪几张没挂上」。

## 先建主体再引用的模型(可灵)

描述符写了 `reference_subjects` 的模型,参考图不是「这次用几张图」,而是**先用 2～4 张图建一个主体**
(ai/providers/adapters/kuaishou/kling/elements)。这时每个资产是一个主体:它挑中的几张带上同一个
`subject`,适配器按它分组、每组建一个主体(名字仍按那几张图的内容哈希算,不另存映射表);
每组的第一张是正面图(可灵要求),凑不够 `min_reference_images` 张的资产不建主体、照实说。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers import roles_supplied_via_url
from app.db.models import Entity
from app.domain.entities.catalog import attach_order, parse_entity_ids
from app.domain.entities.library import EntityDomainError, references_of
from app.domain.generation.catalog import prompt_mode

#: 一次生成最多点名几个资产。
MAX_MENTIONS = 8

REFERENCE_ROLE = "reference_image"

#: 回执里的几种「为什么没挂」(界面按它说一句话,见前端 entityNote_*)。
NOTE_LIMIT = "limit"
NOTE_NO_ROLE = "no_reference_role"
NOTE_UNKNOWN = "unknown_limits"
NOTE_EXCLUSIVE = "exclusive"
NOTE_SUBJECT_TOO_FEW = "subject_too_few"
NOTE_PROMPT_SKIPPED = "prompt_skipped"


@dataclass
class _Mention:
    entity: Entity
    name: str
    descriptor: str
    #: 能挂的图(按挑图的先后)。
    images: list[str]
    #: 这张图是什么角度(给主体模型排正面图用)。
    roles: dict[str, str]
    attached: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Expansion:
    prompt: str
    source_assets: list[dict[str, str]]
    #: 写进生成请求的回执:每个点名的资产挂了哪几张、哪几张没挂上、为什么。
    receipt: list[dict[str, Any]]


def _mention(db: Session, entity: Entity) -> _Mention:
    """一个资产在生成里的样子。**变体继承母体的提示词描述**(ADR 0027 §1),只换参考图;
    变体自己一张参考图都没有时用母体的 —— 「张三 · 冬装」还没画好冬装那一套时,至少脸是张三的。"""
    parent = db.get(Entity, entity.parent_id) if entity.parent_id else None
    name = f"{parent.name} · {entity.name}" if parent is not None else entity.name
    descriptor = "，".join(part for part in ((parent.prompt if parent else ""), entity.prompt) if part.strip())
    refs = references_of(db, entity.id)
    if parent is not None and not any(asset.kind == "image" for _, asset in refs):
        refs = references_of(db, parent.id)
    images = [(ref.asset_id, ref.role) for ref, asset in refs if asset.kind == "image"]
    return _Mention(
        entity=entity,
        name=name,
        descriptor=descriptor.strip(),
        images=attach_order(entity.kind, images),
        roles=dict(images),
    )


def generation_profile(db: Session, entity: Entity) -> tuple[str, str, list[str]]:
    """生成时这个资产长什么样:(显示名, 提示词描述, 按挑图先后排好的图片参考图)。和 `@资产` 同一份规矩 ——
    变体带着母体的描述、自己没图时用母体的图。工作流的「取资产」节点交出的就是它。"""
    mention = _mention(db, entity)
    return mention.name, mention.descriptor, list(mention.images)


def resolve_mentions(db: Session, workspace_id: str, entity_ids: list[str]) -> list[Entity]:
    """点名的资产必须都在这个工作区。别处的 id 当场拒 —— 不能借一次生成读到别的工作区的参考图。"""
    if len(entity_ids) > MAX_MENTIONS:
        raise EntityDomainError("entityErr_tooManyMentions", limit=MAX_MENTIONS)
    out: list[Entity] = []
    for entity_id in entity_ids:
        entity = db.get(Entity, entity_id)
        if entity is None or entity.workspace_id != workspace_id:
            raise EntityDomainError("entityErr_mentionGone", id=entity_id[:12])
        out.append(entity)
    return out


def _budget(capabilities: dict[str, Any] | None, source_assets: list[dict[str, str]],
            parameters: dict[str, Any], kind: str) -> tuple[int, str]:
    """这一次还能挂几张参考图,以及挂不了时的原因。"""
    if capabilities is None:
        return 0, NOTE_UNKNOWN
    if REFERENCE_ROLE not in (capabilities.get("parameter_keys") or ()):
        return 0, NOTE_NO_ROLE
    cap = (capabilities.get("source_limits") or {}).get(REFERENCE_ROLE)
    if cap is None:
        return 0, NOTE_UNKNOWN
    via_url = roles_supplied_via_url(parameters, kind)
    used_roles = {str(entry.get("role") or "") for entry in source_assets}
    used_roles |= {role for role, count in via_url.items() if count}
    for group in capabilities.get("exclusive_source_groups") or []:
        # 已经挂上的角色落在另一组里,而参考图不在那一组 —— 这两组不能混用(火山原话见 catalog)。
        if REFERENCE_ROLE not in group and used_roles & set(group):
            return 0, NOTE_EXCLUSIVE
    taken = sum(1 for entry in source_assets if entry.get("role") == REFERENCE_ROLE)
    taken += via_url.get(REFERENCE_ROLE, 0)
    return max(0, int(cap) - taken), NOTE_LIMIT


def _round_robin(mentions: list[_Mention], budget: int, skip: set[str]) -> None:
    """轮流挑:每个资产先挂一张,再各挂第二张……名额用完为止。已经在请求里的素材不再挂一次。"""
    queues = [[one for one in mention.images if one not in skip] for mention in mentions]
    taken = set(skip)
    while budget > 0 and any(queues):
        for mention, queue in zip(mentions, queues):
            while queue and queue[0] in taken:
                queue.pop(0)
            if budget <= 0 or not queue:
                continue
            asset_id = queue.pop(0)
            mention.attached.append(asset_id)
            taken.add(asset_id)
            budget -= 1


def attach_entities(
    db: Session,
    workspace_id: str,
    entity_ids: list[str],
    *,
    prompt: str,
    source_assets: list[dict[str, str]],
    parameters: dict[str, Any],
    kind: str,
    capabilities: dict[str, Any] | None,
) -> Expansion:
    """把点名的资产展开成提示词和参考素材。没点名就原样返回(回执为空)。

    `capabilities` 是这个模型的描述符;查不到时是 None —— 那就不挂任何参考图(不知道它收几张)。
    """
    ids = parse_entity_ids(entity_ids)
    if not ids:
        return Expansion(prompt=prompt, source_assets=list(source_assets), receipt=[])
    mentions = [_mention(db, entity) for entity in resolve_mentions(db, workspace_id, ids)]

    # 提示词描述。不收提示词的模型(放大、抠图)不拼 —— 拼了提交会被拒,照实记一笔。
    lines = [f"{mention.name}: {mention.descriptor}" for mention in mentions if mention.descriptor]
    if lines and capabilities is not None and prompt_mode(capabilities) == "none":
        for mention in mentions:
            if mention.descriptor:
                mention.notes.append(NOTE_PROMPT_SKIPPED)
        lines = []
    expanded = "\n\n".join(part for part in (prompt.strip(), "\n".join(lines)) if part) if lines else prompt

    budget, reason = _budget(capabilities, source_assets, parameters, kind)
    already = {str(entry.get("asset_id") or "") for entry in source_assets}
    subjects = (capabilities or {}).get("reference_subjects") if budget else None
    if subjects:
        floor = int((capabilities or {}).get("min_reference_images") or 1)
        manual = sum(1 for entry in source_assets if entry.get("role") == REFERENCE_ROLE)
        room = int(subjects.get("max_subjects") or 1) - (1 if manual else 0)
        eligible: list[_Mention] = []
        for mention in mentions:
            usable = [one for one in mention.images if one not in already]
            if 0 < len(usable) < floor:
                mention.notes.append(NOTE_SUBJECT_TOO_FEW)
            elif usable:
                eligible.append(mention)
        fits = max(0, min(room, budget // floor))
        _round_robin(eligible[:fits], budget, already)
        chosen = eligible[:fits]
    else:
        chosen = mentions
        _round_robin(mentions, budget, already)

    added: list[dict[str, str]] = []
    for mention in chosen:
        order = mention.attached
        if subjects:
            # 主体的第一张是正面图(可灵的 frontal_image);没有正面图就按原来的先后。
            order = sorted(order, key=lambda one: 0 if mention.roles.get(one) == "front" else 1)
        for asset_id in order:
            entry = {"asset_id": asset_id, "role": REFERENCE_ROLE}
            if subjects:
                entry["subject"] = mention.entity.id
            added.append(entry)

    #: 两个资产共用一张图时,它被前一个挂上了 —— 对后一个来说也不算「没挂上」。
    sent = already | {one for mention in mentions for one in mention.attached}
    receipt: list[dict[str, Any]] = []
    for mention in mentions:
        dropped = [one for one in mention.images if one not in sent]
        notes = list(mention.notes)
        if dropped and not notes:
            notes.append(reason)
        receipt.append({
            "id": mention.entity.id,
            "name": mention.name,
            "kind": mention.entity.kind,
            "attached": list(mention.attached),
            "dropped": dropped,
            "notes": notes,
        })
    return Expansion(prompt=expanded, source_assets=[*source_assets, *added], receipt=receipt)


__all__ = ["Expansion", "MAX_MENTIONS", "attach_entities", "parse_entity_ids", "resolve_mentions"]

