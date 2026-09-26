"""画板上存着的**插件节点产出者**跟上插件报出的清单(对账)。

画板上跑插件工具的地方有两处(ADR 0025 修订「能力住在内容格上」):内容格的**能力**
(`form.abilities["node:plugin.<包>.<工具>"] = {config, bindings}`)和空格子上的**生成器**
(`form.producer = "node:plugin.<包>.<工具>"`,同一格的 `form.config` / `form.bindings`)。两处存的都是一个工具的
名字加一份设置,插件升级、换了清单之后,这里把它们改成当下对得上的样子:

**被取代的工具**(`replaces`,规则在 domain/workflows/plugin_references 一处):配置按那张表改名,绑定的字段名
跟着改;一格对不上时,老工具还在就不动,老工具已经不在了就把没有位置的配置和绑定丢掉(和工作流那边同一条)。
能力换了名字,`abilities` 里的键跟着换 —— 不换的话,那一项的设置挂在一个不存在的名字下面,再也读不到。

**被生成取代的生成器**(ADR 0021 修订 · 一个概念一个入口)。插件报出的工具声明了 `mirrors`(它和某个生成模型是
同一件事,见 docs/PLUGIN_MANIFEST)、而那个连接的主人在生成目录里用得上那个模型时,画板上不再列这个工具
(boards.transforms 的 `mirrored_by_generation`)。空格子上存着的这种生成器改写成**生成**(产出者 `generate`、
选的就是那个模型),id、位置、大小、名字不变。带得过去的:

- 提示词:填的字原样带过去;接的是上游便签 / 文档时留空 —— 连线还在,生成的面板照上游便签填提示词、
  带上文档(和节点运行时「绑定的优先」是同一个结果);
- 素材:接上游的那几格按 `mirrors.sources` 换成生成的素材角色(记着 `from`,和面板照上游挂的一样);手挑的素材 id
  照样挂上;
- 参数:按 `mirrors.parameters` 改名(值原样,面板打开时按模型的描述符解读)。

带不过去的丢掉并记日志:没有写进 `mirrors` 的入参(ComfyUI 的宽和高 —— 生成里是一格「尺寸」、也取回预览)、
选的连接(生成选的是连接下的模型本身)和上一轮的运行状态。在跑的那一格不动,等它落终态;没选连接、几条连接
给出的模型不是同一个时也不动(和 replaces 同一条:说不准就不改),跑的时候说清楚去用生成。

**别的不合格不对账。** 一项能力或一个生成器此刻不在这个人的注册表里(插件卸了、连接是别人的、清单改说它按
另一个系统里的编号取东西 —— `external_id`),存着的名字和设置照样留着:注册表每次现算,那一项只是此刻不在
操作条上 / 切换里,跑的时候由注册表说清楚为什么(producers.get_producer);插件回来了,设置还在。此前按编号取
东西的工具格要改成便签(`retire_external_id_tools`),因为一格跑不了的工具格什么也不是;而能力的设置挂在一格
有内容的格子上,留着不碍事。

什么时候跑:插件的工具清单每刷新一次(`dynamic_tools.on_refreshed`,生成目录在它前面刷新,见清单里 `provides`
的顺序),以及每次启动(对账步骤 `rewrite-replaced-plugin-tools`)。`replaces`、`mirrors` 只有插件报出清单之后
才有,所以这是对账,不是一次性迁移;没有可改的就什么都不做。
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Board, PluginInstance
from app.domain.boards.producer_ids import node_producer_id, node_type_of

#: 生成的产出者(boards.producers 里内置的那一个)。
GENERATE_PRODUCER = "generate"

logger = logging.getLogger(__name__)


def _rewrite_setting(item_id: Any, producer: str, setting: dict[str, Any], found: list[Any]
                     ) -> tuple[str, dict[str, Any]] | None:
    """一份 `{config, bindings}`(跑 `producer` 的)被取代时改成什么:`(新产出者, 新设置)`;不用改回 None。"""
    from app.domain.workflows.plugin_references import MISSING, rewrite_node

    node_type = node_type_of(producer)
    if not node_type:
        return None
    dropped: list[str] = []
    result = rewrite_node(node_type, dict(setting.get("config") or {}), found, dropped)
    if result is None:
        return None
    new_type, converted, replacement = result
    bindings = setting.get("bindings") if isinstance(setting.get("bindings"), dict) else {}
    renamed: dict[str, Any] = {}
    for field, refs in bindings.items():
        target = replacement.target(str(field))
        if target is MISSING:
            if not replacement.retired:
                return None
            dropped.append(f"{field}(绑定)")  # 老工具已经不在了:这一格在新工具上没有位置,绑定拆掉
            continue
        renamed[target] = refs
    if dropped:
        logger.info("画板格子 %s 上的 %s 改写成 %s 时丢掉了 %s", item_id, producer, new_type, dropped)
    return node_producer_id(new_type), {**setting, "config": converted, "bindings": renamed}


def _rewrite_item(item: dict[str, Any], found: list[Any]) -> dict[str, Any] | None:
    """一格上被取代的插件节点(它自己的生成器、它的每一项能力)改掉;没有要改的回 None。"""
    form = item.get("form") if isinstance(item.get("form"), dict) else None
    if form is None:
        return None
    changed = False
    new_form = dict(form)
    own = str(form.get("producer") or "")
    rewritten = _rewrite_setting(item.get("id"), own, form, found)
    if rewritten is not None:
        producer, setting = rewritten
        new_form = {**{key: value for key, value in setting.items() if key != "producer"}, "producer": producer}
        changed = True
    abilities = form.get("abilities") if isinstance(form.get("abilities"), dict) else {}
    renamed: dict[str, Any] = {}
    for producer, setting in abilities.items():
        rewritten = _rewrite_setting(item.get("id"), producer, setting if isinstance(setting, dict) else {}, found)
        if rewritten is None:
            renamed.setdefault(producer, setting)
            continue
        new_name, new_setting = rewritten
        changed = True
        #: 新名字下已经存着一份(用户在新工具上用过)的,留新的那份:它是更晚的设置。
        renamed.setdefault(new_name, new_setting)
    if not changed:
        return None
    if abilities:
        own_keys = {key: value for key, value in new_form.items() if key not in ("abilities", "producer")}
        new_form = {**own_keys, "abilities": renamed,
                    **({"producer": new_form["producer"]} if "producer" in new_form else {})}
    return {**item, "form": new_form}


def rewrite_replaced_tools(db: Session) -> int:
    """把库里所有画板上能改的老插件节点(生成器、能力)改掉。返回改了几块画板。"""
    from app.domain.workflows.plugin_references import replacements

    found = replacements(db)
    if not found:
        return 0
    changed = 0
    for board in db.scalars(select(Board)):
        canvas = board.canvas if isinstance(board.canvas, dict) else {}
        items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
        touched = False
        rewritten_items = []
        for item in items:
            rewritten = _rewrite_item(item, found) if isinstance(item, dict) else None
            touched = touched or rewritten is not None
            rewritten_items.append(rewritten if rewritten is not None else item)
        if not touched:
            continue
        board.canvas = {**deepcopy(canvas), "items": rewritten_items}
        board.revision = (board.revision or 0) + 1
        changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 块画板上的老插件节点改写成了取代它的工具", changed)
    return changed


# ── 被生成取代的生成器 ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Mirror:
    """一个连接上的一个工具**和一个生成模型是同一件事**,而那个连接的主人用得上那个模型。"""

    package_id: str
    instance_id: str
    tool: str
    spec: dict[str, Any]
    kind: str
    provider: str
    provider_profile_id: str
    model: str


GenerationIndex = dict[tuple[str, str, str], Any]


def generation_index(db: Session, user_id: str | None, kinds: Any = None) -> GenerationIndex:
    """`user_id` 在生成目录里用得上的插件模型:(种类, 插件连接 id, 模型 id) → 那一行模型。

    问的就是生成选择器问的那一个(provider_models.models_for_capability),不另判「能不能用」;只收插件连接
    (`plugin_instance_id` 指回实例)下的 —— 工具和模型要是**同一个连接**的才算同一件事。
    """
    from app.domain import provider_models
    from app.domain.generation.catalog import GENERATION_KINDS

    index: GenerationIndex = {}
    for kind in kinds if kinds is not None else GENERATION_KINDS:
        if kind not in GENERATION_KINDS:
            continue
        for row in provider_models.models_for_capability(db, kind, user_id):
            profile = row.profile
            if profile is not None and profile.plugin_instance_id:
                index[(kind, str(profile.plugin_instance_id), str(row.model_id))] = row
    return index


def mirrored_model(index: GenerationIndex, instance_id: str, mirror: Any) -> Any:
    """这个连接上声明了 `mirror` 的工具,对得上的那一行生成模型;对不上(没声明、他用不了)回 None。"""
    if not isinstance(mirror, dict):
        return None
    return index.get((str(mirror.get("kind") or ""), instance_id, str(mirror.get("generation_model") or "")))


def mirrors(db: Session) -> list[Mirror]:
    """所有连接报出的工具里,声明了 `mirrors`、且连接的主人此刻用得上那个模型的那些。"""
    found: list[Mirror] = []
    indexes: dict[str, GenerationIndex] = {}
    for instance in db.scalars(select(PluginInstance)):
        for tool in instance.discovered_tools or []:
            spec = tool.get("mirrors") if isinstance(tool, dict) else None
            if not isinstance(spec, dict):
                continue
            owner = instance.owner_user_id or ""
            if owner not in indexes:
                indexes[owner] = generation_index(db, owner)
            row = mirrored_model(indexes[owner], instance.id, spec)
            if row is None:
                continue
            found.append(Mirror(instance.package_id, instance.id, str(tool.get("name") or ""), spec,
                                str(spec["kind"]), str(row.profile.vendor), str(row.provider_profile_id), str(row.model_id)))
    return found


def _given(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def as_generation_slot(item: dict[str, Any], by_id: dict[str, dict[str, Any]], found: list[Mirror], *,
                   any_kind: bool = False) -> dict[str, Any] | None:
    """一格空格子上的生成器被生成取代了 → 这一格改挂生成、选那个模型。改不了(有产出了、在跑、种类对不上、
    说不准)回 None。

    `any_kind`:这一格还不是一种素材格(升级前的工具格,见迁移 migrate-board-tool-cells-become-abilities)——
    改成生成的那一种素材的空格子。"""
    from app.ai.providers.contracts.generation import SOURCE_ROLES
    from app.domain.plugins.nodes import parse_node_type

    form = item.get("form") if isinstance(item.get("form"), dict) else None
    if form is None or item.get("asset_id"):
        return None
    parsed = parse_node_type(node_type_of(str(form.get("producer") or "")) or "")
    if parsed is None:
        return None
    if (item.get("run") or {}).get("status") in ("queued", "running"):
        return None  # 这一轮的回执要落回这一格:等它落终态,下一次对账再改
    package_id, tool_name = parsed
    config = dict(form.get("config") or {})
    bindings = form.get("bindings") if isinstance(form.get("bindings"), dict) else {}
    chosen = str(config.get("instance_id") or "")
    candidates = [one for one in found if one.package_id == package_id and one.tool == tool_name
                  and (not chosen or one.instance_id == chosen)]
    if len({(one.kind, one.provider_profile_id, one.model) for one in candidates}) != 1:
        return None
    mirror = candidates[0]
    if mirror.kind != item.get("kind") and not any_kind:
        return None  # 这一格是另一种素材的空格子:生成的那一种放不进来
    prompt_field = str(mirror.spec.get("prompt") or "")
    parameter_names = mirror.spec.get("parameters") if isinstance(mirror.spec.get("parameters"), dict) else {}
    source_roles = mirror.spec.get("sources") if isinstance(mirror.spec.get("sources"), dict) else {}

    dropped: list[str] = []
    prompt = ""
    parameters: dict[str, Any] = {}
    #: 字段 → 挂上去的素材。和运行时(tools.resolve_bindings)同一个先后:接了上游、上游有素材的,盖过手挑的。
    sources: dict[str, list[dict[str, str]]] = {}
    for field, value in config.items():
        if field == "instance_id" or not _given(value):
            continue
        if field == prompt_field:
            #: 接了上游的话,运行时用的是上游的字(绑定优先);生成的面板照连线填,这里留空。
            prompt = "" if bindings.get(field) else str(value)
        elif field in parameter_names:
            parameters[str(parameter_names[field])] = value
        elif source_roles.get(field) in SOURCE_ROLES:
            sources[field] = [{"asset_id": str(value), "role": str(source_roles[field])}]
        else:
            dropped.append(field)
    for field, refs in bindings.items():
        if field == prompt_field:
            continue  # 连线还在:上游便签 / 文档由生成的面板接上
        role = source_roles.get(field)
        if role not in SOURCE_ROLES:
            dropped.append(f"{field}(绑定)")
            continue
        #: 和面板照上游挂的一样:记着 `from`,线断了、上游换了素材就摘掉(canvas._drop_detached_bindings)。
        upstream = [by_id.get(str(ref.get("from") or "")) for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []
        attached = [{"asset_id": str(one["asset_id"]), "role": str(role), "from": str(one["id"])}
                    for one in upstream if one is not None and one.get("asset_id")]
        if attached:
            sources[field] = attached
    if dropped:
        logger.info("画板格子 %s 改挂生成(%s · %s)时带不过去:%s", item.get("id"), mirror.provider, mirror.model, dropped)
    kept = {key: value for key, value in item.items() if key not in ("form", "run")}
    abilities = {"abilities": form["abilities"]} if form.get("abilities") else {}
    return {
        **kept,
        "kind": mirror.kind,
        "form": {
            "prompt": prompt,
            "provider": mirror.provider,
            "provider_profile_id": mirror.provider_profile_id,
            "model": mirror.model,
            "parameters": parameters,
            "source_assets": [one for attached in sources.values() for one in attached],
            **abilities,
            "producer": GENERATE_PRODUCER,
        },
    }


def rewrite_mirrored_tools(db: Session) -> int:
    """把库里所有画板上空格子里被生成取代的生成器,改挂生成。返回改了几块画板。"""
    found = mirrors(db)
    if not found:
        return 0
    changed = 0
    for board in db.scalars(select(Board)):
        canvas = board.canvas if isinstance(board.canvas, dict) else {}
        items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
        by_id = {str(one.get("id")): one for one in items if isinstance(one, dict)}
        touched = False
        rewritten_items = []
        for item in items:
            rewritten = as_generation_slot(item, by_id, found) if isinstance(item, dict) else None
            touched = touched or rewritten is not None
            rewritten_items.append(rewritten if rewritten is not None else item)
        if not touched:
            continue
        board.canvas = {**deepcopy(canvas), "items": rewritten_items}
        board.revision = (board.revision or 0) + 1
        changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 块画板上被生成取代的插件生成器改挂了生成", changed)
    return changed


def reconcile_plugin_tool_cells(db: Session) -> None:
    """画板上存着的插件节点跟上插件报出的清单:先按 `replaces` 改名,再把被生成取代的生成器改挂生成。"""
    rewrite_replaced_tools(db)
    rewrite_mirrored_tools(db)


def _after_refresh(db: Session, instance: PluginInstance) -> None:
    reconcile_plugin_tool_cells(db)


def install() -> None:
    from app.domain.plugins import dynamic_tools

    dynamic_tools.on_refreshed(_after_refresh)


__all__ = [
    "Mirror",
    "as_generation_slot",
    "generation_index",
    "install",
    "mirrored_model",
    "mirrors",
    "reconcile_plugin_tool_cells",
    "rewrite_mirrored_tools",
    "rewrite_replaced_tools",
]
